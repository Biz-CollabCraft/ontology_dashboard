"""Immutable versioned Model Artifact publication for the generator system."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_TYPE = "predictive_maintenance_model"
ARTIFACT_SCHEMA_VERSION = "model-artifact-v1.0"
REQUIRED_ARTIFACT_ROLES = ("model", "feature_schema", "label_schema", "history_requirement", "metrics")
REQUIRED_MANIFEST_FIELDS = {
    "artifact_type",
    "artifact_schema_version",
    "model_id",
    "model_version",
    "dataset_version",
    "feature_schema_version",
    "created_at",
    "training_config",
    "metrics",
    "checksum",
    "provenance",
    "compatibility",
    "artifact_files",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_root(uri: str | Path) -> Path:
    text = str(uri)
    if text.startswith("file://"):
        return Path(text[7:]).expanduser().resolve()
    if "://" in text:
        raise ValueError(
            "this local publisher supports filesystem/file:// MODEL_ARTIFACT_URI values only; "
            "object-storage/registry adapters must be injected separately"
        )
    return Path(text).expanduser().resolve()


def validate_manifest(manifest: dict[str, Any]) -> None:
    missing = sorted(REQUIRED_MANIFEST_FIELDS - manifest.keys())
    if missing:
        raise ValueError(f"Model Artifact manifest is missing fields: {missing}")
    if manifest["artifact_type"] != ARTIFACT_TYPE:
        raise ValueError("unexpected Model Artifact type")
    if manifest["artifact_schema_version"] != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported Model Artifact schema version")
    if not manifest["artifact_files"]:
        raise ValueError("Model Artifact must publish at least one artifact file")


def publish_model_artifact(
    *,
    artifact_uri: str | Path,
    model_id: str,
    model_version: str,
    dataset_version: str,
    feature_schema_version: str,
    model_file: str | Path,
    feature_schema: dict[str, Any],
    training_config: dict[str, Any],
    metrics: dict[str, Any],
    provenance: dict[str, Any],
    compatibility: dict[str, Any],
    label_schema: dict[str, Any] | None = None,
    history_requirement: dict[str, Any] | None = None,
    prediction_contract: dict[str, Any] | None = None,
    model_runtime: dict[str, Any] | None = None,
    dataset_schema_version: str = "pdm-dataset-v1",
    label_schema_version: str | None = None,
    history_requirement_version: str | None = None,
    metrics_schema_version: str = "pdm-metrics-v1",
    extra_files: dict[str, str | Path] | None = None,
) -> Path:
    """Publish an immutable Model Artifact package atomically.

    The final path is ``<artifact_root>/<model_id>/<model_version>``. Existing
    immutable versions are never overwritten.
    """
    root = _local_root(artifact_uri)
    destination = root / model_id / model_version
    if destination.exists():
        raise FileExistsError(
            f"Model Artifact already published for model_id={model_id!r}, "
            f"model_version={model_version!r}; immutable publish forbids overwrite"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{model_version}-", dir=destination.parent))
    try:
        files: list[dict[str, str]] = []

        def copy_or_create(role: str, source: str | Path | None, target_name: str, fallback_data: dict[str, Any] | None = None) -> None:
            target = staging / target_name
            if source is not None and Path(source).exists():
                shutil.copy2(Path(source), target)
            elif fallback_data is not None:
                target.write_text(json.dumps(fallback_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                target.write_text("{}\n", encoding="utf-8")
            files.append({"role": role, "path": target_name, "sha256": _sha256(target)})

        # 1. model.joblib
        copy_or_create("model", model_file, "model.joblib")

        # 2. feature_schema.json
        copy_or_create("feature_schema", None, "feature_schema.json", fallback_data=feature_schema)

        # 3. label_schema.json
        resolved_label_schema = label_schema or {
            "label_schema_version": label_schema_version or "pdm-label-v1",
            "target": feature_schema.get("target", "label"),
            "prediction_task": "binary_failure_within_horizon",
            "prediction_horizon_hours": 24,
        }
        copy_or_create("label_schema", None, "label_schema.json", fallback_data=resolved_label_schema)

        # 4. history_requirement.json
        resolved_history = history_requirement or {
            "history_requirement_version": history_requirement_version or "pdm-history-v1",
            "expected_sampling_interval_seconds": 3600,
            "minimum_history_rows": 10,
            "maximum_lookback_hours": 24,
        }
        copy_or_create("history_requirement", None, "history_requirement.json", fallback_data=resolved_history)

        # 5. metrics.json
        resolved_metrics = dict(metrics)
        if "metrics_schema_version" not in resolved_metrics:
            resolved_metrics["metrics_schema_version"] = metrics_schema_version
        copy_or_create("metrics", None, "metrics.json", fallback_data=resolved_metrics)

        # Optional extra files
        for role, source in sorted((extra_files or {}).items()):
            copy_or_create(role, source, Path(source).name)

        checksum_map = {item["path"]: item["sha256"] for item in files}

        resolved_pred_contract = prediction_contract or {
            "prediction_task": "binary_failure_within_horizon",
            "prediction_horizon_hours": 24,
            "probability_output": "positive_class_probability",
            "positive_class": 1,
        }

        resolved_runtime = model_runtime or {
            "format": "joblib",
            "framework": training_config.get("framework", "scikit-learn"),
            "framework_api": "sklearn",
            "entry_role": "model",
            "output_type": "positive_class_probability",
        }

        manifest = {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "dataset_schema_version": dataset_schema_version,
            "feature_schema_version": feature_schema_version,
            "label_schema_version": resolved_label_schema.get("label_schema_version", label_schema_version or "pdm-label-v1"),
            "history_requirement_version": resolved_history.get("history_requirement_version", history_requirement_version or "pdm-history-v1"),
            "metrics_schema_version": metrics_schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prediction_contract": resolved_pred_contract,
            "model_runtime": resolved_runtime,
            "training_config": training_config,
            "metrics": resolved_metrics,
            "checksum": {"algorithm": "sha256", "files": checksum_map},
            "provenance": provenance,
            "compatibility": compatibility,
            "artifact_files": files,
        }
        validate_manifest(manifest)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, destination)
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def train_and_publish_model(
    *,
    csv_path: str | Path,
    artifact_uri: str | Path,
    model_id: str = "ai4i-failure-risk",
    dataset_version: str | None = None,
    feature_schema_version: str = "ai4i-canonical-features-v1",
    minimum_recall: float = 0.80,
    false_negative_cost: float = 10.0,
    false_positive_cost: float = 1.0,
) -> Path:
    """Train/evaluate and publish the result as one versioned Model Artifact."""
    from .training_impl import ALL_FEATURES, train_and_evaluate

    with tempfile.TemporaryDirectory(prefix="ontology-dashboard-model-training-") as work:
        work_dir = Path(work)
        metadata = train_and_evaluate(
            csv_path,
            work_dir,
            minimum_recall=minimum_recall,
            false_negative_cost=false_negative_cost,
            false_positive_cost=false_positive_cost,
        )
        source_sha = str(metadata["dataset"]["sha256"])
        resolved_dataset_version = dataset_version or f"ai4i-sha256-{source_sha[:12]}"
        model_version = f"{metadata['model_version']}-{source_sha[:12]}"
        return publish_model_artifact(
            artifact_uri=artifact_uri,
            model_id=model_id,
            model_version=model_version,
            dataset_version=resolved_dataset_version,
            feature_schema_version=feature_schema_version,
            model_file=work_dir / "model.joblib",
            feature_schema={
                "schema_version": feature_schema_version,
                "features": ALL_FEATURES,
                "target": "machine_failure",
                "prediction_task": "binary_failure_within_horizon",
            },
            training_config={
                "random_seed": metadata["random_seed"],
                "selected_model": metadata["selected_model"],
                "split": metadata["split"],
                "threshold_choice": metadata["threshold_choice"],
                "minimum_recall": minimum_recall,
                "false_negative_cost": false_negative_cost,
                "false_positive_cost": false_positive_cost,
            },
            metrics={
                "candidate_validation_metrics": metadata["candidate_validation_metrics"],
                "test_metrics": metadata["test_metrics"],
                "dummy_test_metrics": metadata["dummy_test_metrics"],
            },
            provenance={
                "source_repository": "Biz-CollabCraft/gen_data or compatible source contract",
                "source_file_sha256": source_sha,
                "producer": "ontology_dashboard/systems/generator",
                "truth_usage": "training/evaluation label only",
            },
            compatibility={
                "runtime": "ontology_dashboard.systems.backend.diagnosis",
                "prediction_task": "binary_failure_within_horizon",
                "python": ">=3.11",
            },
            extra_files={"threshold_curve": work_dir / "threshold_curve.json"},
        )


class ModelRegistry:
    """PR #10 public facade for immutable Model Artifact publication."""

    def __init__(self, artifact_uri: str | Path) -> None:
        self.artifact_uri = artifact_uri

    def publish(self, **kwargs: Any) -> Path:
        return publish_model_artifact(artifact_uri=self.artifact_uri, **kwargs)


def _get_default_store_dir(store_dir: str | Path | None = None) -> Path:
    if store_dir:
        return Path(store_dir).resolve()
    from systems.generator.generator_config import PATHS
    return PATHS.models_store


def get_next_run_version(store_dir: str | Path | None = None) -> int:
    """Scan store_dir for existing runs and return the next integer run version."""
    root = _get_default_store_dir(store_dir)
    registry_file = root / "registry.json"
    if registry_file.exists():
        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                latest = data.get("latest_run_version", 0)
                if isinstance(latest, int) and latest > 0:
                    return latest + 1
        except Exception:
            pass

    runs_dir = root / "runs"
    if runs_dir.exists():
        max_ver = 0
        for entry in runs_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("v"):
                try:
                    ver = int(entry.name[1:])
                    max_ver = max(max_ver, ver)
                except ValueError:
                    pass
        return max_ver + 1
    return 1


def save_run_result(
    run_version: int,
    results: dict[str, Any],
    run_meta: dict[str, Any],
    store_dir: str | Path | None = None,
) -> None:
    """Persist run execution records into the secondary run registry index."""
    root = _get_default_store_dir(store_dir)
    root.mkdir(parents=True, exist_ok=True)
    registry_file = root / "registry.json"

    registry_data: dict[str, Any] = {"latest_run_version": run_version, "runs": {}}
    if registry_file.exists():
        try:
            with open(registry_file, "r", encoding="utf-8") as f:
                registry_data = json.load(f)
        except Exception:
            pass

    registry_data["latest_run_version"] = run_version
    registry_data.setdefault("runs", {})[f"v{run_version}"] = {
        "run_version": run_version,
        "trained_at": run_meta.get("trained_at", datetime.now(timezone.utc).isoformat()),
        "models": results,
        "meta": run_meta,
    }

    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump(registry_data, f, ensure_ascii=False, indent=2)


def load_registry(store_dir: str | Path | None = None) -> dict[str, Any]:
    """Load the secondary run registry index file."""
    root = _get_default_store_dir(store_dir)
    registry_file = root / "registry.json"
    if registry_file.exists():
        with open(registry_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"latest_run_version": 0, "runs": {}}


def get_latest_model_path(model_name: str, store_dir: str | Path | None = None) -> Path | None:
    """Return the filesystem path to the latest model for a given model algorithm."""
    root = _get_default_store_dir(store_dir)
    model_dir = root / model_name
    if not model_dir.exists():
        return None

    candidates: list[tuple[int, Path]] = []
    for p in model_dir.glob("model_v*.joblib"):
        stem = p.stem.replace("model_v", "")
        try:
            candidates.append((int(stem), p))
        except ValueError:
            pass

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None


def has_any_trained_model(store_dir: str | Path | None = None) -> bool:
    """Check if any model has been trained and recorded in the run registry."""
    root = _get_default_store_dir(store_dir)
    for model_name in ("lightgbm", "xgboost", "random_forest"):
        if get_latest_model_path(model_name, root) is not None:
            return True
    return False

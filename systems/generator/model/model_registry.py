"""Immutable versioned Model Artifact publication for the generator system.

The physical ``model_store/`` directory from the PR #10 scaffold is only a
local adapter example. The Generator/Backend boundary is the versioned manifest
and injected artifact URI, not a sibling filesystem path.
"""

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
    extra_files: dict[str, str | Path] | None = None,
) -> Path:
    """Publish an immutable local Model Artifact atomically.

    ``artifact_uri`` is the provider root, not a generator-relative sibling path.
    The final path is ``<root>/<model_id>/<model_version>``. Existing immutable
    versions are never overwritten.
    """

    root = _local_root(artifact_uri)
    destination = root / model_id / model_version
    if destination.exists():
        raise FileExistsError(f"immutable Model Artifact already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{model_version}-", dir=destination.parent))
    try:
        files: list[dict[str, str]] = []

        def copy_file(role: str, source: str | Path, target_name: str) -> None:
            source_path = Path(source)
            target = staging / target_name
            shutil.copy2(source_path, target)
            files.append({"role": role, "path": target_name, "sha256": _sha256(target)})

        copy_file("model", model_file, "model.joblib")
        (staging / "feature_schema.json").write_text(
            json.dumps(feature_schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files.append(
            {
                "role": "feature_schema",
                "path": "feature_schema.json",
                "sha256": _sha256(staging / "feature_schema.json"),
            }
        )
        (staging / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        files.append(
            {"role": "metrics", "path": "metrics.json", "sha256": _sha256(staging / "metrics.json")}
        )
        for role, source in sorted((extra_files or {}).items()):
            copy_file(role, source, Path(source).name)

        checksum_map = {item["path"]: item["sha256"] for item in files}
        manifest = {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
            "model_id": model_id,
            "model_version": model_version,
            "dataset_version": dataset_version,
            "feature_schema_version": feature_schema_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "training_config": training_config,
            "metrics": metrics,
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

    from .model_training import ALL_FEATURES, train_and_evaluate

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

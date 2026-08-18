"""Standalone Generator batch entrypoint.

This module deliberately exposes a batch CLI rather than a permanently busy API
server. It exercises the PR #21 extraction/mapping/feature/label path and keeps
the final Generator/Backend boundary at the immutable Model Artifact publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from systems.generator.extraction.extraction_profiler import load_family_registry
from systems.generator.extraction.extraction_service import get_last_plans, load_all_sources
from systems.generator.feature.feature_builder import build_features, save_features_npy
from systems.generator.feature.feature_catalog import load_catalog
from systems.generator.feature.feature_label_service import build_labels
from systems.generator.generator_config import PATHS
from systems.generator.model.compressor_training import (
    FEATURE_SCHEMA_VERSION,
    TRAINING_VERSION,
    train_compressor_model,
)
from systems.generator.model.model_registry import publish_model_artifact
from systems.generator.ontology_mapping.mapping_agent import map_all_sources
from systems.generator.ontology_mapping.mapping_cache import get_mapping_store

logger = logging.getLogger(__name__)

def _metadata_for(source_key: str, registry: dict[str, Any]) -> dict[str, Any]:
    filename = next((name for name in registry if Path(name).stem == source_key), None)
    return registry.get(filename, {}) if filename else {}


def _effective_plan(
    source_key: str,
    plans: dict[str, Any],
    metadata: dict[str, Any],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    """Fill LLM-fallback plan gaps from Stage-0 metadata/canonical columns."""

    plan = dict(plans.get(source_key) or {})
    id_candidates = [metadata.get("id_col"), "asset_id", "machineID", "equipment_id", "device_id"]
    time_candidates = [metadata.get("time_col"), "observed_at", "datetime", "timestamp", "time"]
    if not plan.get("id_column") or plan.get("id_column") not in frame.columns:
        plan["id_column"] = next((column for column in id_candidates if column and column in frame.columns), None)
    if not plan.get("time_column") or plan.get("time_column") not in frame.columns:
        plan["time_column"] = next((column for column in time_candidates if column and column in frame.columns), None)
    return plan


def _select_pipeline_pair(sources: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    registry = load_family_registry()
    telemetry = [key for key in sources if _metadata_for(key, registry).get("role") == "telemetry_sensor"]
    failures = [
        key
        for key in sources
        if _metadata_for(key, registry).get("role") in {"failure_event", "evaluation_truth"}
    ]
    for telemetry_key in telemetry:
        telemetry_meta = _metadata_for(telemetry_key, registry)
        telemetry_ids = set(telemetry_meta.get("id_columns") or [])
        for failure_key in failures:
            failure_meta = _metadata_for(failure_key, registry)
            if telemetry_ids.intersection(failure_meta.get("id_columns") or []):
                return telemetry_key, failure_key, telemetry_meta, failure_meta
    raise ValueError(
        "no telemetry/failure pair with a shared asset identifier was found; "
        "stage-0 source_family_registry.json contains the authoritative roles"
    )


def run_feature_label_pipeline(*, force_reanalyze: bool = False) -> dict[str, Any]:
    sources = load_all_sources(str(PATHS.data_dir), force_reanalyze=force_reanalyze)
    store = map_all_sources(sources, get_mapping_store())
    telemetry_key, failure_key, telemetry_meta, failure_meta = _select_pipeline_pair(sources)
    plans = get_last_plans()
    plan = _effective_plan(telemetry_key, plans, telemetry_meta, sources[telemetry_key])
    features = build_features(sources[telemetry_key], store, load_catalog(), plan=plan)
    labeled = build_labels(
        features,
        sources[failure_key],
        failure_meta=failure_meta,
        plan=plan,
    )
    output_dir = PATHS.data_preprocessed / "features"
    save_features_npy(features, str(output_dir), telemetry_key, plan=plan)
    labeled_path = PATHS.data_preprocessed / f"{telemetry_key}_labeled.csv"
    labeled.to_csv(labeled_path, index=False)
    positive = int(labeled["label"].sum()) if "label" in labeled else 0
    return {
        "source_files": len(sources),
        "telemetry_source": telemetry_key,
        "failure_source": failure_key,
        "input_rows": int(len(sources[telemetry_key])),
        "feature_rows": int(len(features)),
        "feature_count": max(0, int(len(features.columns) - 2)),
        "labeled_rows": int(len(labeled)),
        "positive_labels": positive,
        "negative_labels": int(len(labeled) - positive),
        "asset_count": int(features[plan["id_column"]].nunique()) if plan.get("id_column") in features else 1,
        "labeled_output": str(labeled_path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _training_n_jobs() -> int:
    value = int(os.getenv("GENERATOR_TRAINING_N_JOBS", "2"))
    if value == 0 or value < -1:
        raise ValueError("GENERATOR_TRAINING_N_JOBS must be -1 or a positive integer")
    return value


def publish_training_artifact(*, force_reanalyze: bool = False) -> Path:
    """Train a runtime-compatible compressor model and publish it immutably.

    The source remains the gen_data file contract. Training labels use the same
    failure-horizon semantics as the Generator feature/label stage, while the
    published feature schema is intentionally limited to fields the Backend
    runtime observation contract can provide.
    """

    artifact_uri = os.getenv("MODEL_ARTIFACT_URI", "").strip()
    if not artifact_uri:
        raise RuntimeError("MODEL_ARTIFACT_URI is required for Generator publication")

    sources = load_all_sources(str(PATHS.data_dir), force_reanalyze=force_reanalyze)
    registry = load_family_registry()
    plans = get_last_plans()
    candidate = next(
        (
            key
            for key, frame in sources.items()
            if all(
                feature in frame.columns
                for feature in (
                    "observed_at",
                    "asset_id",
                    "site_id",
                    "operating_state",
                    "voltage_raw",
                    "rotation_raw",
                    "pressure_raw",
                    "vibration_raw",
                    "relative_vibration_z",
                )
            )
            and _metadata_for(key, registry).get("role") == "telemetry_sensor"
        ),
        None,
    )
    if candidate is None:
        raise ValueError("no compressor telemetry source matches the Backend runtime feature contract")
    telemetry_meta = _metadata_for(candidate, registry)
    telemetry_ids = set(telemetry_meta.get("id_columns") or [])
    failure_key = next(
        (
            key
            for key in sources
            if _metadata_for(key, registry).get("role") in {"failure_event", "evaluation_truth"}
            and telemetry_ids.intersection(_metadata_for(key, registry).get("id_columns") or [])
            and "compressor" in key.lower()
        ),
        None,
    )
    if failure_key is None:
        raise ValueError("no compressor failure truth source matches compressor telemetry")

    training = train_compressor_model(
        sources[candidate],
        sources[failure_key],
        n_jobs=_training_n_jobs(),
        horizon_hours=24,
        minimum_recall=0.30,
    )

    source_file = PATHS.data_dir / f"{candidate}.csv"
    source_sha = _sha256(source_file)
    dataset_version = f"gen-data-v3.1-sha256-{source_sha[:12]}"
    algorithm_slug = training.selected_model.replace("_", "-")
    model_version = f"compressor-{algorithm_slug}-v3-{source_sha[:12]}"
    destination = Path(str(artifact_uri).removeprefix("file://")).expanduser().resolve() / "compressor-failure-risk" / model_version
    if destination.exists():
        return destination

    with tempfile.TemporaryDirectory(prefix="compressor-model-") as work:
        model_file = Path(work) / "model.joblib"
        import joblib

        joblib.dump(training.model, model_file)
        threshold_curve_file = Path(work) / "threshold_curve.json"
        threshold_curve_file.write_text(
            json.dumps(training.threshold_curve, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        label_schema_file = Path(work) / "label_schema.json"
        label_schema_file.write_text(
            json.dumps(
                {
                    "schema_version": "compressor-failure-within-horizon-v1",
                    "target": "failure_within_24h",
                    "horizon_hours": 24,
                    "positive_semantics": "next failure strictly after observation and within 24 hours",
                    "post_failure_rows_positive": False,
                    "right_censoring": "exclude final 24h of each asset observation horizon",
                    "maintenance_rows_excluded": True,
                    "truth_usage": "label creation and offline evaluation only",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        history_requirement_file = Path(work) / "history_requirement.json"
        runtime_context = dict(
            (training.feature_schema.get("feature_engineering") or {}).get("runtime_context") or {}
        )
        history_requirement_file.write_text(
            json.dumps(
                {
                    "schema_version": "compressor-history-requirement-v1",
                    "observation_family": "compressor",
                    "current_observation_required": True,
                    "prior_observations_required": int(runtime_context.get("recent_history_rows_required", 35)),
                    "expected_cadence_minutes": float(
                        (training.feature_schema.get("feature_engineering") or {}).get(
                            "expected_cadence_minutes", 10.0
                        )
                    ),
                    "ordering": runtime_context.get(
                        "history_order", "strictly_ascending_before_current_observation"
                    ),
                    "new_asset_policy": runtime_context.get(
                        "new_asset_policy", "calibrate_baseline_before_inference"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return publish_model_artifact(
            artifact_uri=artifact_uri,
            model_id="compressor-failure-risk",
            model_version=model_version,
            dataset_version=dataset_version,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            model_file=model_file,
            feature_schema=training.feature_schema,
            training_config=training.training_config,
            metrics=training.metrics,
            provenance={
                "source_repository": "Biz-CollabCraft/gen_data",
                "source_contract": "Canonical V3.1 file/artifact",
                "source_file": f"{candidate}.csv",
                "source_file_sha256": source_sha,
                "failure_truth_file": f"{failure_key}.csv",
                "producer": "ontology_dashboard/systems/generator",
                "training_implementation": TRAINING_VERSION,
            },
            compatibility={
                "runtime": "ontology_dashboard.systems.backend.diagnosis",
                "prediction_task": "binary_failure_within_horizon",
                "observation_family": "compressor",
                "python": ">=3.11",
            },
            extra_files={
                "threshold_curve": threshold_curve_file,
                "label_schema": label_schema_file,
                "history_requirement": history_requirement_file,
            },
        )


def update_current_alias(artifact_path: Path) -> Path:
    alias = artifact_path.parent / "current"
    temporary = artifact_path.parent / ".current.tmp"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(artifact_path.name)
    os.replace(temporary, alias)
    return alias


def assert_promotion_sanity(artifact_path: Path) -> None:
    """Refuse to promote an artifact that cannot detect known positives.

    Publication remains immutable even when a candidate misses the gate, which
    preserves debugging evidence without moving the Backend's ``current`` alias.
    """

    metrics = json.loads((artifact_path / "metrics.json").read_text(encoding="utf-8"))
    feature_table = metrics.get("feature_table") or {}
    sanity = metrics.get("regression_sanity") or {}
    deployment = metrics.get("deployment_realism_test") or {}
    prevalence = float(feature_table.get("prevalence") or 0.0)
    average_precision = float(sanity.get("average_precision") or 0.0)
    if average_precision <= prevalence:
        raise RuntimeError(
            "Model Artifact promotion blocked: regression sanity average precision "
            f"{average_precision:.6f} is not above prevalence {prevalence:.6f}"
        )
    if average_precision < 0.15:
        raise RuntimeError(
            "Model Artifact promotion blocked: regression sanity average precision "
            f"{average_precision:.6f} is below the project sanity floor 0.150000"
        )
    if float(sanity.get("recall") or 0.0) <= 0.0:
        raise RuntimeError("Model Artifact promotion blocked: regression sanity recall is zero")
    if float(deployment.get("recall") or 0.0) <= 0.0:
        raise RuntimeError("Model Artifact promotion blocked: deployment realism recall is zero")
    deployment_precision = float(deployment.get("precision") or 0.0)
    deployment_prevalence = float(deployment.get("prevalence") or 0.0)
    if deployment_precision <= deployment_prevalence:
        raise RuntimeError(
            "Model Artifact promotion blocked: deployment alert precision does not exceed base prevalence "
            f"({deployment_precision:.6f} <= {deployment_prevalence:.6f})"
        )


def llm_smoke() -> dict[str, Any]:
    from systems.generator.generator_llm_client import ExtractionStructureResponse, call_llm, validate_or_transform_pydantic

    raw = call_llm(
        'Return only JSON: {"structure_type":"tabular_column_as_attribute","reason":"runtime smoke"}',
        system="Return the requested JSON only.",
    )
    parsed = validate_or_transform_pydantic(raw, ExtractionStructureResponse)
    if parsed is None:
        raise RuntimeError("OpenAI response failed Pydantic parsing")
    return {"status": "ok", "structure_type": parsed.structure_type}


def main() -> int:
    parser = argparse.ArgumentParser(description="ontology_dashboard standalone Generator")
    parser.add_argument("command", choices=("run", "feature-label", "train-publish", "llm-smoke"), nargs="?", default="run")
    parser.add_argument("--force-reanalyze", action="store_true")
    parser.add_argument(
        "--promote-current",
        action="store_true",
        help="after metric sanity gates pass, atomically move the current alias to the published artifact",
    )
    args = parser.parse_args()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    result: dict[str, Any] = {}
    if args.command in {"run", "feature-label"}:
        result["pipeline"] = run_feature_label_pipeline(force_reanalyze=args.force_reanalyze)
    if args.command in {"run", "train-publish"}:
        artifact = publish_training_artifact(force_reanalyze=args.force_reanalyze)
        manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
        result["artifact"] = {
            "path": str(artifact),
            "model_version": manifest["model_version"],
            "dataset_version": manifest["dataset_version"],
            "artifact_files": len(manifest["artifact_files"]),
            "promoted_current": False,
        }
        if args.promote_current:
            assert_promotion_sanity(artifact)
            current = update_current_alias(artifact)
            result["artifact"]["current_uri"] = str(current)
            result["artifact"]["promoted_current"] = True
    if args.command == "llm-smoke":
        result["llm"] = llm_smoke()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

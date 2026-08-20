"""Continuously ingest the Mac mini ``gen_data`` daemon sensor stream.

``gen_data`` owns source/simulation generation.  This module is deliberately
owned by ``ontology_dashboard`` because it converts those source observations
into the product database and invokes the currently promoted Model Artifacts.
The immutable Canonical V3.1 Dataset Version remains untouched; live source is
published as a separate, monotonically newer Dataset Version.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from app.common.runtime_settings import project_root
from app.diagnosis.evidence import build_product_result_artifact
from app.diagnosis.predictor import configured_predictor
from app.infra.db.predictive_maintenance_ontology_projection import (
    PredictiveMaintenanceOntologyMaterializer,
)
from app.infra.db.settings import database_location


LOGGER = logging.getLogger(__name__)
ORGANIZATION_ID = "org-ontology-demo"
PROJECT_ID = "manufacturing-demo-project"
WORKSPACE_ID = "manufacturing-demo"
SOURCE_VERSION = "canonical-ai4i-physics-v3.1"
RUNTIME_SELECTION_STRATEGY = "latest_observation_per_asset_v1"
RUNTIME_MATERIALIZATION_PROFILE = "cnc_and_compressor_artifact_current_state_v3"
OUTPUT_ROLES = {
    "prediction_snapshot",
    "prediction_factor",
    "prediction_timeline",
    "result_artifact",
}
LIVE_SOURCE_VERSION = "gen-data-wall-clock-live-v2"
LEGACY_ACCELERATED_SOURCE_VERSION = "gen-data-live-v1"
LIVE_MATERIALIZATION_PROFILE = "gen_data_wall_clock_live_current_state_v2"
OVERLAY_SOURCE_VERSION = "maintenance-replay-overlay-v1"
DEFAULT_STREAM_ROOT = Path("/gen-data-runtime")
EXPECTED_ASSET_COUNT = 100
MAX_LIVE_CLOCK_SKEW = timedelta(minutes=2)
LIVE_STATIC_LINEAGE_ROLES = ("asset_master", "asset_relation")
LIVE_SENSOR_ROLES = ("cnc_sensor_observation", "compressor_sensor_observation")


def database_target() -> str:
    return database_location(project_root())


def _postgres_modules():
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover - deployment packaging guard
        raise RuntimeError("live predictive-maintenance ingestion requires backend[postgres]") from exc
    return psycopg, dict_row, Jsonb


def _normalize_database_url(value: str) -> str:
    normalized = value.replace("postgresql+psycopg://", "postgresql://", 1)
    if not normalized.startswith("postgresql://"):
        raise ValueError("live predictive-maintenance ingestion requires PostgreSQL")
    return normalized


def _set_scope(connection: Any) -> None:
    connection.execute("SELECT set_config('app.organization_id',%s,true)", (ORGANIZATION_ID,))
    connection.execute("SELECT set_config('app.project_id',%s,true)", (PROJECT_ID,))


def _runtime_candidates(
    connection: Any,
    dataset_version_id: str,
    *,
    excluded_asset_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Select the latest observation for every canonical equipment asset."""

    excluded = sorted(excluded_asset_ids or set())
    return list(
        connection.execute(
            """
            WITH cnc_ranked AS (
                SELECT o.*,
                       ROW_NUMBER() OVER (PARTITION BY o.asset_id ORDER BY o.observed_at DESC) AS row_number
                FROM pm_cnc_observations o
                WHERE o.dataset_version_id=%s
                  AND NOT (o.asset_id = ANY(%s))
            ), latest_cnc AS (
                SELECT o.asset_id,o.observed_at,o.source_sha256,'cnc'::text AS asset_type,
                       jsonb_build_object(
                           'product_type',o.product_type,
                           'air_temperature_k',o.air_temperature_k,
                           'process_temperature_k',o.process_temperature_k,
                           'rotational_speed_rpm',o.rotational_speed_rpm,
                           'torque_nm',o.torque_nm,
                           'tool_wear_min',o.tool_wear_min
                       ) AS observation,
                       COALESCE(
                           (
                               SELECT jsonb_agg(
                                   jsonb_build_object(
                                       'timestamp',h.observed_at,
                                       'product_type',h.product_type,
                                       'air_temperature_k',h.air_temperature_k,
                                       'process_temperature_k',h.process_temperature_k,
                                       'rotational_speed_rpm',h.rotational_speed_rpm,
                                       'torque_nm',h.torque_nm,
                                       'tool_wear_min',h.tool_wear_min
                                   ) ORDER BY h.observed_at ASC
                               )
                               FROM cnc_ranked h
                               WHERE h.asset_id=o.asset_id AND h.observed_at < o.observed_at
                           ),
                           '[]'::jsonb
                       ) AS history
                FROM cnc_ranked o
                WHERE o.row_number=1
            ), compressor_ranked AS (
                SELECT o.*,
                       ROW_NUMBER() OVER (PARTITION BY o.asset_id ORDER BY o.observed_at DESC) AS row_number
                FROM pm_compressor_observations o
                WHERE o.dataset_version_id=%s
                  AND NOT (o.asset_id = ANY(%s))
            ), latest_compressor AS (
                SELECT o.asset_id,o.observed_at,o.source_sha256,'compressor'::text AS asset_type,
                       jsonb_build_object(
                           'voltage_raw',o.voltage_raw,
                           'rotation_raw',o.rotation_raw,
                           'pressure_raw',o.pressure_raw,
                           'vibration_raw',o.vibration_raw,
                           'relative_vibration_z',o.relative_vibration_z,
                           'relative_vibration_zone',o.relative_vibration_zone
                       ) AS observation,
                       COALESCE(
                           (
                               SELECT jsonb_agg(
                                   jsonb_build_object(
                                       'timestamp',h.observed_at,
                                       'voltage_raw',h.voltage_raw,
                                       'rotation_raw',h.rotation_raw,
                                       'pressure_raw',h.pressure_raw,
                                       'vibration_raw',h.vibration_raw,
                                       'relative_vibration_z',h.relative_vibration_z,
                                       'relative_vibration_zone',h.relative_vibration_zone
                                   ) ORDER BY h.observed_at ASC
                               )
                               FROM compressor_ranked h
                               WHERE h.asset_id=o.asset_id AND h.observed_at < o.observed_at
                           ),
                           '[]'::jsonb
                       ) AS history
                FROM compressor_ranked o
                WHERE o.row_number=1
            )
            SELECT * FROM latest_cnc
            UNION ALL
            SELECT * FROM latest_compressor
            ORDER BY asset_id
            """,
            (dataset_version_id, excluded, dataset_version_id, excluded),
        ).fetchall()
    )


def _artifact_checksum(artifact: dict[str, Any]) -> str:
    rendered = json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _compressor_runtime_history(
    connection: Any,
    dataset_version_id: str,
    asset_id: str,
    observed_at: Any,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT observed_at,voltage_raw,rotation_raw,pressure_raw,vibration_raw,
               relative_vibration_z,relative_vibration_zone
        FROM pm_compressor_observations
        WHERE dataset_version_id=%s AND asset_id=%s AND observed_at < %s
        ORDER BY observed_at DESC
        LIMIT 35
        """,
        (dataset_version_id, asset_id, observed_at),
    ).fetchall()
    ordered = list(reversed(rows))
    return [
        {
            "timestamp": item["observed_at"].isoformat(),
            "voltage_raw": float(item["voltage_raw"]),
            "rotation_raw": float(item["rotation_raw"]),
            "pressure_raw": float(item["pressure_raw"]),
            "vibration_raw": float(item["vibration_raw"]),
            "relative_vibration_z": float(item["relative_vibration_z"]),
            "relative_vibration_zone": str(item["relative_vibration_zone"]),
        }
        for item in ordered
    ]


def _cnc_runtime_history(
    connection: Any,
    dataset_version_id: str,
    asset_id: str,
    observed_at: Any,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT observed_at,product_type,air_temperature_k,process_temperature_k,
               rotational_speed_rpm,torque_nm,tool_wear_min
        FROM pm_cnc_observations
        WHERE dataset_version_id=%s AND asset_id=%s AND observed_at < %s
        ORDER BY observed_at DESC
        LIMIT 35
        """,
        (dataset_version_id, asset_id, observed_at),
    ).fetchall()
    ordered = list(reversed(rows))
    return [
        {
            "timestamp": item["observed_at"].isoformat(),
            "product_type": item["product_type"],
            "air_temperature_k": float(item["air_temperature_k"]),
            "process_temperature_k": float(item["process_temperature_k"]),
            "rotational_speed_rpm": float(item["rotational_speed_rpm"]),
            "torque_nm": float(item["torque_nm"]),
            "tool_wear_min": float(item["tool_wear_min"]),
        }
        for item in ordered
    ]


def _runtime_fixture(
    row: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
    source_version: str = SOURCE_VERSION,
) -> dict[str, Any]:
    observed_at = row["observed_at"].isoformat()
    asset_id = str(row["asset_id"])
    asset_type = str(row["asset_type"])
    source = dict(row["observation"])
    if asset_type == "compressor":
        observation = {
            "timestamp": observed_at,
            "voltage_raw": float(source["voltage_raw"]),
            "rotation_raw": float(source["rotation_raw"]),
            "pressure_raw": float(source["pressure_raw"]),
            "vibration_raw": float(source["vibration_raw"]),
            "relative_vibration_z": float(source["relative_vibration_z"]),
            "relative_vibration_zone": str(source["relative_vibration_zone"]),
        }
    else:
        observation = {
            "timestamp": observed_at,
            "product_type": source.get("product_type"),
            "air_temperature_k": float(source["air_temperature_k"]),
            "process_temperature_k": float(source["process_temperature_k"]),
            "rotational_speed_rpm": float(source["rotational_speed_rpm"]),
            "torque_nm": float(source["torque_nm"]),
            "tool_wear_min": float(source["tool_wear_min"]),
        }
    return {
        "schema_version": "1.0",
        "event_id": f"runtime-{asset_id}-{observed_at}",
        "scenario_id": f"canonical-v3.1-runtime:{asset_id}",
        "dataset_version": source_version,
        "asset_type": asset_type,
        "equipment": {
            "equipment_id": asset_id,
            "criticality": "medium",
        },
        "observation": observation,
        "history": list(history if history is not None else row.get("history") or []),
    }


def _materialize_runtime_results(
    database_url: str,
    dataset_version_id: str,
    *,
    source_version: str = SOURCE_VERSION,
    materialization_profile: str = RUNTIME_MATERIALIZATION_PROFILE,
    excluded_asset_ids: set[str] | None = None,
) -> dict[str, Any]:
    psycopg, dict_row, Jsonb = _postgres_modules()
    cnc_predictor = configured_predictor("cnc")
    compressor_predictor = configured_predictor("compressor")
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            _set_scope(connection)
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"demo-runtime:{PROJECT_ID}:{dataset_version_id}",),
            )
            roles = {
                str(row["role"])
                for row in connection.execute(
                    "SELECT role FROM dataset_files WHERE dataset_version_id=%s",
                    (dataset_version_id,),
                ).fetchall()
            }
            unexpected = sorted(roles & OUTPUT_ROLES)
            if unexpected:
                raise RuntimeError(
                    "refusing to overwrite fixture-backed predictive outputs: "
                    + ", ".join(unexpected)
                )
            candidates = _runtime_candidates(
                connection,
                dataset_version_id,
                excluded_asset_ids=excluded_asset_ids,
            )
            if not candidates:
                raise RuntimeError("canonical source ingestion produced no equipment observations")

            existing = connection.execute(
                """
                SELECT COUNT(*) AS count,
                       COUNT(*) FILTER (
                           WHERE provenance->>'source_type'='product_runtime_inference'
                       ) AS runtime_count,
                       COUNT(*) FILTER (
                           WHERE provenance->>'selection_strategy'=%s
                       ) AS current_selection_count,
                       COUNT(*) FILTER (
                           WHERE provenance->>'materialization_profile'=%s
                       ) AS current_profile_count,
                       MAX(observed_at) AS latest_observed_at
                FROM pm_result_artifacts
                WHERE dataset_version_id=%s
                """,
                (
                    RUNTIME_SELECTION_STRATEGY,
                    materialization_profile,
                    dataset_version_id,
                ),
            ).fetchone()
            latest_candidate_observed_at = max(row["observed_at"] for row in candidates)
            if (
                int(existing["count"] or 0) == len(candidates)
                and int(existing["runtime_count"] or 0) == len(candidates)
                and int(existing["current_selection_count"] or 0) == len(candidates)
                and int(existing["current_profile_count"] or 0) == len(candidates)
                and existing["latest_observed_at"] == latest_candidate_observed_at
            ):
                return {
                    "model_versions": sorted({cnc_predictor.model_version, compressor_predictor.model_version}),
                    "result_artifact_count": len(candidates),
                    "selection_strategy": RUNTIME_SELECTION_STRATEGY,
                    "materialization_profile": materialization_profile,
                    "reused": True,
                }

            prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []
            held_assets: list[dict[str, Any]] = []
            for row in candidates:
                asset_type = str(row["asset_type"])
                predictor = compressor_predictor if asset_type == "compressor" else cnc_predictor
                history = (
                    _compressor_runtime_history(
                        connection,
                        dataset_version_id,
                        str(row["asset_id"]),
                        row["observed_at"],
                    )
                    if asset_type == "compressor"
                    else _cnc_runtime_history(
                        connection,
                        dataset_version_id,
                        str(row["asset_id"]),
                        row["observed_at"],
                    )
                )
                artifact = build_product_result_artifact(
                    _runtime_fixture(row, history=history, source_version=source_version),
                    predictor=predictor,
                )
                if artifact.get("failure_probability") is None:
                    held_assets.append(
                        {
                            "asset_id": str(row["asset_id"]),
                            "asset_type": asset_type,
                            "observed_at": row["observed_at"].isoformat(),
                            "quality_warnings": list(artifact.get("data_quality_warnings") or []),
                        }
                    )
                    continue
                prepared.append((row, artifact))

            ready_asset_ids = sorted({str(row["asset_id"]) for row, _artifact in prepared})
            if ready_asset_ids:
                previous = connection.execute(
                    """
                    SELECT prediction_id,prediction_result_id
                    FROM pm_prediction_snapshots
                    WHERE dataset_version_id=%s AND asset_id = ANY(%s)
                    """,
                    (dataset_version_id, ready_asset_ids),
                ).fetchall()
                previous_prediction_ids = [str(item["prediction_id"]) for item in previous]
                previous_result_ids = [str(item["prediction_result_id"]) for item in previous]
                connection.execute(
                    "DELETE FROM pm_result_artifacts WHERE dataset_version_id=%s AND asset_id = ANY(%s)",
                    (dataset_version_id, ready_asset_ids),
                )
                if previous_prediction_ids:
                    connection.execute(
                        "DELETE FROM pm_prediction_factors WHERE dataset_version_id=%s AND prediction_id = ANY(%s)",
                        (dataset_version_id, previous_prediction_ids),
                    )
                    connection.execute(
                        "DELETE FROM pm_prediction_timeline WHERE dataset_version_id=%s AND prediction_id = ANY(%s)",
                        (dataset_version_id, previous_prediction_ids),
                    )
                connection.execute(
                    "DELETE FROM pm_prediction_snapshots WHERE dataset_version_id=%s AND asset_id = ANY(%s)",
                    (dataset_version_id, ready_asset_ids),
                )
                if previous_result_ids:
                    connection.execute(
                        "DELETE FROM prediction_results WHERE prediction_id = ANY(%s)",
                        (previous_result_ids,),
                    )

            for row, artifact in prepared:
                asset_type = str(row["asset_type"])
                probability = float(artifact["failure_probability"])
                diagnostic_type = str(artifact["predicted_failure_type"])
                if asset_type == "compressor" and diagnostic_type in {"failure_risk", "none"}:
                    binary_type = (
                        "failure_risk" if diagnostic_type == "failure_risk" else "no_significant_risk"
                    )
                else:
                    binary_type = "failure_risk" if probability >= 0.5 else "no_significant_risk"
                provenance = dict(artifact["provenance"])
                provenance.update(
                    {
                        "dataset_version_id": dataset_version_id,
                        "source_version": source_version,
                        "source_observation_sha256": str(row["source_sha256"]),
                        "diagnostic_failure_type": diagnostic_type,
                        "selection_strategy": RUNTIME_SELECTION_STRATEGY,
                        "materialization_profile": materialization_profile,
                    }
                )
                prediction_id = str(provenance["prediction_id"])
                prediction_result_id = f"pmrt-{uuid.uuid5(uuid.NAMESPACE_URL, f'{dataset_version_id}:{prediction_id}')}"
                artifact_checksum = _artifact_checksum({**artifact, "provenance": provenance})
                confidence = float(artifact["confidence"])
                status = str(artifact["status_grade"])
                feature_scope = [str(item["feature"]) for item in artifact["top_factors"]]
                result_payload = {
                    **artifact,
                    "predicted_failure_type": binary_type,
                    "provenance": provenance,
                    "dataset_version_id": dataset_version_id,
                    "source_type": "product_runtime_inference",
                }

                connection.execute(
                    """
                    INSERT INTO prediction_results(
                        prediction_id,organization_id,project_id,workspace_id,
                        subject_object_type,subject_object_id,prediction_status,
                        model_version,dataset_version,payload_json,created_at,received_at
                    ) VALUES (%s,%s,%s,%s,'equipment',%s,%s,%s,%s,%s,%s,now())
                    """,
                    (
                        prediction_result_id,
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        row["asset_id"],
                        status,
                        artifact["provenance"]["model_version"],
                        source_version,
                        Jsonb(result_payload),
                        row["observed_at"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO pm_prediction_snapshots(
                        organization_id,project_id,workspace_id,dataset_version_id,
                        prediction_id,prediction_result_id,asset_id,asset_type,observed_at,
                        prediction_horizon_hours,failure_probability,predicted_failure_type,
                        confidence,status,model_version,feature_scope,source_sha256
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_version_id,
                        prediction_id,
                        prediction_result_id,
                        row["asset_id"],
                        asset_type,
                        row["observed_at"],
                        probability,
                        binary_type,
                        confidence,
                        status,
                        artifact["provenance"]["model_version"],
                        Jsonb(feature_scope),
                        artifact_checksum,
                    ),
                )
                for factor in artifact["top_factors"]:
                    signed = float(factor["signed_contribution"])
                    connection.execute(
                        """
                        INSERT INTO pm_prediction_factors(
                            organization_id,project_id,workspace_id,dataset_version_id,
                            prediction_id,rank,feature,feature_value,signed_contribution,
                            absolute_contribution,direction,explanation_method,source_type,source_sha256
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                  'product_runtime_inference',%s)
                        """,
                        (
                            ORGANIZATION_ID,
                            PROJECT_ID,
                            WORKSPACE_ID,
                            dataset_version_id,
                            prediction_id,
                            int(factor["rank"]),
                            factor["feature"],
                            float(factor["feature_value"]),
                            signed,
                            abs(signed),
                            factor["direction"],
                            factor["explanation_method"],
                            artifact_checksum,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO pm_prediction_timeline(
                        organization_id,project_id,workspace_id,dataset_version_id,
                        prediction_id,asset_id,asset_type,observed_at,
                        prediction_horizon_hours,failure_probability,status,top_factors,
                        model_version,feature_scope,source_type,source_sha256
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,
                              'product_runtime_inference',%s)
                    """,
                    (
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_version_id,
                        prediction_id,
                        row["asset_id"],
                        asset_type,
                        row["observed_at"],
                        probability,
                        status,
                        Jsonb(artifact["top_factors"]),
                        artifact["provenance"]["model_version"],
                        Jsonb(feature_scope),
                        artifact_checksum,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO pm_result_artifacts(
                        organization_id,project_id,workspace_id,dataset_version_id,
                        artifact_id,prediction_id,prediction_result_id,asset_id,asset_type,
                        observed_at,prediction_horizon_hours,prediction_task,
                        failure_probability,predicted_failure_type,status_grade,confidence,
                        top_factors,recommended_action,provenance,schema_version,
                        model_version,source_sha256
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,24,
                              'binary_failure_within_horizon',%s,%s,%s,%s,%s,%s,%s,
                              'result-artifact-v1.0',%s,%s)
                    """,
                    (
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_version_id,
                        artifact["artifact_id"],
                        prediction_id,
                        prediction_result_id,
                        row["asset_id"],
                        asset_type,
                        row["observed_at"],
                        probability,
                        binary_type,
                        status,
                        confidence,
                        Jsonb(artifact["top_factors"]),
                        Jsonb(artifact["recommended_action"]),
                        Jsonb(provenance),
                        artifact["provenance"]["model_version"],
                        artifact_checksum,
                    ),
                )

            final_rows = connection.execute(
                """
                SELECT status_grade,asset_type,COUNT(*) AS count
                FROM pm_result_artifacts
                WHERE dataset_version_id=%s
                GROUP BY status_grade,asset_type
                """,
                (dataset_version_id,),
            ).fetchall()
            status_counts: dict[str, int] = {}
            asset_type_counts: dict[str, int] = {}
            result_artifact_count = 0
            for item in final_rows:
                count = int(item["count"])
                result_artifact_count += count
                status = str(item["status_grade"])
                family = str(item["asset_type"])
                status_counts[status] = status_counts.get(status, 0) + count
                asset_type_counts[family] = asset_type_counts.get(family, 0) + count

            return {
                "model_versions": sorted({cnc_predictor.model_version, compressor_predictor.model_version}),
                "result_artifact_count": result_artifact_count,
                "status_counts": status_counts,
                "asset_type_counts": asset_type_counts,
                "selection_strategy": RUNTIME_SELECTION_STRATEGY,
                "materialization_profile": materialization_profile,
                "held_asset_count": len(held_assets),
                "held_assets": held_assets,
                "reused": False,
            }


def _parse_observed_at(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("gen_data observed_at must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _record_checksum(record: dict[str, Any]) -> str:
    rendered = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def read_complete_ticks(
    stream_root: str | Path,
    *,
    after: datetime | None = None,
    not_after: datetime | None = None,
    expected_asset_count: int = EXPECTED_ASSET_COUNT,
) -> list[tuple[datetime, list[dict[str, Any]]]]:
    """Read complete cross-line ticks from daemon ``sensor_stream.jsonl`` files.

    A daemon tick is committed only when every expected asset is present.  This
    prevents the database from seeing a half-written state while the 20 line
    workers are still appending their records.
    """

    root = Path(stream_root).expanduser()
    files = sorted(root.glob("sensor/**/sensor_stream.jsonl"))
    if not files:
        return []
    grouped: dict[datetime, dict[str, dict[str, Any]]] = defaultdict(dict)
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    observed_at = _parse_observed_at(payload["observed_at"])
                    asset_id = str(payload["asset_id"])
                except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                    raise ValueError(f"invalid gen_data stream row: {path}:{line_number}") from exc
                if after is not None and observed_at <= after:
                    continue
                if not_after is not None and observed_at > not_after:
                    continue
                grouped[observed_at][asset_id] = payload
    return [
        (observed_at, list(by_asset.values()))
        for observed_at, by_asset in sorted(grouped.items())
        if len(by_asset) >= expected_asset_count
    ]


def _safe_overlay_component(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value)
    )


def active_overlay_asset_ids(stream_root: str | Path) -> set[str]:
    """Return equipment whose Canonical/live stream is paused by Runtime Overlay."""

    state_path = Path(stream_root).expanduser() / "runtime_overlay" / "runtime_overlay_state.json"
    if not state_path.exists():
        return set()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    branches = payload.get("branches") or {}
    if not isinstance(branches, dict):
        raise ValueError("Runtime Overlay checkpoint branches must be an object")
    return {
        str(item["equipment_id"])
        for item in branches.values()
        if isinstance(item, dict) and item.get("equipment_id")
    }


def read_overlay_available_events(stream_root: str | Path) -> list[dict[str, Any]]:
    """Read the idempotent ``runtime_overlay.observations.available`` outbox."""

    path = Path(stream_root).expanduser() / "runtime_overlay" / "observations_available.jsonl"
    if not path.exists():
        return []
    events: dict[str, tuple[str, dict[str, Any]]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Runtime Overlay outbox JSON at {path}:{line_number}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"Runtime Overlay outbox event must be an object at {path}:{line_number}")
        if event.get("event_type") != "runtime_overlay.observations.available":
            raise ValueError(f"unsupported Runtime Overlay outbox event at {path}:{line_number}")
        event_id = str(event.get("event_id") or "")
        if not event_id:
            raise ValueError(f"Runtime Overlay outbox event_id is missing at {path}:{line_number}")
        digest = _record_checksum(event)
        previous = events.get(event_id)
        if previous is not None and previous[0] != digest:
            raise ValueError(f"Runtime Overlay event_id conflict: {event_id}")
        events[event_id] = (digest, event)
    return [item[1] for item in events.values()]


def _overlay_branch_path(stream_root: str | Path, event: dict[str, Any]) -> Path:
    session = _safe_overlay_component(str(event["simulation_session_id"]))
    branch = _safe_overlay_component(str(event["overlay_branch_id"]))
    return Path(stream_root).expanduser() / "runtime_overlay" / session / f"{branch}.jsonl"


def _read_overlay_event_rows(
    stream_root: str | Path,
    event: dict[str, Any],
) -> list[dict[str, Any]]:
    path = _overlay_branch_path(stream_root, event)
    if not path.exists():
        raise ValueError(f"Runtime Overlay branch storage is missing: {path}")
    observed_from = _parse_observed_at(event["observed_from"])
    observed_to = _parse_observed_at(event["observed_to"])
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
            observed_at = _parse_observed_at(row["observed_at"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid Runtime Overlay observation at {path}:{line_number}") from exc
        if str(row.get("overlay_branch_id")) != str(event["overlay_branch_id"]):
            continue
        if str(row.get("equipment_id") or row.get("asset_id")) != str(event["equipment_id"]):
            continue
        if not observed_from <= observed_at <= observed_to:
            continue
        if int(row.get("state_version", -1)) != int(event["state_version"]):
            raise ValueError("Runtime Overlay observation state_version differs from availability event")
        rows.append(row)
    rows.sort(key=lambda item: _parse_observed_at(item["observed_at"]))
    if len(rows) != int(event["batch_rows"]):
        raise ValueError(
            "Runtime Overlay availability batch does not match branch storage: "
            f"event={event['event_id']} expected={event['batch_rows']} actual={len(rows)}"
        )
    return rows


def _required_prior_rows(predictor: Any) -> int:
    feature_schema = getattr(predictor, "feature_schema", {}) or {}
    engineering = feature_schema.get("feature_engineering") or {}
    context = engineering.get("runtime_context") or {}
    return max(0, int(context.get("recent_history_rows_required", 0)))


def _overlay_history_record(payload: dict[str, Any], asset_type: str) -> dict[str, Any]:
    timestamp = _parse_observed_at(payload["observed_at"]).isoformat()
    if asset_type == "compressor":
        return {
            "timestamp": timestamp,
            "voltage_raw": float(payload["voltage_raw"]),
            "rotation_raw": float(payload["rotation_raw"]),
            "pressure_raw": float(payload["pressure_raw"]),
            "vibration_raw": float(payload["vibration_raw"]),
            "relative_vibration_z": float(payload["relative_vibration_z"]),
            "relative_vibration_zone": str(payload["relative_vibration_zone"]),
        }
    return {
        "timestamp": timestamp,
        "product_type": payload.get("product_type"),
        "air_temperature_k": float(payload["air_temperature_k"]),
        "process_temperature_k": float(payload["process_temperature_k"]),
        "rotational_speed_rpm": float(payload["rotational_speed_rpm"]),
        "torque_nm": float(payload["torque_nm"]),
        "tool_wear_min": float(payload["tool_wear_min"]),
    }


def _evaluate_overlay_branch(
    database_url: str,
    dataset_version_id: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    psycopg, dict_row, Jsonb = _postgres_modules()
    asset_id = str(event["equipment_id"])
    branch_id = str(event["overlay_branch_id"])
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            _set_scope(connection)
            asset = connection.execute(
                "SELECT asset_type FROM pm_assets WHERE dataset_version_id=%s AND asset_id=%s",
                (dataset_version_id, asset_id),
            ).fetchone()
            if asset is None:
                raise ValueError(f"Runtime Overlay references unknown live asset: {asset_id}")
            asset_type = str(asset["asset_type"])
            predictor = configured_predictor(asset_type)
            required_prior_rows = _required_prior_rows(predictor)
            rows = connection.execute(
                """
                SELECT observed_at,observation_json,source_sha256
                FROM pm_runtime_overlay_observations
                WHERE dataset_version_id=%s AND overlay_branch_id=%s
                ORDER BY observed_at
                """,
                (dataset_version_id, branch_id),
            ).fetchall()
            generated_rows = len(rows)
            runtime_status = "warming_up"
            result: dict[str, Any] | None = None
            model_version: str | None = getattr(predictor, "model_version", None)
            prediction_id: str | None = None
            latest_observed_at = rows[-1]["observed_at"] if rows else None

            if rows and generated_rows >= required_prior_rows + 1:
                current = rows[-1]
                current_payload = dict(current["observation_json"] or {})
                history_rows = rows[-(required_prior_rows + 1) : -1] if required_prior_rows else []
                history = [
                    _overlay_history_record(dict(item["observation_json"] or {}), asset_type)
                    for item in history_rows
                ]
                fixture = _runtime_fixture(
                    {
                        "observed_at": current["observed_at"],
                        "asset_id": asset_id,
                        "asset_type": asset_type,
                        "observation": current_payload,
                    },
                    history=history,
                    source_version=OVERLAY_SOURCE_VERSION,
                )
                fixture["event_id"] = f"runtime-overlay:{branch_id}:{current['observed_at'].isoformat()}"
                fixture["scenario_id"] = f"runtime-overlay:{branch_id}"
                artifact = build_product_result_artifact(fixture, predictor=predictor)
                provenance = dict(artifact["provenance"])
                provenance.update(
                    {
                        "source_kind": "maintenance_replay_overlay",
                        "dataset_version_id": dataset_version_id,
                        "overlay_branch_id": branch_id,
                        "history_segment_id": str(event["history_segment_id"]),
                        "simulation_session_id": str(event["simulation_session_id"]),
                        "maintenance_action_id": str(event["maintenance_action_id"]),
                        "maintenance_event_id": str(event["maintenance_event_id"]),
                        "runtime_overlay_available_event_id": str(event["event_id"]),
                        "state_version": int(event["state_version"]),
                        "source_observation_sha256": str(current["source_sha256"]),
                        "history_pre_maintenance_mixed": False,
                    }
                )
                result = {**artifact, "provenance": provenance}
                prediction_id = str(provenance["prediction_id"])
                runtime_status = (
                    "history_insufficient"
                    if result.get("data_quality_warnings")
                    else "predicted"
                )

            if result is not None and runtime_status == "predicted":
                _persist_overlay_product_result(
                    connection,
                    Jsonb,
                    dataset_version_id=dataset_version_id,
                    asset_id=asset_id,
                    asset_type=asset_type,
                    result=result,
                )

            connection.execute(
                """
                INSERT INTO pm_runtime_overlay_state(
                    organization_id,project_id,workspace_id,dataset_version_id,
                    overlay_branch_id,simulation_session_id,history_segment_id,
                    maintenance_action_id,maintenance_event_id,asset_id,asset_type,
                    runtime_status,generated_rows,required_prior_rows,latest_observed_at,
                    model_version,prediction_id,latest_result_json,updated_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (dataset_version_id,overlay_branch_id) DO UPDATE SET
                    runtime_status=EXCLUDED.runtime_status,
                    generated_rows=EXCLUDED.generated_rows,
                    required_prior_rows=EXCLUDED.required_prior_rows,
                    latest_observed_at=EXCLUDED.latest_observed_at,
                    model_version=EXCLUDED.model_version,
                    prediction_id=EXCLUDED.prediction_id,
                    latest_result_json=EXCLUDED.latest_result_json,
                    updated_at=now()
                """,
                (
                    ORGANIZATION_ID,
                    PROJECT_ID,
                    WORKSPACE_ID,
                    dataset_version_id,
                    branch_id,
                    str(event["simulation_session_id"]),
                    str(event["history_segment_id"]),
                    str(event["maintenance_action_id"]),
                    str(event["maintenance_event_id"]),
                    asset_id,
                    asset_type,
                    runtime_status,
                    generated_rows,
                    required_prior_rows,
                    latest_observed_at,
                    model_version,
                    prediction_id,
                    Jsonb(result) if result is not None else None,
                ),
            )
    return {
        "overlay_branch_id": branch_id,
        "equipment_id": asset_id,
        "runtime_status": runtime_status,
        "generated_rows": generated_rows,
        "required_prior_rows": required_prior_rows,
        "latest_observed_at": latest_observed_at.isoformat() if latest_observed_at else None,
        "model_version": model_version,
        "prediction_id": prediction_id,
        "result": result,
    }


def _persist_overlay_product_result(
    connection: Any,
    Jsonb: Any,
    *,
    dataset_version_id: str,
    asset_id: str,
    asset_type: str,
    result: dict[str, Any],
) -> None:
    """Project the latest post-maintenance branch result into the product read model."""

    existing = connection.execute(
        """
        SELECT prediction_id,prediction_result_id
        FROM pm_prediction_snapshots
        WHERE dataset_version_id=%s AND asset_id=%s
        """,
        (dataset_version_id, asset_id),
    ).fetchall()
    prediction_ids = [str(row["prediction_id"]) for row in existing]
    prediction_result_ids = [str(row["prediction_result_id"]) for row in existing]
    connection.execute(
        "DELETE FROM pm_result_artifacts WHERE dataset_version_id=%s AND asset_id=%s",
        (dataset_version_id, asset_id),
    )
    connection.execute(
        "DELETE FROM pm_prediction_timeline WHERE dataset_version_id=%s AND asset_id=%s",
        (dataset_version_id, asset_id),
    )
    connection.execute(
        "DELETE FROM pm_prediction_snapshots WHERE dataset_version_id=%s AND asset_id=%s",
        (dataset_version_id, asset_id),
    )
    if prediction_result_ids:
        connection.execute(
            "DELETE FROM prediction_results WHERE prediction_id = ANY(%s)",
            (prediction_result_ids,),
        )

    provenance = dict(result["provenance"])
    prediction_id = str(provenance["prediction_id"])
    prediction_result_id = (
        f"pmoverlay-{uuid.uuid5(uuid.NAMESPACE_URL, f'{dataset_version_id}:{prediction_id}:overlay')}"
    )
    observed_at = _parse_observed_at(result["observed_at"])
    probability = float(result["failure_probability"])
    status = str(result["status_grade"])
    confidence = float(result["confidence"])
    binary_type = (
        "failure_risk"
        if str(result["predicted_failure_type"]) == "failure_risk"
        else "no_significant_risk"
    )
    artifact_checksum = _record_checksum(result)
    factors = list(result.get("top_factors") or [])
    feature_scope = [str(item["feature"]) for item in factors]
    payload = {
        **result,
        "predicted_failure_type": binary_type,
        "dataset_version_id": dataset_version_id,
        "source_type": "product_runtime_inference",
    }

    connection.execute(
        """
        INSERT INTO prediction_results(
            prediction_id,organization_id,project_id,workspace_id,
            subject_object_type,subject_object_id,prediction_status,
            model_version,dataset_version,payload_json,created_at,received_at
        ) VALUES (%s,%s,%s,%s,'equipment',%s,%s,%s,%s,%s,%s,now())
        """,
        (
            prediction_result_id,
            ORGANIZATION_ID,
            PROJECT_ID,
            WORKSPACE_ID,
            asset_id,
            status,
            str(provenance["model_version"]),
            OVERLAY_SOURCE_VERSION,
            Jsonb(payload),
            observed_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO pm_prediction_snapshots(
            organization_id,project_id,workspace_id,dataset_version_id,
            prediction_id,prediction_result_id,asset_id,asset_type,observed_at,
            prediction_horizon_hours,failure_probability,predicted_failure_type,
            confidence,status,model_version,feature_scope,source_sha256
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,%s,%s)
        """,
        (
            ORGANIZATION_ID,
            PROJECT_ID,
            WORKSPACE_ID,
            dataset_version_id,
            prediction_id,
            prediction_result_id,
            asset_id,
            asset_type,
            observed_at,
            probability,
            binary_type,
            confidence,
            status,
            str(provenance["model_version"]),
            Jsonb(feature_scope),
            artifact_checksum,
        ),
    )
    for factor in factors:
        signed = float(factor["signed_contribution"])
        connection.execute(
            """
            INSERT INTO pm_prediction_factors(
                organization_id,project_id,workspace_id,dataset_version_id,
                prediction_id,rank,feature,feature_value,signed_contribution,
                absolute_contribution,direction,explanation_method,source_type,source_sha256
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      'maintenance_replay_overlay',%s)
            """,
            (
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                dataset_version_id,
                prediction_id,
                int(factor["rank"]),
                str(factor["feature"]),
                float(factor["feature_value"]),
                signed,
                abs(signed),
                str(factor["direction"]),
                str(factor["explanation_method"]),
                artifact_checksum,
            ),
        )
    connection.execute(
        """
        INSERT INTO pm_prediction_timeline(
            organization_id,project_id,workspace_id,dataset_version_id,
            prediction_id,asset_id,asset_type,observed_at,prediction_horizon_hours,
            failure_probability,status,top_factors,model_version,feature_scope,
            source_type,source_sha256
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,
                  'maintenance_replay_overlay',%s)
        """,
        (
            ORGANIZATION_ID,
            PROJECT_ID,
            WORKSPACE_ID,
            dataset_version_id,
            prediction_id,
            asset_id,
            asset_type,
            observed_at,
            probability,
            status,
            Jsonb(factors),
            str(provenance["model_version"]),
            Jsonb(feature_scope),
            artifact_checksum,
        ),
    )
    connection.execute(
        """
        INSERT INTO pm_result_artifacts(
            organization_id,project_id,workspace_id,dataset_version_id,
            artifact_id,prediction_id,prediction_result_id,asset_id,asset_type,
            observed_at,prediction_horizon_hours,prediction_task,
            failure_probability,predicted_failure_type,status_grade,confidence,
            top_factors,recommended_action,provenance,schema_version,
            model_version,source_sha256
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,24,
                  'binary_failure_within_horizon',%s,%s,%s,%s,%s,%s,%s,
                  'result-artifact-v1.0',%s,%s)
        """,
        (
            ORGANIZATION_ID,
            PROJECT_ID,
            WORKSPACE_ID,
            dataset_version_id,
            str(result["artifact_id"]),
            prediction_id,
            prediction_result_id,
            asset_id,
            asset_type,
            observed_at,
            probability,
            binary_type,
            status,
            confidence,
            Jsonb(factors),
            Jsonb(result["recommended_action"]),
            Jsonb(provenance),
            str(provenance["model_version"]),
            artifact_checksum,
        ),
    )


def _consume_overlay_event(
    database_url: str,
    dataset_version_id: str,
    stream_root: str | Path,
    event: dict[str, Any],
) -> dict[str, Any]:
    psycopg, dict_row, Jsonb = _postgres_modules()
    event_id = str(event["event_id"])
    event_checksum = _record_checksum(event)
    rows = _read_overlay_event_rows(stream_root, event)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            _set_scope(connection)
            existing = connection.execute(
                """
                SELECT source_sha256 FROM pm_runtime_overlay_events
                WHERE dataset_version_id=%s AND event_id=%s
                """,
                (dataset_version_id, event_id),
            ).fetchone()
            if existing is not None and str(existing["source_sha256"]) != event_checksum:
                raise ValueError(f"Runtime Overlay availability event identity conflict: {event_id}")
            asset = connection.execute(
                "SELECT asset_type FROM pm_assets WHERE dataset_version_id=%s AND asset_id=%s",
                (dataset_version_id, str(event["equipment_id"])),
            ).fetchone()
            if asset is None:
                raise ValueError(f"Runtime Overlay references unknown live asset: {event['equipment_id']}")
            asset_type = str(asset["asset_type"])
            if existing is None:
                for row in rows:
                    observed_at = _parse_observed_at(row["observed_at"])
                    source_sha256 = str(row.get("observation_sha256") or _record_checksum(row))
                    connection.execute(
                        """
                        INSERT INTO pm_runtime_overlay_observations(
                            organization_id,project_id,workspace_id,dataset_version_id,
                            simulation_session_id,overlay_branch_id,history_segment_id,
                            maintenance_action_id,maintenance_event_id,asset_id,asset_type,
                            site_id,cell_id,observed_at,state_version,source_kind,
                            observation_json,source_sha256,created_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                  'maintenance_replay_overlay',%s,%s,now())
                        ON CONFLICT (dataset_version_id,overlay_branch_id,observed_at) DO NOTHING
                        """,
                        (
                            ORGANIZATION_ID,
                            PROJECT_ID,
                            WORKSPACE_ID,
                            dataset_version_id,
                            str(event["simulation_session_id"]),
                            str(event["overlay_branch_id"]),
                            str(event["history_segment_id"]),
                            str(event["maintenance_action_id"]),
                            str(event["maintenance_event_id"]),
                            str(event["equipment_id"]),
                            asset_type,
                            str(row["site_id"]),
                            str(row["cell_id"]),
                            observed_at,
                            int(event["state_version"]),
                            Jsonb(row),
                            source_sha256,
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO pm_runtime_overlay_events(
                        organization_id,project_id,workspace_id,dataset_version_id,
                        event_id,event_type,simulation_session_id,overlay_branch_id,
                        history_segment_id,maintenance_action_id,maintenance_event_id,
                        asset_id,state_version,batch_rows,generated_rows,observed_from,
                        observed_to,payload_json,source_sha256,consumed_at
                    ) VALUES (%s,%s,%s,%s,%s,'runtime_overlay.observations.available',%s,%s,
                              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                    """,
                    (
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_version_id,
                        event_id,
                        str(event["simulation_session_id"]),
                        str(event["overlay_branch_id"]),
                        str(event["history_segment_id"]),
                        str(event["maintenance_action_id"]),
                        str(event["maintenance_event_id"]),
                        str(event["equipment_id"]),
                        int(event["state_version"]),
                        int(event["batch_rows"]),
                        int(event["generated_rows"]),
                        _parse_observed_at(event["observed_from"]),
                        _parse_observed_at(event["observed_to"]),
                        Jsonb(event),
                        event_checksum,
                    ),
                )
    state = _evaluate_overlay_branch(database_url, dataset_version_id, event)
    return {"event_id": event_id, "reused": existing is not None, **state}


def process_overlay_available_events(
    *,
    stream_root: str | Path,
    database_url: str,
    dataset_version_id: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in read_overlay_available_events(stream_root):
        results.append(
            _consume_overlay_event(
                database_url,
                dataset_version_id,
                stream_root,
                event,
            )
        )
    return results


def _ensure_live_dataset_files(
    connection: Any,
    *,
    base_version_id: str,
    dataset_id: str,
    live_version_id: str,
    Jsonb: Any,
) -> None:
    """Seed lineage roles required by ontology materialization for a live version.

    Topology roles are inherited from the immutable Canonical base version. Live
    sensor roles receive deterministic virtual file identities because the source
    transport is append-only ``sensor_stream.jsonl`` rather than one immutable
    release file. This keeps source refs truthful while allowing a live Dataset
    Version to materialize the same ontology contract.
    """

    base_files = {
        str(row["role"]): row
        for row in connection.execute(
            """
            SELECT role,uri,media_type,checksum_sha256,size_bytes,format,schema_json
            FROM dataset_files
            WHERE dataset_version_id=%s AND role = ANY(%s)
            """,
            (base_version_id, list(LIVE_STATIC_LINEAGE_ROLES)),
        ).fetchall()
    }
    missing = [role for role in LIVE_STATIC_LINEAGE_ROLES if role not in base_files]
    if missing:
        raise RuntimeError(
            "canonical base Dataset Version is missing live topology lineage role(s): "
            + ", ".join(missing)
        )

    for role in LIVE_STATIC_LINEAGE_ROLES:
        row = base_files[role]
        file_id = f"file-{uuid.uuid5(uuid.NAMESPACE_URL, f'{live_version_id}:{role}')}"
        connection.execute(
            """
            INSERT INTO dataset_files(
                id,organization_id,project_id,workspace_id,dataset_id,dataset_version_id,
                uri,media_type,checksum_sha256,size_bytes,role,format,schema_json,created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT DO NOTHING
            """,
            (
                file_id,
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                dataset_id,
                live_version_id,
                str(row["uri"]),
                str(row["media_type"]),
                str(row["checksum_sha256"]),
                row["size_bytes"],
                role,
                row["format"],
                Jsonb(dict(row["schema_json"] or {})),
            ),
        )

    for role in LIVE_SENSOR_ROLES:
        checksum = hashlib.sha256(
            f"{live_version_id}:{role}:sensor-stream-jsonl-v1".encode("utf-8")
        ).hexdigest()
        file_id = f"file-{uuid.uuid5(uuid.NAMESPACE_URL, f'{live_version_id}:{role}')}"
        connection.execute(
            """
            INSERT INTO dataset_files(
                id,organization_id,project_id,workspace_id,dataset_id,dataset_version_id,
                uri,media_type,checksum_sha256,size_bytes,role,format,schema_json,created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,'application/x-ndjson',%s,NULL,%s,'jsonl',%s,now())
            ON CONFLICT DO NOTHING
            """,
            (
                file_id,
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                dataset_id,
                live_version_id,
                f"gen-data-live://sensor_stream/{role}",
                checksum,
                role,
                Jsonb(
                    {
                        "source_version": LIVE_SOURCE_VERSION,
                        "transport": "sensor_stream.jsonl",
                        "append_only": True,
                        "truth_exposed": False,
                    }
                ),
            ),
        )


def _cutover_seed_candidates(
    connection: Any,
    *,
    dataset_version_id: str,
    cutoff_at: datetime,
) -> list[dict[str, Any]]:
    """Select one current-or-past source observation per asset for cutover."""

    return list(
        connection.execute(
            """
            WITH latest_cnc AS (
                SELECT DISTINCT ON (o.asset_id)
                       o.asset_id,o.observed_at,o.source_sha256,'cnc'::text AS asset_type,
                       jsonb_build_object(
                           'product_type',o.product_type,
                           'air_temperature_k',o.air_temperature_k,
                           'process_temperature_k',o.process_temperature_k,
                           'rotational_speed_rpm',o.rotational_speed_rpm,
                           'torque_nm',o.torque_nm,
                           'tool_wear_min',o.tool_wear_min
                       ) AS observation
                FROM pm_cnc_observations o
                WHERE o.dataset_version_id=%s AND o.observed_at <= %s
                ORDER BY o.asset_id,o.observed_at DESC
            ), latest_compressor AS (
                SELECT DISTINCT ON (o.asset_id)
                       o.asset_id,o.observed_at,o.source_sha256,'compressor'::text AS asset_type,
                       jsonb_build_object(
                           'voltage_raw',o.voltage_raw,
                           'rotation_raw',o.rotation_raw,
                           'pressure_raw',o.pressure_raw,
                           'vibration_raw',o.vibration_raw,
                           'relative_vibration_z',o.relative_vibration_z,
                           'relative_vibration_zone',o.relative_vibration_zone
                       ) AS observation
                FROM pm_compressor_observations o
                WHERE o.dataset_version_id=%s AND o.observed_at <= %s
                ORDER BY o.asset_id,o.observed_at DESC
            )
            SELECT * FROM latest_cnc
            UNION ALL
            SELECT * FROM latest_compressor
            ORDER BY asset_id
            """,
            (dataset_version_id, cutoff_at, dataset_version_id, cutoff_at),
        ).fetchall()
    )


def _seed_live_product_results_for_cutover(
    connection: Any,
    *,
    seed_version_id: str,
    seed_source_version: str,
    live_version_id: str,
    cutoff_at: datetime,
    Jsonb: Any,
) -> int:
    """Build a non-future Product Result seed while wall-clock history warms up.

    Only the cutover seed may use the pre-live source Dataset Version. The seed
    is a fully evaluated current-model result whose observation timestamp is at
    or before ``cutoff_at``. Subsequent wall-clock inference reads history only
    from ``live_version_id``; this avoids both future timestamps and hidden
    cross-version history mixing.
    """

    existing = int(
        connection.execute(
            "SELECT COUNT(*) AS count FROM pm_result_artifacts WHERE dataset_version_id=%s",
            (live_version_id,),
        ).fetchone()["count"]
    )
    if existing:
        return existing

    candidates = _cutover_seed_candidates(
        connection,
        dataset_version_id=seed_version_id,
        cutoff_at=cutoff_at,
    )
    if len(candidates) != EXPECTED_ASSET_COUNT:
        raise RuntimeError(
            "wall-clock cutover seed requires one non-future observation for every asset: "
            f"expected={EXPECTED_ASSET_COUNT} actual={len(candidates)}"
        )

    seeded = 0
    for row in candidates:
        asset_id = str(row["asset_id"])
        asset_type = str(row["asset_type"])
        predictor = configured_predictor(asset_type)
        history = (
            _compressor_runtime_history(
                connection,
                seed_version_id,
                asset_id,
                row["observed_at"],
            )
            if asset_type == "compressor"
            else _cnc_runtime_history(
                connection,
                seed_version_id,
                asset_id,
                row["observed_at"],
            )
        )
        artifact = build_product_result_artifact(
            _runtime_fixture(
                row,
                history=history,
                source_version=seed_source_version,
            ),
            predictor=predictor,
        )
        if artifact.get("failure_probability") is None:
            raise RuntimeError(
                "wall-clock cutover seed cannot satisfy current Model Artifact contract: "
                f"asset={asset_id} warnings={artifact.get('data_quality_warnings') or []}"
            )

        probability = float(artifact["failure_probability"])
        diagnostic_type = str(artifact["predicted_failure_type"])
        if asset_type == "compressor" and diagnostic_type in {"failure_risk", "none"}:
            binary_type = (
                "failure_risk" if diagnostic_type == "failure_risk" else "no_significant_risk"
            )
        else:
            binary_type = "failure_risk" if probability >= 0.5 else "no_significant_risk"

        original_prediction_id = str(artifact["provenance"]["prediction_id"])
        prediction_id = f"pmcutover-{uuid.uuid5(uuid.NAMESPACE_URL, f'{live_version_id}:{original_prediction_id}')}"
        prediction_result_id = f"pmcutover-result-{uuid.uuid5(uuid.NAMESPACE_URL, f'{live_version_id}:{original_prediction_id}')}"
        source_artifact_id = str(artifact["artifact_id"])
        artifact_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"{live_version_id}:{source_artifact_id}")
        artifact_id = f"pmcutover-artifact-{artifact_uuid}"
        cutover_sha256 = hashlib.sha256(
            (
                f"{live_version_id}:{seed_version_id}:{row['source_sha256']}:"
                f"{row['observed_at'].isoformat()}:{artifact['artifact_id']}"
            ).encode("utf-8")
        ).hexdigest()
        provenance = dict(artifact["provenance"])
        provenance.update(
            {
                "prediction_id": prediction_id,
                "dataset_version_id": live_version_id,
                "source_version": LIVE_SOURCE_VERSION,
                "source_type": "cutover_carry_forward",
                "cutover_seed": True,
                "cutover_seed_at": cutoff_at.isoformat(),
                "cutover_history_dataset_version_id": seed_version_id,
                "cutover_history_source_version": seed_source_version,
                "cutover_source_prediction_id": original_prediction_id,
                "live_runtime_history_mixed": False,
                "history_pre_maintenance_mixed": False,
            }
        )
        feature_scope = [str(item["feature"]) for item in artifact["top_factors"]]
        result_payload = {
            **artifact,
            "artifact_id": artifact_id,
            "predicted_failure_type": binary_type,
            "provenance": provenance,
            "dataset_version_id": live_version_id,
            "source_type": "cutover_carry_forward",
        }
        connection.execute(
            """
            INSERT INTO prediction_results(
                prediction_id,organization_id,project_id,workspace_id,
                subject_object_type,subject_object_id,prediction_status,
                model_version,dataset_version,payload_json,created_at,received_at
            ) VALUES (%s,%s,%s,%s,'equipment',%s,%s,%s,%s,%s,%s,now())
            """,
            (
                prediction_result_id,
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                asset_id,
                artifact["status_grade"],
                artifact["provenance"]["model_version"],
                LIVE_SOURCE_VERSION,
                Jsonb(result_payload),
                row["observed_at"],
            ),
        )
        connection.execute(
            """
            INSERT INTO pm_prediction_snapshots(
                organization_id,project_id,workspace_id,dataset_version_id,
                prediction_id,prediction_result_id,asset_id,asset_type,observed_at,
                prediction_horizon_hours,failure_probability,predicted_failure_type,
                confidence,status,model_version,feature_scope,source_sha256
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                live_version_id,
                prediction_id,
                prediction_result_id,
                asset_id,
                asset_type,
                row["observed_at"],
                probability,
                binary_type,
                float(artifact["confidence"]),
                artifact["status_grade"],
                artifact["provenance"]["model_version"],
                Jsonb(feature_scope),
                cutover_sha256,
            ),
        )
        for factor in artifact["top_factors"]:
            signed = float(factor["signed_contribution"])
            connection.execute(
                """
                INSERT INTO pm_prediction_factors(
                    organization_id,project_id,workspace_id,dataset_version_id,
                    prediction_id,rank,feature,feature_value,signed_contribution,
                    absolute_contribution,direction,explanation_method,source_type,source_sha256
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          'cutover_carry_forward',%s)
                """,
                (
                    ORGANIZATION_ID,
                    PROJECT_ID,
                    WORKSPACE_ID,
                    live_version_id,
                    prediction_id,
                    int(factor["rank"]),
                    factor["feature"],
                    float(factor["feature_value"]),
                    signed,
                    abs(signed),
                    factor["direction"],
                    factor["explanation_method"],
                    cutover_sha256,
                ),
            )
        connection.execute(
            """
            INSERT INTO pm_prediction_timeline(
                organization_id,project_id,workspace_id,dataset_version_id,
                prediction_id,asset_id,asset_type,observed_at,prediction_horizon_hours,
                failure_probability,status,top_factors,model_version,feature_scope,
                source_type,source_sha256
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,24,%s,%s,%s,%s,%s,
                      'cutover_carry_forward',%s)
            """,
            (
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                live_version_id,
                prediction_id,
                asset_id,
                asset_type,
                row["observed_at"],
                probability,
                artifact["status_grade"],
                Jsonb(artifact["top_factors"]),
                artifact["provenance"]["model_version"],
                Jsonb(feature_scope),
                cutover_sha256,
            ),
        )
        connection.execute(
            """
            INSERT INTO pm_result_artifacts(
                organization_id,project_id,workspace_id,dataset_version_id,
                artifact_id,prediction_id,prediction_result_id,asset_id,asset_type,
                observed_at,prediction_horizon_hours,prediction_task,
                failure_probability,predicted_failure_type,status_grade,confidence,
                top_factors,recommended_action,provenance,schema_version,
                model_version,source_sha256
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,24,
                      'binary_failure_within_horizon',%s,%s,%s,%s,%s,%s,%s,
                      'result-artifact-v1.0',%s,%s)
            """,
            (
                ORGANIZATION_ID,
                PROJECT_ID,
                WORKSPACE_ID,
                live_version_id,
                artifact_id,
                prediction_id,
                prediction_result_id,
                asset_id,
                asset_type,
                row["observed_at"],
                probability,
                binary_type,
                artifact["status_grade"],
                float(artifact["confidence"]),
                Jsonb(artifact["top_factors"]),
                Jsonb(artifact["recommended_action"]),
                Jsonb(provenance),
                artifact["provenance"]["model_version"],
                cutover_sha256,
            ),
        )
        seeded += 1
    return seeded


def _ensure_live_version(database_url: str) -> tuple[str, str]:
    psycopg, dict_row, Jsonb = _postgres_modules()
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            _set_scope(connection)
            existing = connection.execute(
                """
                SELECT id,dataset_id FROM dataset_versions
                WHERE organization_id=%s AND project_id=%s AND workspace_id=%s
                  AND source_version=%s
                ORDER BY version_number DESC LIMIT 1
                """,
                (ORGANIZATION_ID, PROJECT_ID, WORKSPACE_ID, LIVE_SOURCE_VERSION),
            ).fetchone()
            base = connection.execute(
                """
                SELECT v.*,d.display_name AS dataset_name
                FROM dataset_versions v
                JOIN datasets d ON d.id=v.dataset_id
                WHERE v.organization_id=%s AND v.project_id=%s AND v.workspace_id=%s
                  AND v.manifest_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM pm_assets a WHERE a.dataset_version_id=v.id)
                ORDER BY v.version_number DESC,v.created_at DESC
                LIMIT 1
                """,
                (ORGANIZATION_ID, PROJECT_ID, WORKSPACE_ID),
            ).fetchone()
            if base is None:
                raise RuntimeError("cannot create live Dataset Version without a canonical base version")
            seed = connection.execute(
                """
                SELECT id,source_version
                FROM dataset_versions
                WHERE organization_id=%s AND project_id=%s AND workspace_id=%s
                  AND source_version=%s
                  AND EXISTS (SELECT 1 FROM pm_assets a WHERE a.dataset_version_id=dataset_versions.id)
                ORDER BY version_number DESC,created_at DESC
                LIMIT 1
                """,
                (
                    ORGANIZATION_ID,
                    PROJECT_ID,
                    WORKSPACE_ID,
                    LEGACY_ACCELERATED_SOURCE_VERSION,
                ),
            ).fetchone()
            if seed is None:
                seed = {
                    "id": base["id"],
                    "source_version": base["source_version"],
                }
            cutover_at = datetime.now(tz=timezone.utc)
            if existing is not None:
                dataset_id = str(existing["dataset_id"])
                version_id = str(existing["id"])
                _ensure_live_dataset_files(
                    connection,
                    base_version_id=str(base["id"]),
                    dataset_id=dataset_id,
                    live_version_id=version_id,
                    Jsonb=Jsonb,
                )
                carried = _seed_live_product_results_for_cutover(
                    connection,
                    seed_version_id=str(seed["id"]),
                    seed_source_version=str(seed["source_version"]),
                    live_version_id=version_id,
                    cutoff_at=cutover_at,
                    Jsonb=Jsonb,
                )
                if carried:
                    profile_row = connection.execute(
                        "SELECT profile_json FROM dataset_versions WHERE id=%s FOR UPDATE",
                        (version_id,),
                    ).fetchone()
                    profile = dict(profile_row["profile_json"] or {})
                    row_counts = dict(profile.get("row_counts") or {})
                    row_counts["result_artifact"] = carried
                    profile["row_counts"] = row_counts
                    connection.execute(
                        "UPDATE dataset_versions SET profile_json=%s WHERE id=%s",
                        (Jsonb(profile), version_id),
                    )
                return dataset_id, version_id

            dataset_id = str(base["dataset_id"])
            version_number = int(
                connection.execute(
                    "SELECT COALESCE(MAX(version_number),0)+1 AS value FROM dataset_versions WHERE dataset_id=%s",
                    (dataset_id,),
                ).fetchone()["value"]
            )
            version_id = f"dsv-{uuid.uuid5(uuid.NAMESPACE_URL, f'{dataset_id}:{LIVE_SOURCE_VERSION}')}"
            profile = dict(base["profile_json"] or {})
            profile["row_counts"] = {
                "compressor_sensor_observation": 0,
                "cnc_sensor_observation": 0,
                "result_artifact": 0,
            }
            profile["source_contract"] = {
                "producer": "Biz-CollabCraft/gen_data daemon",
                "transport": "sensor_stream.jsonl",
                "clock_mode": "wall_clock",
                "cadence_minutes": 10,
                "restart_policy": "align_to_current_boundary_without_backfill",
                "semantics": "physical-sensor wall-clock synthetic observations",
                "truth_exposed": False,
                "legacy_accelerated_source_version": LEGACY_ACCELERATED_SOURCE_VERSION,
                "cutover_seed_history_source_version": str(seed["source_version"]),
                "cutover_seed_policy": "latest_non_future_result_then_live_history_only",
            }
            checksum = hashlib.sha256(
                f"{dataset_id}:{LIVE_SOURCE_VERSION}:sensor-stream-contract-v1".encode("utf-8")
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO dataset_versions(
                    id,organization_id,project_id,workspace_id,dataset_id,
                    version_number,version_label,source_version,manifest_id,
                    checksum_sha256,schema_json,profile_json,record_count,status,
                    created_by,created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s,0,'published',%s,now())
                """,
                (
                    version_id,
                    ORGANIZATION_ID,
                    PROJECT_ID,
                    WORKSPACE_ID,
                    dataset_id,
                    version_number,
                    "gen_data live daemon · current Model Artifact",
                    LIVE_SOURCE_VERSION,
                    checksum,
                    Jsonb(dict(base["schema_json"] or {})),
                    Jsonb(profile),
                    "macmini-live-ingestor",
                ),
            )
            connection.execute(
                """
                INSERT INTO pm_assets(
                    organization_id,project_id,workspace_id,dataset_version_id,
                    asset_id,asset_type,site_id,cell_id,source_sha256,created_at
                )
                SELECT organization_id,project_id,workspace_id,%s,
                       asset_id,asset_type,site_id,cell_id,source_sha256,now()
                FROM pm_assets WHERE dataset_version_id=%s
                """,
                (version_id, base["id"]),
            )
            connection.execute(
                """
                INSERT INTO pm_asset_relations(
                    organization_id,project_id,workspace_id,dataset_version_id,
                    from_asset_id,relation_type,to_asset_id,source_sha256,created_at
                )
                SELECT organization_id,project_id,workspace_id,%s,
                       from_asset_id,relation_type,to_asset_id,source_sha256,now()
                FROM pm_asset_relations WHERE dataset_version_id=%s
                """,
                (version_id, base["id"]),
            )
            _ensure_live_dataset_files(
                connection,
                base_version_id=str(base["id"]),
                dataset_id=dataset_id,
                live_version_id=version_id,
                Jsonb=Jsonb,
            )
            carried = _seed_live_product_results_for_cutover(
                connection,
                seed_version_id=str(seed["id"]),
                seed_source_version=str(seed["source_version"]),
                live_version_id=version_id,
                cutoff_at=cutover_at,
                Jsonb=Jsonb,
            )
            if carried:
                profile["row_counts"]["result_artifact"] = carried
                connection.execute(
                    "UPDATE dataset_versions SET profile_json=%s WHERE id=%s",
                    (Jsonb(profile), version_id),
                )
            projection = connection.execute(
                """
                SELECT * FROM store_projections
                WHERE dataset_version_id=%s AND store_kind='relational'
                LIMIT 1
                """,
                (base["id"],),
            ).fetchone()
            if projection is not None:
                projection_id = f"proj-{uuid.uuid5(uuid.NAMESPACE_URL, f'{version_id}:relational')}"
                connection.execute(
                    """
                    INSERT INTO store_projections(
                        id,organization_id,project_id,workspace_id,dataset_id,dataset_version_id,
                        store_kind,status,object_namespace,source_version,record_count,attempt_count,
                        last_error,started_at,completed_at,updated_at,provider_run_id,provider_metadata_json
                    ) VALUES (%s,%s,%s,%s,%s,%s,'relational','ready',%s,%s,0,1,NULL,now(),now(),now(),%s,%s)
                    """,
                    (
                        projection_id,
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_id,
                        version_id,
                        projection["object_namespace"],
                        LIVE_SOURCE_VERSION,
                        f"gen-data-live:{version_id}",
                        Jsonb({"producer": "live_predictive_maintenance"}),
                    ),
                )
            return dataset_id, version_id


def _latest_ingested_at(database_url: str, dataset_version_id: str) -> datetime | None:
    psycopg, dict_row, _ = _postgres_modules()
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        _set_scope(connection)
        row = connection.execute(
            """
            SELECT GREATEST(
                (SELECT MAX(observed_at) FROM pm_cnc_observations WHERE dataset_version_id=%s),
                (SELECT MAX(observed_at) FROM pm_compressor_observations WHERE dataset_version_id=%s)
            ) AS observed_at
            """,
            (dataset_version_id, dataset_version_id),
        ).fetchone()
    return None if row is None else row["observed_at"]


def _insert_ticks(
    database_url: str,
    dataset_version_id: str,
    ticks: Iterable[tuple[datetime, list[dict[str, Any]]]],
) -> int:
    psycopg, dict_row, Jsonb = _postgres_modules()
    inserted = 0
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            _set_scope(connection)
            asset_types = {
                str(row["asset_id"]): str(row["asset_type"])
                for row in connection.execute(
                    "SELECT asset_id,asset_type FROM pm_assets WHERE dataset_version_id=%s",
                    (dataset_version_id,),
                ).fetchall()
            }
            for observed_at, records in ticks:
                for record in records:
                    asset_id = str(record["asset_id"])
                    asset_type = asset_types.get(asset_id)
                    if asset_type is None:
                        raise ValueError(f"gen_data emitted an unknown asset: {asset_id}")
                    checksum = _record_checksum(record)
                    common = (
                        ORGANIZATION_ID,
                        PROJECT_ID,
                        WORKSPACE_ID,
                        dataset_version_id,
                        observed_at,
                        asset_id,
                        str(record["site_id"]),
                        str(record["cell_id"]),
                        bool(record["is_operating"]),
                        str(record["operating_state"]),
                    )
                    if asset_type == "cnc":
                        result = connection.execute(
                            """
                            INSERT INTO pm_cnc_observations(
                                organization_id,project_id,workspace_id,dataset_version_id,
                                observed_at,asset_id,site_id,cell_id,is_operating,operating_state,
                                product_type,air_temperature_k,process_temperature_k,
                                rotational_speed_rpm,torque_nm,tool_wear_min,
                                generator_version,source_sha256,created_at
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                            ON CONFLICT (dataset_version_id,asset_id,observed_at) DO NOTHING
                            RETURNING 1
                            """,
                            (
                                *common,
                                str(record["product_type"]),
                                float(record["air_temperature_k"]),
                                float(record["process_temperature_k"]),
                                float(record["rotational_speed_rpm"]),
                                float(record["torque_nm"]),
                                float(record["tool_wear_min"]),
                                str(record["generator_version"]),
                                checksum,
                            ),
                        ).fetchone()
                    else:
                        result = connection.execute(
                            """
                            INSERT INTO pm_compressor_observations(
                                organization_id,project_id,workspace_id,dataset_version_id,
                                observed_at,asset_id,site_id,cell_id,is_operating,operating_state,
                                voltage_raw,rotation_raw,pressure_raw,vibration_raw,
                                relative_vibration_z,relative_vibration_zone,
                                generator_version,source_sha256,created_at
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                            ON CONFLICT (dataset_version_id,asset_id,observed_at) DO NOTHING
                            RETURNING 1
                            """,
                            (
                                *common,
                                float(record["voltage_raw"]),
                                float(record["rotation_raw"]),
                                float(record["pressure_raw"]),
                                float(record["vibration_raw"]),
                                float(record["relative_vibration_z"]),
                                str(record["relative_vibration_zone"]),
                                str(record["generator_version"]),
                                checksum,
                            ),
                        ).fetchone()
                    inserted += int(result is not None)
            counts = connection.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM pm_compressor_observations WHERE dataset_version_id=%s) AS compressor_count,
                  (SELECT COUNT(*) FROM pm_cnc_observations WHERE dataset_version_id=%s) AS cnc_count
                """,
                (dataset_version_id, dataset_version_id),
            ).fetchone()
            record_count = int(counts["compressor_count"]) + int(counts["cnc_count"])
            version = connection.execute(
                "SELECT profile_json FROM dataset_versions WHERE id=%s FOR UPDATE",
                (dataset_version_id,),
            ).fetchone()
            profile = dict(version["profile_json"] or {})
            row_counts = dict(profile.get("row_counts") or {})
            row_counts.update(
                {
                    "compressor_sensor_observation": int(counts["compressor_count"]),
                    "cnc_sensor_observation": int(counts["cnc_count"]),
                    "result_artifact": EXPECTED_ASSET_COUNT,
                }
            )
            profile["row_counts"] = row_counts
            connection.execute(
                "UPDATE dataset_versions SET record_count=%s,profile_json=%s,status='published' WHERE id=%s",
                (record_count, Jsonb(profile), dataset_version_id),
            )
            connection.execute(
                """
                UPDATE store_projections
                SET record_count=%s,status='ready',updated_at=now(),completed_at=now()
                WHERE dataset_version_id=%s AND store_kind='relational'
                """,
                (record_count, dataset_version_id),
            )
    return inserted


def ingest_once(
    *,
    stream_root: str | Path = DEFAULT_STREAM_ROOT,
    database_url: str | None = None,
) -> dict[str, Any]:
    target = _normalize_database_url(database_url or database_target())
    dataset_id, dataset_version_id = _ensure_live_version(target)
    active_overlay_assets = active_overlay_asset_ids(stream_root)
    latest = _latest_ingested_at(target, dataset_version_id)
    expected_live_assets = max(1, EXPECTED_ASSET_COUNT - len(active_overlay_assets))
    live_now = datetime.now(tz=timezone.utc)
    ticks = read_complete_ticks(
        stream_root,
        after=latest,
        not_after=live_now + MAX_LIVE_CLOCK_SKEW,
        expected_asset_count=expected_live_assets,
    )
    if not ticks:
        overlay = process_overlay_available_events(
            stream_root=stream_root,
            database_url=target,
            dataset_version_id=dataset_version_id,
        )
        return {
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "source_version": LIVE_SOURCE_VERSION,
            "new_ticks": 0,
            "inserted_rows": 0,
            "latest_observed_at": latest.isoformat() if latest else None,
            "active_overlay_assets": sorted(active_overlay_assets),
            "runtime_overlay": overlay,
        }
    inserted = _insert_ticks(target, dataset_version_id, ticks)
    runtime = _materialize_runtime_results(
        target,
        dataset_version_id,
        source_version=LIVE_SOURCE_VERSION,
        materialization_profile=LIVE_MATERIALIZATION_PROFILE,
        excluded_asset_ids=active_overlay_assets,
    )
    # Normal live materialization atomically refreshes its current-state output
    # rows. Project the active post-maintenance branch only after that refresh so
    # the target equipment rejoins the standard Product Result read model without
    # mixing its pre-maintenance source history back into temporal inference.
    overlay = process_overlay_available_events(
        stream_root=stream_root,
        database_url=target,
        dataset_version_id=dataset_version_id,
    )
    materializer = PredictiveMaintenanceOntologyMaterializer(target)
    materializer.ensure_default_mapping(
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
        approve=True,
        approved_by="macmini-live-ingestor",
    )
    ontology = materializer.materialize(
        organization_id=ORGANIZATION_ID,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        dataset_id=dataset_id,
        dataset_version_id=dataset_version_id,
    )
    return {
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "source_version": LIVE_SOURCE_VERSION,
        "new_ticks": len(ticks),
        "inserted_rows": inserted,
        "latest_observed_at": ticks[-1][0].isoformat(),
        "active_overlay_assets": sorted(active_overlay_assets),
        "runtime_overlay": overlay,
        "runtime": runtime,
        "ontology": ontology.model_dump(mode="json"),
    }


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    stream_root = Path(os.getenv("GEN_DATA_RUNTIME_OUTPUT_ROOT", str(DEFAULT_STREAM_ROOT)))
    poll_seconds = max(1.0, float(os.getenv("LIVE_PM_POLL_SECONDS", "5")))
    once = os.getenv("LIVE_PM_RUN_ONCE", "0").lower() in {"1", "true", "yes"}
    while True:
        try:
            payload = ingest_once(stream_root=stream_root)
            LOGGER.info("live predictive-maintenance ingest: %s", json.dumps(payload, default=str))
        except Exception:
            LOGGER.exception("live predictive-maintenance ingest failed")
            if once:
                raise
        if once:
            break
        time.sleep(poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

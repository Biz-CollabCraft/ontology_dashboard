from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

MODEL_INPUT_COLUMNS = [
    "Type",
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
]
TARGET_COLUMN = "Machine failure"
FAILURE_MODE_COLUMNS = ["TWF", "HDF", "PWF", "OSF", "RNF"]
IDENTIFIER_COLUMNS = ["UDI", "Product ID"]
DERIVED_COLUMNS = [
    "temperature_difference_k",
    "mechanical_power_w",
    "overstrain_index",
]

SENSOR_RANGES: dict[str, tuple[float, float]] = {
    "air_temperature_k": (250.0, 350.0),
    "process_temperature_k": (250.0, 400.0),
    "rotational_speed_rpm": (0.0, 10000.0),
    "torque_nm": (0.0, 500.0),
    "tool_wear_min": (0.0, 1000.0),
}

DISPLAY_NAMES = {
    "tool_wear_min": "공구 마모",
    "temperature_difference_k": "공정·공기 온도 차이",
    "mechanical_power_w": "기계 동력",
    "overstrain_index": "과부하 지표",
    "torque_nm": "토크",
    "rotational_speed_rpm": "회전 속도",
    "process_temperature_k": "공정 온도",
    "air_temperature_k": "공기 온도",
}

UNITS = {
    "tool_wear_min": "min",
    "temperature_difference_k": "K",
    "mechanical_power_w": "W",
    "overstrain_index": "N·m·min",
    "torque_nm": "N·m",
    "rotational_speed_rpm": "rpm",
    "process_temperature_k": "K",
    "air_temperature_k": "K",
}

GEN_DATA_OUTPUT_ROOT_ENV = "GEN_DATA_OUTPUT_ROOT"


@dataclass(frozen=True)
class QualityIssue:
    code: str
    field: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


class CompleteFileTickNotFound(RuntimeError):
    pass


def project_root() -> Path:
    for env_name in ("ONTOLOGY_DASHBOARD_PROJECT_ROOT", "ONTOLOGY_DASHBOARD_ROOT"):
        configured = os.getenv(env_name, "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "contracts" / "schemas").is_dir() and (cwd / "data" / "fixtures").is_dir():
        return cwd
    app_root = Path("/app")
    if (app_root / "contracts" / "schemas").is_dir() and (app_root / "data" / "fixtures").is_dir():
        return app_root
    for parent in Path(__file__).resolve().parents:
        if (parent / "contracts" / "schemas").is_dir() and (parent / "data" / "fixtures").is_dir():
            return parent
    raise RuntimeError(
        "cannot resolve ontology_dashboard runtime root; "
        "set ONTOLOGY_DASHBOARD_PROJECT_ROOT"
    )


def schema_path() -> Path:
    return project_root() / "contracts" / "schemas" / "input-event.schema.json"


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_fixture(path: str | Path, *, validate_envelope: bool = True) -> dict[str, Any]:
    payload = load_json(path)
    if validate_envelope:
        schema = load_json(schema_path())
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
            key=lambda item: list(item.absolute_path),
        )
        if errors:
            rendered = "; ".join(
                f"{'/'.join(map(str, err.absolute_path)) or '<root>'}: {err.message}"
                for err in errors
            )
            raise ValueError(f"fixture schema validation failed: {rendered}")
    return payload


def derive_features(observation: dict[str, Any]) -> dict[str, float]:
    required = [
        "air_temperature_k",
        "process_temperature_k",
        "rotational_speed_rpm",
        "torque_nm",
        "tool_wear_min",
    ]
    missing = [name for name in required if observation.get(name) is None]
    if missing:
        raise ValueError(f"cannot derive features with missing values: {missing}")

    air = float(observation["air_temperature_k"])
    process = float(observation["process_temperature_k"])
    speed = float(observation["rotational_speed_rpm"])
    torque = float(observation["torque_nm"])
    wear = float(observation["tool_wear_min"])
    return {
        "temperature_difference_k": process - air,
        "mechanical_power_w": torque * speed * (2.0 * math.pi / 60.0),
        "overstrain_index": torque * wear,
    }


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def audit_fixture(payload: dict[str, Any]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    observations = [*payload.get("history", []), payload.get("observation", {})]

    for index, observation in enumerate(observations):
        prefix = f"history[{index}]" if index < len(observations) - 1 else "observation"
        for field, (minimum, maximum) in SENSOR_RANGES.items():
            value = observation.get(field)
            if value is None:
                issues.append(QualityIssue("missing_sensor", f"{prefix}.{field}", "필수 센서 값이 없습니다."))
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                issues.append(QualityIssue("invalid_type", f"{prefix}.{field}", "센서 값이 숫자가 아닙니다."))
                continue
            if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
                issues.append(
                    QualityIssue(
                        "out_of_range",
                        f"{prefix}.{field}",
                        f"값 {value}이 데이터 품질 범위 {minimum}–{maximum} 밖에 있습니다.",
                    )
                )

    timestamps = [_parse_timestamp(item.get("timestamp", "")) for item in payload.get("history", [])]
    if any(item is None for item in timestamps):
        issues.append(QualityIssue("invalid_timestamp", "history.timestamp", "유효하지 않은 타임스탬프가 있습니다."))
    else:
        for previous, current in zip(timestamps, timestamps[1:]):
            if current <= previous:  # type: ignore[operator]
                issues.append(QualityIssue("non_monotonic_time", "history.timestamp", "시계열 시간이 증가하지 않습니다."))
                break

    current_ts = _parse_timestamp(payload.get("observation", {}).get("timestamp", ""))
    if current_ts is None:
        issues.append(QualityIssue("invalid_timestamp", "observation.timestamp", "현재 관측 시각이 유효하지 않습니다."))
    elif timestamps and timestamps[-1] is not None and current_ts < timestamps[-1]:
        issues.append(QualityIssue("current_before_history", "observation.timestamp", "현재 관측이 마지막 이력보다 과거입니다."))

    return issues


def assert_no_leakage(feature_names: Iterable[str]) -> None:
    features = set(feature_names)
    forbidden = {TARGET_COLUMN, *FAILURE_MODE_COLUMNS}
    leaked = sorted(features & forbidden)
    if leaked:
        raise ValueError(f"target leakage columns are forbidden as model inputs: {leaked}")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_paths(root: Path | None = None) -> list[Path]:
    base = root or project_root()
    return sorted((base / "data" / "fixtures").glob("GS-*.json"))


def risk_from_file_record(record: dict[str, Any]) -> float:
    measurements = record.get("measurements") or {}
    if record.get("asset_type") == "compressor":
        zone_floor = {
            "attention": 0.45,
            "warning": 0.58,
            "alert": 0.72,
            "danger": 0.86,
        }.get(str(measurements.get("relative_vibration_zone", "")).lower(), 0.0)
        vibration_score = min(abs(float(measurements.get("relative_vibration_z") or 0)) / 4.0, 1.0)
        return round(max(zone_floor, vibration_score), 4)
    wear = min(float(measurements.get("tool_wear_min") or 0) / 240.0, 1.0)
    torque = min(float(measurements.get("torque_nm") or 0) / 80.0, 1.0)
    temperature_gap = max(
        float(measurements.get("process_temperature_k") or 0)
        - float(measurements.get("air_temperature_k") or 0),
        0.0,
    )
    return round(min(wear * 0.68 + torque * 0.22 + min(temperature_gap / 15.0, 1.0) * 0.1, 1.0), 4)


def risk_status(score: float) -> str:
    if score >= 0.75:
        return "critical"
    if score >= 0.45:
        return "warning"
    if score >= 0.20:
        return "attention"
    return "normal"


def measurement_factors(record: dict[str, Any]) -> list[dict[str, Any]]:
    measurements = record.get("measurements") or {}
    if record.get("asset_type") == "compressor":
        definitions = (
            ("relative_vibration_z", "상대 진동 이상도", "σ", lambda value: min(abs(value) / 4.0, 1.0)),
            ("vibration_raw", "진동", None, lambda value: min(abs(value) / 80.0, 1.0)),
            ("pressure_raw", "압력", None, lambda value: min(abs(value - 100.0) / 35.0, 1.0)),
            ("rotation_raw", "회전", None, lambda value: min(abs(value - 450.0) / 250.0, 1.0)),
        )
    else:
        definitions = (
            ("tool_wear_min", "공구 마모", "분", lambda value: min(value / 240.0, 1.0)),
            ("torque_nm", "토크", "N·m", lambda value: min(value / 80.0, 1.0)),
            ("rotational_speed_rpm", "회전 속도", "rpm", lambda value: min(abs(value - 1500.0) / 900.0, 1.0)),
            ("process_temperature_k", "공정 온도", "K", lambda value: min(max(value - 305.0, 0.0) / 20.0, 1.0)),
        )
    factors: list[dict[str, Any]] = []
    for feature, label, unit, contribution_fn in definitions:
        raw_value = measurements.get(feature)
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            continue
        value = float(raw_value)
        contribution = round(contribution_fn(value), 4)
        factors.append({
            "id": f"{record.get('asset_id')}:{feature}",
            "feature": feature,
            "label": label,
            "value": value,
            "unit": unit,
            "contribution": contribution,
            "direction": "risk_up" if contribution > 0 else "risk_down",
            "explanationMethod": "실시간 센서 범위 비교",
        })
    return sorted(factors, key=lambda item: abs(item["contribution"]), reverse=True)


def latest_complete_file_tick() -> tuple[Path, str, list[dict[str, Any]], list[tuple[str, dict[str, dict[str, Any]]]]]:
    configured_root = os.getenv(GEN_DATA_OUTPUT_ROOT_ENV, "").strip()
    session_roots = sorted(
        Path("/home/bistell/ontology_dashboard/data_preprocessed/local-realtime/sessions").glob(
            "*/gen-data-runtime"
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    roots = ([Path(configured_root)] if configured_root else []) + session_roots + [
        Path("/home/bistell/gen_data/output")
    ]
    output_root = next((root for root in roots if any(root.glob("runs/*/source/sensor_records.jsonl"))), roots[-1])
    streams = sorted(
        output_root.glob("runs/*/source/sensor_records.jsonl"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for stream in streams:
        asset_master = stream.parents[1] / "canonical" / "asset_master.csv"
        expected_assets: set[str] = set()
        if asset_master.exists():
            with asset_master.open("r", encoding="utf-8-sig", newline="") as handle:
                expected_assets = {
                    row["asset_id"] for row in csv.DictReader(handle) if row.get("asset_id")
                }
        ticks: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        with stream.open("rb") as handle:
            end = handle.seek(0, 2)
            start = max(0, end - 2 * 1024 * 1024)
            handle.seek(start)
            if start:
                handle.readline()
            for line in handle:
                try:
                    record = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                observed_at = str(record.get("observed_at") or "")
                asset_id = str(record.get("asset_id") or "")
                if observed_at and asset_id:
                    ticks[observed_at][asset_id] = record
        complete_ticks: list[tuple[str, dict[str, dict[str, Any]]]] = []
        for tick_at in sorted(ticks):
            tick_records = ticks[tick_at]
            if expected_assets and expected_assets.issubset(tick_records):
                complete_ticks.append((tick_at, tick_records))
            elif not expected_assets and len(tick_records) >= 100:
                complete_ticks.append((tick_at, tick_records))
        for observed_at in sorted(ticks, reverse=True):
            records = ticks[observed_at]
            if expected_assets and expected_assets.issubset(records):
                return stream, observed_at, [records[key] for key in sorted(expected_assets)], complete_ticks[-72:]
            if not expected_assets and len(records) >= 100:
                return stream, observed_at, list(records.values()), complete_ticks[-72:]
    raise CompleteFileTickNotFound("완성된 gen_data 관측 틱을 찾지 못했습니다.")


def filesystem_event_artifact(
    *, run_id: str, observed_at: str, record: dict[str, Any], event_id: str
) -> dict[str, Any]:
    asset_id = str(record["asset_id"])
    asset_type = str(record.get("asset_type") or "equipment")
    score = risk_from_file_record(record)
    status_grade = risk_status(score)
    action_id = "review_shutdown" if status_grade == "critical" else "request_inspection"
    factors = measurement_factors(record)
    source_body = json.dumps(
        {"event_id": event_id, "record": record},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    source_sha256 = hashlib.sha256(source_body).hexdigest()
    artifact_id = f"FILE-ART-{source_sha256[:24]}"
    sensors = {
        factor["feature"]: {
            "display_name": factor["label"],
            "current": factor["value"],
            "window_mean": factor["value"],
            "unit": factor.get("unit") or "",
            "z_score": None,
            "basis": {"source": "gen_data filesystem observation"},
        }
        for factor in factors
    }
    top_factors = [
        {
            "evidence_field_id": f"measurements.{factor['feature']}",
            "feature": factor["feature"],
            "display_name": factor["label"],
            "value": factor["value"],
            "unit": factor.get("unit") or "",
            "normal_range": "실시간 기준 범위",
            "direction": factor["direction"],
            "contribution": factor["contribution"],
            "source_type": "observed",
        }
        for factor in factors
    ]
    return {
        "artifact_id": artifact_id,
        "artifact_type": "prediction_result",
        "schema_version": "result-artifact-v1.0",
        "event_id": event_id,
        "asset_id": asset_id,
        "asset_type": asset_type,
        "observed_at": observed_at,
        "generated_at": observed_at,
        "failure_probability": score,
        "threshold": 0.20,
        "status_grade": status_grade,
        "confidence": None,
        "confidence_label": "unavailable",
        "predicted_failure_type": str(record.get("branch_kind") or "live_sensor_anomaly"),
        "recommended_action": {"action": action_id},
        "top_factors": top_factors,
        "source_sha256": source_sha256,
        "policy_version": "filesystem-risk-policy-v1",
        "model_mode": "filesystem_live",
        "evidence_payload": {
            "sensor_evidence": {"sensors": sensors},
            "recommended_actions": [{"action_id": action_id, "label": "정비 승인 검토"}],
            "source_fields": [factor["evidence_field_id"] for factor in top_factors],
        },
        "provenance": {
            "dataset_version": run_id,
            "model_version": str(record.get("generator_version") or "filesystem-risk-v1"),
            "prediction_id": str(record.get("observation_id") or event_id),
            "source_type": "filesystem_live_observation",
            "evidence_payload_reference": f"gen_data://runs/{run_id}/source/sensor_records.jsonl#{record.get('observation_id', asset_id)}",
            "source_sha256": source_sha256,
            "canonical_source_mutated": False,
        },
        "lineage": {
            "policy_version": "filesystem-risk-policy-v1",
            "model_mode": "filesystem_live",
            "sensor_source": "gen_data filesystem observation",
            "source_sha256": source_sha256,
        },
    }

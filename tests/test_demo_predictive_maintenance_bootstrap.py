from __future__ import annotations

import json
from pathlib import Path

from app.dataset.ingestion import (
    BundleFileAdapter,
    PredictiveMaintenanceCanonicalV3SourceAdapter,
    default_adapter_registry,
)
from ontology_dashboard.demo_predictive_maintenance_bootstrap import (
    RUNTIME_MATERIALIZATION_PROFILE,
    RUNTIME_SELECTION_STRATEGY,
    _runtime_candidates,
    _runtime_fixture,
)
from app.diagnosis.evidence import build_product_result_artifact
from app.diagnosis.predictor import CompressorHeuristicPredictor, HeuristicPredictor
from predictive_maintenance_v3_helpers import create_small_v3_package


SOURCE_ROLES = {
    "asset_master",
    "asset_relation",
    "compressor_sensor_observation",
    "cnc_sensor_observation",
    "cnc_production_cycle",
    "maintenance_event",
}


def _declare_current_ownership(root: Path) -> None:
    path = root / "canonical" / "dataset" / "dataset_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ownership_contract"] = {
        "repository_role": "source_data_producer",
        "canonical_source_owner": "Biz-CollabCraft/gen_data",
        "semantic_ml_owner": "Biz-CollabCraft/ontology_dashboard/systems/generator",
        "runtime_result_owner": "Biz-CollabCraft/ontology_dashboard/systems/backend/diagnosis",
        "model_outputs_in_this_package": "reference_regression_fixture",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_v3_source_adapter_excludes_gen_data_prediction_fixtures(tmp_path: Path) -> None:
    root = create_small_v3_package(tmp_path)
    _declare_current_ownership(root)

    manifest = PredictiveMaintenanceCanonicalV3SourceAdapter.build_manifest(
        root,
        organization_id="org-test",
        project_id="project-test",
        workspace_id="workspace-test",
    )

    assert manifest.adapter_code == "predictive-maintenance-canonical-v3-source"
    assert {item.role for item in manifest.files} == SOURCE_ROLES
    assert all("/canonical/model_outputs/" not in item.uri for item in manifest.files)
    assert default_adapter_registry().get_bundle(manifest.adapter_code) is not None

    validation = BundleFileAdapter(allowed_roots=[root]).validate(manifest)
    assert validation.status == "completed"
    assert {item.role for item in validation.roles} == SOURCE_ROLES


def test_runtime_fixture_uses_only_canonical_cnc_observation_fields() -> None:
    from datetime import datetime, timezone

    row = {
        "asset_id": "CNC-S01-L01-01",
        "asset_type": "cnc",
        "observed_at": datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
        "observation": {
            "product_type": "M",
            "air_temperature_k": 300.0,
            "process_temperature_k": 307.7,
            "rotational_speed_rpm": 1280.0,
            "torque_nm": 46.0,
            "tool_wear_min": 220.0,
        },
    }

    fixture = _runtime_fixture(row)

    assert fixture["dataset_version"] == "canonical-ai4i-physics-v3.1"
    assert fixture["asset_type"] == "cnc"
    assert fixture["history"] == []
    assert set(fixture["observation"]) == {
        "timestamp",
        "product_type",
        "air_temperature_k",
        "process_temperature_k",
        "rotational_speed_rpm",
        "torque_nm",
        "tool_wear_min",
    }


def test_runtime_fixture_and_predictor_support_canonical_compressor_fields() -> None:
    from datetime import datetime, timezone

    row = {
        "asset_id": "CMP-S01-L01-01",
        "asset_type": "compressor",
        "observed_at": datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
        "observation": {
            "voltage_raw": 170.0,
            "rotation_raw": 450.0,
            "pressure_raw": 100.0,
            "vibration_raw": 51.0,
            "relative_vibration_z": 2.3,
            "relative_vibration_zone": "C",
        },
    }

    fixture = _runtime_fixture(row)
    prediction = CompressorHeuristicPredictor().predict(fixture)

    assert fixture["asset_type"] == "compressor"
    assert set(fixture["observation"]) == {
        "timestamp",
        "voltage_raw",
        "rotation_raw",
        "pressure_raw",
        "vibration_raw",
        "relative_vibration_z",
        "relative_vibration_zone",
    }
    assert prediction.model_version == "compressor-signal-heuristic-v1"
    assert prediction.risk_band == "warning"
    assert prediction.predicted_failure_type == "compressor_signal_anomaly"
    assert prediction.factors


def test_runtime_fixture_preserves_pre_current_history_from_canonical_selection() -> None:
    from datetime import datetime, timezone

    history = [
        {
            "timestamp": "2026-07-31T01:00:00+00:00",
            "air_temperature_k": 299.0,
            "process_temperature_k": 306.5,
            "rotational_speed_rpm": 1300.0,
            "torque_nm": 44.0,
            "tool_wear_min": 210.0,
        },
        {
            "timestamp": "2026-07-31T02:00:00+00:00",
            "air_temperature_k": 299.5,
            "process_temperature_k": 306.8,
            "rotational_speed_rpm": 1290.0,
            "torque_nm": 45.0,
            "tool_wear_min": 215.0,
        },
    ]
    row = {
        "asset_id": "CNC-S01-L01-01",
        "asset_type": "cnc",
        "observed_at": datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
        "observation": {
            "product_type": "M",
            "air_temperature_k": 300.0,
            "process_temperature_k": 307.7,
            "rotational_speed_rpm": 1280.0,
            "torque_nm": 46.0,
            "tool_wear_min": 220.0,
        },
        "history": history,
    }

    fixture = _runtime_fixture(row)
    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    history_timestamps = [item["timestamp"] for item in fixture["history"]]

    assert fixture["history"] == history
    assert history_timestamps == sorted(history_timestamps)
    assert history_timestamps[-1] < fixture["observation"]["timestamp"]
    assert artifact["detected_interval"] == {
        "start": history_timestamps[0],
        "end": fixture["observation"]["timestamp"],
    }
    assert all(
        warning.get("code") != "non_monotonic_time"
        for warning in artifact["data_quality_warnings"]
    )


def test_runtime_candidates_select_latest_observation_per_asset() -> None:
    class Result:
        def fetchall(self) -> list[dict[str, object]]:
            return [{"asset_id": "CNC-001"}]

    class Connection:
        def __init__(self) -> None:
            self.query = ""
            self.parameters: tuple[str, ...] = ()

        def execute(self, query: str, parameters: tuple[str, ...]) -> Result:
            self.query = query
            self.parameters = parameters
            return Result()

    connection = Connection()
    candidates = _runtime_candidates(connection, "dsv-current")

    assert candidates == [{"asset_id": "CNC-001"}]
    assert connection.parameters == ("dsv-current", [], "dsv-current", [])
    assert connection.query.count(
        "ROW_NUMBER() OVER (PARTITION BY o.asset_id ORDER BY o.observed_at DESC)"
    ) == 2
    assert connection.query.count("ORDER BY h.observed_at ASC") == 2
    assert "ORDER BY h.observed_at DESC" not in connection.query
    assert connection.query.count("h.observed_at < o.observed_at") == 2
    assert "pm_cnc_observations" in connection.query
    assert "pm_compressor_observations" in connection.query
    assert "UNION ALL" in connection.query
    assert "signal_rank" not in connection.query


def test_runtime_selection_strategy_declares_current_state_semantics() -> None:
    assert RUNTIME_SELECTION_STRATEGY == "latest_observation_per_asset_v1"
    assert RUNTIME_MATERIALIZATION_PROFILE == "cnc_and_compressor_artifact_current_state_v3"


def test_threshold_policy_is_declared_as_wheel_package_data() -> None:
    import tomllib

    root = Path(__file__).resolve().parents[1]
    payload = tomllib.loads(
        (root / "systems" / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "threshold_policy.json" in payload["tool"]["setuptools"]["package-data"]["app.diagnosis"]

from __future__ import annotations

import json
from pathlib import Path

from ontology_dashboard.adapters import (
    BundleFileAdapter,
    PredictiveMaintenanceCanonicalV3SourceAdapter,
    default_adapter_registry,
)
from ontology_dashboard.demo_predictive_maintenance_bootstrap import (
    RUNTIME_SELECTION_STRATEGY,
    _runtime_candidates,
    _runtime_fixture,
)
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
        "observed_at": datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
        "product_type": "M",
        "air_temperature_k": 300.0,
        "process_temperature_k": 307.7,
        "rotational_speed_rpm": 1280.0,
        "torque_nm": 46.0,
        "tool_wear_min": 220.0,
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
    assert connection.parameters == ("dsv-current",)
    assert "DISTINCT ON (o.asset_id)" in connection.query
    assert "ORDER BY o.asset_id, o.observed_at DESC" in connection.query
    assert "signal_rank" not in connection.query


def test_runtime_selection_strategy_declares_current_state_semantics() -> None:
    assert RUNTIME_SELECTION_STRATEGY == "latest_observation_per_asset_v1"


def test_threshold_policy_is_declared_as_wheel_package_data() -> None:
    import tomllib

    root = Path(__file__).resolve().parents[1]
    payload = tomllib.loads(
        (root / "systems" / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "threshold_policy.json" in payload["tool"]["setuptools"]["package-data"]["app.diagnosis"]

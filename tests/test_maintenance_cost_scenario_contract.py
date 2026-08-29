from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from app.maintenance import MaintenanceCostScenarioResult


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "schemas" / "maintenance-cost-scenario.schema.json"
EXAMPLE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "maintenance-cost-scenario"
    / "tool-replacement.json"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_tool_replacement_example_passes_typed_and_json_schema_contracts() -> None:
    payload = load_json(EXAMPLE_PATH)
    result = MaintenanceCostScenarioResult.model_validate(payload)

    assert result.lowest_calculated_cost_option_id == "option-tool-planned"
    assert {option.execution_timing.value for option in result.options} == {
        "immediate",
        "planned_window",
        "reinspect_after",
        "no_action_baseline",
    }
    errors = list(
        Draft202012Validator(
            load_json(SCHEMA_PATH), format_checker=FormatChecker()
        ).iter_errors(payload)
    )
    assert errors == []


def test_contract_does_not_reuse_synthetic_preventive_what_if_version() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["schema_version"] = "what-if-result-v1.0"

    with pytest.raises(ValidationError, match="maintenance-cost-scenario-v1.0"):
        MaintenanceCostScenarioResult.model_validate(payload)


def test_contract_rejects_missing_timing_scenario() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["options"].pop()

    with pytest.raises(ValidationError, match="all four timing scenarios"):
        MaintenanceCostScenarioResult.model_validate(payload)


def test_contract_rejects_total_that_does_not_equal_components() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["options"][0]["total_expected_cost"]["base_minor"] += 1

    with pytest.raises(ValidationError, match="must equal its cost components"):
        MaintenanceCostScenarioResult.model_validate(payload)


def test_contract_rejects_non_minimum_lowest_option() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["lowest_calculated_cost_option_id"] = "option-tool-immediate"

    with pytest.raises(ValidationError, match="lowest base cost"):
        MaintenanceCostScenarioResult.model_validate(payload)


def test_insufficient_option_never_invents_a_total() -> None:
    payload = load_json(EXAMPLE_PATH)
    for option in payload["options"]:
        option.update(
            {
                "calculation_status": "insufficient",
                "parts_cost": None,
                "labor_cost": None,
                "production_loss": None,
                "expected_failure_loss": None,
                "total_expected_cost": None,
                "expected_downtime": None,
                "confidence": "insufficient",
                "missing_inputs": ["parts_cost"],
            }
        )
    payload["lowest_calculated_cost_option_id"] = None
    payload["missing_inputs"] = ["parts_cost"]

    result = MaintenanceCostScenarioResult.model_validate(payload)
    assert result.lowest_calculated_cost_option_id is None
    assert all(option.total_expected_cost is None for option in result.options)


def test_contract_requires_decision_support_boundaries() -> None:
    payload = load_json(EXAMPLE_PATH)
    payload["limitations"].remove("NOT_RECOMMENDATION")

    with pytest.raises(ValidationError, match="decision-boundary limitations"):
        MaintenanceCostScenarioResult.model_validate(payload)

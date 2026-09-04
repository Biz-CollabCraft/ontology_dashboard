from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "tests" / "eval" / "agent_workflow_baseline_comparison_contract.json"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_baseline_contract_defines_three_distinct_arms() -> None:
    contract = _load_contract()
    assert set(contract["arms"]) == {"B1", "B2", "B3"}
    assert contract["arms"]["B1"]["input"] == "minimally_normalized_raw_input"
    assert "evidence_packet" in contract["arms"]["B1"]["excludes"]
    assert contract["arms"]["B2"]["uses"] == [
        "evidence_packet",
        "same_read_only_output_schema",
    ]
    assert "workflow_orchestration" in contract["arms"]["B2"]["excludes"]
    assert "output_validation" in contract["arms"]["B3"]["uses"]


def test_missing_metric_states_do_not_synthesize_zero() -> None:
    contract = _load_contract()
    sample_metrics = contract["sample_row"]["metrics"]
    assert sample_metrics["schema_validation_pass_rate"]["value"] is None
    assert sample_metrics["schema_validation_pass_rate"]["state"] == "not_measured"
    assert sample_metrics["saved_summary_reuse"]["value"] is None
    assert sample_metrics["saved_summary_reuse"]["state"] == "not_applicable"
    assert contract["aggregate_contract"]["missing_value_policy"].startswith(
        "exclude null values"
    )


def test_quality_and_fault_injection_are_separate_axes() -> None:
    contract = _load_contract()
    assert contract["fault_injection"]["primary_arm"] == "B3"
    assert contract["fault_injection"]["combined_with_quality_score"] is False
    assert "fault_injection" in contract["aggregate_contract"]["report_separately"]


def test_unexecuted_baseline_is_explicitly_unverified() -> None:
    contract = _load_contract()
    assert contract["status"] == "planned"
    assert contract["execution_status"] == "unverified"
    assert contract["sample_row"]["execution_status"] == "planned"


def test_presentation_minimum_prioritizes_llm_only_vs_pipeline() -> None:
    contract = _load_contract()
    profile = contract["execution_profile"]
    assert profile["case_count"] == 8
    assert profile["iterations_per_case"] == 3
    assert profile["total_llm_runs"] == 72
    assert contract["primary_comparison"] == "B3-B1"


def test_cost_is_required_but_never_synthesized() -> None:
    contract = _load_contract()
    assert "estimated_cost_per_run" in contract["core_metrics"]["cost"]
    assert "never synthesize zero" in contract["aggregate_contract"]["cost_policy"]
    cost = contract["sample_row"]["metrics"]["estimated_cost_per_run"]
    assert cost["value"] is None
    assert cost["state"] == "not_measured"

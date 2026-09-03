from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_agent_workflow_baseline.py"


def _load():
    spec = importlib.util.spec_from_file_location("workflow_baseline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _packet(module, scenario: str = "GS-002"):
    return json.loads(
        (module.ROOT / f"tests/fixtures/agent_review_packets/{scenario}.json").read_text(
            encoding="utf-8"
        )
    )


def test_minimal_suite_builds_72_randomized_rows(monkeypatch) -> None:
    monkeypatch.setenv("LLM_INPUT_PRICE_PER_1M_TOKENS", "0.15")
    monkeypatch.setenv("LLM_OUTPUT_PRICE_PER_1M_TOKENS", "0.60")
    monkeypatch.setenv("LLM_PRICING_VERSION", "test-rates-v1")
    module = _load()

    result = module.run_suite(provider=module.MockJsonProvider())

    assert result["case_count"] == 8
    assert result["iterations_per_case"] == 3
    assert result["sample_size"] == 72
    assert {row["arm"] for row in result["rows"]} == {"B1", "B2", "B3"}
    assert sorted(row["execution_order"] for row in result["rows"]) == list(range(1, 73))
    assert result["control_config"]["same_provider_model_and_generation_settings_for_all_arms"] is True
    assert result["control_config"]["usage_measurement"] == "estimated_from_serialized_payload_and_output_chars"
    assert result["aggregate"]["primary_comparison"] == "B3-B1"
    assert all(result["aggregate"]["by_arm"][arm]["runs"] == 24 for arm in module.ARMS)
    assert result["aggregate"]["by_arm"]["B3"]["reuse_count"] == 16
    assert result["aggregate"]["by_arm"]["B3"]["workflow_trace_completeness"] == 1.0
    assert all(
        result["aggregate"]["by_arm"][arm]["cost_state"] == "measured"
        for arm in module.ARMS
    )
    assert result["aggregate"]["comparison_order"] == ["B3-B1", "B2-B1", "B3-B2"]
    assert set(result["aggregate"]["comparisons"]) == {"B3-B1", "B2-B1", "B3-B2"}
    for arm in module.ARMS:
        aggregate = result["aggregate"]["by_arm"][arm]
        assert aggregate["gold_score_mean"] is not None
        assert aggregate["gold_score_median"] is not None
        assert len(aggregate["fixture_gold_scores"]) == 8
        assert aggregate["required_point_satisfaction_rate"] is not None
        assert set(aggregate["role_required_point_satisfaction_rate"]) == {
            "field_operator",
            "process_manager",
        }
        assert aggregate["input_tokens"] >= 0
        assert aggregate["output_tokens"] >= 0
        assert aggregate["total_tokens"] >= 0
        assert "structural_core_field_exact_match_rate" in aggregate
        assert "core_judgment_agreement_rate" not in aggregate


def test_row_preserves_full_gold_rubric_and_output() -> None:
    module = _load()
    row = module.run_arm(
        arm="B2",
        packet=_packet(module),
        iteration=2,
        provider=module.MockJsonProvider(),
        state=module.SimulationState(),
    )

    assert row["fixture_id"] == "GS-002"
    assert row["run_id"] == "B2:EVT-GS-002:2"
    assert row["llm_output"]["summary"]
    assert row["schema_validation"] == {"passed": True, "errors": []}
    assert row["gold_accuracy"]
    assert row["accuracy_goldset_score"] == row["gold_accuracy"]["accuracy_goldset_score"]
    assert row["matched_required_points"] == row["gold_accuracy"]["matched_required_points"]
    assert row["missing_required_points"] == row["gold_accuracy"]["missing_required_points"]
    assert row["role_required_points"] == row["gold_accuracy"]["role_scores"]
    assert row["forbidden_claims"] == row["gold_accuracy"]["must_not_claim_violations"]
    assert row["unsupported_claims"] == row["gold_accuracy"]["must_not_claim_violations"]
    assert row["usage_measurement"] == "estimated_from_serialized_payload_and_output_chars"


def test_cost_is_not_measured_without_versioned_rates(monkeypatch) -> None:
    for key in (
        "LLM_INPUT_PRICE_PER_1M_TOKENS",
        "LLM_OUTPUT_PRICE_PER_1M_TOKENS",
        "LLM_PRICING_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)
    module = _load()
    row = module.run_arm(
        arm="B1",
        packet=_packet(module),
        iteration=1,
        provider=module.MockJsonProvider(),
        state=module.SimulationState(),
    )
    assert row["estimated_cost"]["value"] is None
    assert row["estimated_cost"]["state"] == "not_measured"


def test_malformed_output_is_contained_by_b3_fallback() -> None:
    module = _load()
    row = module.run_arm(
        arm="B3",
        packet=_packet(module),
        iteration=1,
        provider=module.MockJsonProvider(),
        state=module.SimulationState(),
        fault="malformed_output",
    )
    assert row["attempt_count"] == 2
    assert row["fallback"] is True
    assert row["accepted"] is True
    assert row["workflow_trace"]["status"] == "fallback"
    assert row["fallback_reason"] == "validation_failed"


def test_timeout_is_bounded_and_falls_back() -> None:
    module = _load()
    row = module.run_arm(
        arm="B3",
        packet=_packet(module),
        iteration=1,
        provider=module.MockJsonProvider(),
        state=module.SimulationState(),
        fault="provider_timeout",
    )
    assert row["attempt_count"] == 2
    assert row["fallback"] is True
    assert row["fallback_reason"] == "TimeoutError"
    assert row["workflow_trace"]["trace_complete"] is True


def test_snapshot_mismatch_blocks_before_llm_and_side_effect() -> None:
    module = _load()
    row = module.run_arm(
        arm="B3",
        packet=_packet(module),
        iteration=1,
        provider=module.MockJsonProvider(),
        state=module.SimulationState(),
        fault="snapshot_mismatch",
    )
    assert row["status"] == "blocked"
    assert row["attempt_count"] == 0
    assert row["snapshot_mismatch_blocked"] is True
    assert row["blocked_side_effect"] is True
    assert row["estimated_cost"]["value"] == 0.0


def test_fault_suite_runs_three_scenarios_for_all_eight_cases() -> None:
    module = _load()
    result = module.run_fault_suite(provider=module.MockJsonProvider())
    assert result["sample_size"] == 24
    assert set(result["scenarios"]) == {
        "malformed_output",
        "provider_timeout",
        "snapshot_mismatch",
    }
    assert result["contained_count"] == 24
    assert result["bounded_retry_rows"] == 16
    assert result["blocked_side_effect_count"] == 8


def test_b1_uses_raw_projection_and_b2_uses_evidence_payload() -> None:
    module = _load()
    packet = _packet(module)
    baseline = module.compose_deterministic_agent_review_summary(packet)
    raw = module.raw_input_payload(packet, baseline)
    evidence = module.evidence_input_payload(packet)
    assert "raw_input" in raw
    assert "summary_context" not in raw
    assert "source_refs" not in raw["raw_input"]
    assert raw["baseline_editable_fields"] == {
        "title": "",
        "summary": "",
        "role_summaries": [
            {"role": "field_operator", "quote": ""},
            {"role": "process_manager", "quote": ""},
        ],
    }
    assert raw["output_roles"] == ["field_operator", "process_manager"]
    assert baseline["summary"] not in json.dumps(raw, ensure_ascii=False)
    assert all(
        item["quote"] not in json.dumps(raw, ensure_ascii=False)
        for item in baseline["role_summaries"]
    )
    assert "summary_context" in evidence
    assert evidence["summary_context"]["source_refs"]
    assert evidence["baseline_editable_fields"]["title"] == ""
    assert evidence["baseline_editable_fields"]["summary"] == ""
    assert all(item["quote"] == "" for item in evidence["baseline_editable_fields"]["role_summaries"])
    assert baseline["summary"] not in json.dumps(evidence["baseline_editable_fields"], ensure_ascii=False)
    assert all(
        item["quote"] not in json.dumps(evidence["baseline_editable_fields"], ensure_ascii=False)
        for item in baseline["role_summaries"]
    )


def test_cli_records_common_run_identity(tmp_path: Path) -> None:
    output = tmp_path / "baseline.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "mock",
            "--iterations",
            "1",
            "--run-id",
            "workflow-test-run",
            "--candidate-sha",
            "workflow-test-sha",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "systems/backend"},
        check=True,
        capture_output=True,
        text=True,
    )
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["run_id"] == "workflow-test-run"
    assert artifact["candidate_sha"] == "workflow-test-sha"

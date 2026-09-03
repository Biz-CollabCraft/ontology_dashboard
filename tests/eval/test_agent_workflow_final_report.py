from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_agent_workflow_final_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("final_report", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _artifacts(tmp_path: Path, *, candidate_sha: str = "candidate-sha"):
    identity = {"run_id": "run-1", "candidate_sha": candidate_sha}
    quality = {
        **identity,
        "mode": "live",
        "provider": "openai-compatible",
        "model": "test-model",
        "sample_size": 120,
        "aggregate": {
            "contract_error_rows": 0,
            "accepted_llm_candidates": 120,
            "fallback_summaries": 0,
            "gold_accuracy": {"accuracy_goldset_score": 0.9},
            "quality_scores": {},
            "latency": {},
            "cost": {},
        },
        "operating_gate": {
            "observed_fallback_rows": 0,
            "allowed_fallback_rows": 1,
        },
    }
    arm = {
        "runs": 24,
        "gold_score_mean": 0.9,
        "schema_validation_pass_rate": 1.0,
        "reuse_count": 0,
        "workflow_trace_completeness": None,
    }
    workflow = {
        **identity,
        "mode": "live",
        "sample_size": 72,
        "control_config": {
            "same_provider_model_and_generation_settings_for_all_arms": True
        },
        "aggregate": {
            "by_arm": {
                "B1": arm,
                "B2": arm,
                "B3": {
                    **arm,
                    "reuse_count": 16,
                    "workflow_trace_completeness": 1.0,
                },
            },
            "comparisons": {},
        },
        "fault_injection": {
            "sample_size": 24,
            "contained_count": 24,
            "scenarios": [
                "malformed_output",
                "provider_timeout",
                "snapshot_mismatch",
            ],
            "blocked_side_effect_count": 8,
            "bounded_retry_rows": 16,
        },
    }
    reliability = {
        **identity,
        "evaluation_mode": "integration",
        "database_backend": "isolated_sqlite",
        "scenario_count": 11,
        "passed": True,
        "acceptance": {"all": True},
        "aggregate": {"rates": {"side_effect_unchanged": 1.0}},
    }
    safety = {
        **identity,
        "passed": True,
        "scenario_count": 3,
        "temporal_validation_pass_count": 3,
        "mutation_attempt_count": 0,
        "recommendation_count": 0,
        "external_api_fallback_isolation_pass": True,
    }
    return {
        "quality_path": _write(tmp_path / "quality.json", quality),
        "workflow_path": _write(tmp_path / "workflow.json", workflow),
        "reliability_path": _write(tmp_path / "reliability.json", reliability),
        "safety_path": _write(tmp_path / "safety.json", safety),
    }


def test_final_report_keeps_gates_separate_and_human_review_pending(tmp_path: Path) -> None:
    module = _load()
    report, markdown = module.build_report(
        run_id="run-1",
        candidate_sha="candidate-sha",
        **_artifacts(tmp_path),
    )

    assert report["overall_release_decision"] == "pending_human_review"
    assert {
        name: gate.get("status")
        for name, gate in report["gates"].items()
    } == {
        "quality_gate": "passed",
        "workflow_value_gate": "passed",
        "reliability_gate": "passed",
        "safety_gate": "passed",
        "human_review_gate": "not_measured",
    }
    assert report["architecture_decision"]["langgraph"] == "deferred"
    assert "B1/B2/B3 workflow value" in markdown
    assert "production load or long-running soak reliability" in markdown


def test_final_report_passes_only_after_human_review(tmp_path: Path) -> None:
    module = _load()
    report, _ = module.build_report(
        run_id="run-1",
        candidate_sha="candidate-sha",
        human_review_status="passed",
        **_artifacts(tmp_path),
    )
    assert report["overall_release_decision"] == "passed"


def test_final_report_rejects_mixed_candidate_artifacts(tmp_path: Path) -> None:
    module = _load()
    with pytest.raises(ValueError, match="candidate_sha mismatch"):
        module.build_report(
            run_id="run-1",
            candidate_sha="other-sha",
            **_artifacts(tmp_path),
        )

from scripts.evaluate_operational_evidence_selection import evaluate


def test_operational_evidence_selection_eval_passes_s0_s1_gate() -> None:
    result = evaluate("test-candidate")

    assert result["evaluation_schema_version"] == (
        "operational-evidence-selection-eval-v1.0"
    )
    assert result["passed"] is True
    assert result["metrics"]["required_evidence_recall"] == 1.0
    assert result["metrics"]["context_reduction"] > 0
    assert result["selected_candidate_count"] < result["full_candidate_count"]
    assert result["live_llm_evaluation"] is False
    assert result["actual_mes_cmms_wms_qms_evaluation"] is False

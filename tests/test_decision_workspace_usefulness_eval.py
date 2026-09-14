import importlib
from pathlib import Path


def test_workspace_usefulness_comparison_distinguishes_workflow_structure(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    benchmark = importlib.import_module("evaluate_decision_workspace_usefulness")
    rows = []
    for case in benchmark.CASES:
        rows.append(benchmark.briefing_only(case))
        rows.append(benchmark.rule_only(case))
        rows.append(benchmark.durable_agent(case, tmp_path / f"{case.id}.db"))
    aggregate = benchmark.aggregate(rows)
    assert aggregate["briefing_only"]["workflow_readiness_rate"] == 0.2
    assert aggregate["rule_only_agent"]["workflow_readiness_rate"] == 0.6
    assert aggregate["durable_decision_session"]["workflow_readiness_rate"] == 1.0
    assert aggregate["durable_decision_session"]["manual_check_reduction_rate_vs_briefing"] == 1.0
    assert aggregate["rule_only_agent"]["manual_check_reduction_rate_vs_briefing"] == 0.5
    assert aggregate["durable_decision_session"]["check_rates"]["duplicate_request_reuse"] == 1
    assert aggregate["durable_decision_session"]["check_rates"]["recoverable_checkpoint"] == 1
    assert aggregate["rule_only_agent"]["check_rates"]["recoverable_checkpoint"] == 0

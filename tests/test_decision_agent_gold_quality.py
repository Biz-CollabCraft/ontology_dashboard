import importlib
from pathlib import Path


def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("evaluate_decision_agent_gold_quality")


def test_gold_set_is_reviewed_and_oracle_is_not_visible(monkeypatch):
    b = benchmark(monkeypatch)
    gold = b.load_gold(Path("evaluation/decision_quality/decision-agent-gold-v1.json"))
    review = b.review_gold(gold)
    assert review["passed"]
    assert len(gold) == 7
    assert {item.gold_action for item in gold} >= {None, b.A.REQUEST_INSPECTION, b.A.REQUEST_ADDITIONAL_DIAGNOSIS, b.A.REVIEW_PLANNED_MAINTENANCE}


def test_deterministic_baseline_is_scored_against_exact_gold(monkeypatch):
    b = benchmark(monkeypatch)
    gold = b.load_gold(Path("evaluation/decision_quality/decision-agent-gold-v1.json"))
    rows = [b.run_one(item, arm="deterministic", iteration=1, live=False) for item in gold]
    aggregate = b.aggregate(rows)["deterministic"]
    assert aggregate["policy_contained_rate"] == 1
    assert aggregate["must_not_action_avoided_rate"] == 1
    assert aggregate["required_tool_coverage_rate"] == 1
    assert aggregate["exact_action_rate"] == 5 / 7
    assert aggregate["abstain_appropriateness_rate"] == 5 / 7
    assert aggregate["runs"] == 7
    by_case = b.aggregate(rows)["by_case"]
    assert by_case["A3_RESERVED_UNSUITABLE"]["deterministic"]["exact"] == 0
    assert by_case["A5_REPLENISHMENT"]["deterministic"]["actions"] == {"REVIEW_PLANNED_MAINTENANCE": 1}


def test_gold_quality_eval_records_abstain_and_forbidden_actions(monkeypatch):
    b = benchmark(monkeypatch)
    gold = b.load_gold(Path("evaluation/decision_quality/decision-agent-gold-v1.json"))
    abstain_cases = [item for item in gold if item.gold_action is None]
    assert {item.case_id for item in abstain_cases} == {"A3_RESERVED_UNSUITABLE", "A5_REPLENISHMENT", "A6_CONFLICT"}
    for item in abstain_cases:
        assert b.A.REQUEST_MAINTENANCE in item.must_not_actions


def test_live_report_names_prompt_coupling_and_common_a5_failure():
    report = Path("docs/eval/decision-agent-gold-quality-luna-2026-09-15.md").read_text(encoding="utf-8")
    assert "current bounded planner prompt" in report
    assert "does not isolate model reasoning from prompt policy design" in report
    assert "Both arms failed `A5_REPLENISHMENT`" in report

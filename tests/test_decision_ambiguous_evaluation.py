"""Check benchmark validity and scoring independently of LLM outputs."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('evaluate_decision_agent_ambiguous')


def calls(tools, status='available'):
    return [SimpleNamespace(tool_name=t.value, status=status) for t in tools]


def test_paired_cases_share_policy_but_have_different_gold_and_evidence(benchmark):
    b = benchmark
    for group in ('warning', 'maintenance'):
        cases = [c for c in b.CASES if c.group == group]
        assert all(c.facts == cases[0].facts for c in cases)
        assert len({c.required for c in cases}) > 1
        assert len({c.actions for c in cases}) > 1
        for case in cases:
            allowed = b.DecisionPolicyGuard().evaluate(case.facts).allowed_actions
            assert all(a is None or a in allowed for a in case.actions)
            inspections = case.packet_data['maintenance_history_summary']['inspection_results']
            assert bool(inspections) == case.facts.inspection_result_available
            assert case.packet_data['risk_summary']['status_grade'] == case.facts.risk_status


def test_oracle_is_not_visible_in_tool_payloads(benchmark):
    b = benchmark
    for case in b.CASES:
        tools = b.build_tools(case)
        for name in b.T:
            result = tools.call(tool_name=name, identity=b.IDENTITY, retrieved_at=b.NOW)
            serialized = result.model_dump_json()
            assert case.rationale not in serialized
            assert case.id not in serialized
            assert 'acceptable_actions' not in serialized


def test_tool_scoring_accepts_permutation_and_optional_but_counts_duplicates(benchmark):
    b = benchmark
    case = b.CASES[3]
    actual = calls(tuple(reversed(case.required)) + case.optional)
    metrics = b.score(case, actual, case.actions[0])
    assert metrics['tool_path_acceptable']
    assert not metrics['canonical_path_exact']
    duplicate = b.score(case, actual + calls(case.required[:1]), case.actions[0])
    assert duplicate['unnecessary_tool_calls'] == 1
    assert not duplicate['tool_path_acceptable']
    unexpected = b.score(b.CASES[0], calls(b.CASES[0].required + (b.T.GET_PRODUCTION_CONTEXT,)), b.A.REQUEST_INSPECTION)
    assert unexpected['unnecessary_tool_calls'] == 1


def test_unavailable_required_tool_is_missing_and_provider_failure_is_not_abstention_success(benchmark):
    b = benchmark
    case = b.CASES[5]
    unavailable = b.score(case, calls(case.required, 'unavailable'), None)
    assert unavailable['missing_required_tools'] == 1
    assert not unavailable['joint_success']
    failure = b.score(case, [], None, operational_error=True)
    assert not failure['action_acceptable']
    assert not failure['abstain_appropriate']
    assert not failure['joint_success']


def test_abstain_required_optional_and_disallowed(benchmark):
    b = benchmark
    required, optional, disallowed = b.CASES[5], b.CASES[4], b.CASES[0]
    assert b.score(required, calls(required.required), None)['abstain_appropriate']
    assert not b.score(required, calls(required.required), b.A.REVIEW_PLANNED_MAINTENANCE)['abstain_appropriate']
    assert b.score(optional, calls(optional.required), None)['abstain_appropriate']
    assert b.score(optional, calls(optional.required), optional.actions[0])['abstain_appropriate']
    assert not b.score(disallowed, calls(disallowed.required), None)['abstain_appropriate']


def test_deterministic_uses_measurement_signal_with_human_boundary(benchmark):
    b = benchmark
    first = b.run(b.CASES[0], 'deterministic', 1)
    transient = b.run(b.CASES[1], 'deterministic', 1)
    assert first['action'] == 'REQUEST_INSPECTION'
    assert transient['action'] == 'REQUEST_ADDITIONAL_DIAGNOSIS'
    assert first['preference_match'] and transient['preference_match']
    assert first['human_approval_required'] and transient['human_approval_required']
    assert first['policy_contained'] and transient['policy_contained']
    assert first['planner_api_calls'] == 0

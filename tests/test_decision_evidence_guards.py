from dataclasses import replace

import pytest
from app.common.llm_contract import ProviderUnavailable

from app.operations.decision_evidence import remaining_tools
from app.operations.decision_llm_planner import StructuredLLMDecisionPlanner
from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_support_agent import ManufacturingDecisionAgent, DecisionAgentRequest
from app.operations.decision_tools import DecisionToolName as T, DecisionToolResult
from tests.test_decision_llm_planner import FakeProvider, tools, packet, IDENTITY, NOW


def request(**changes):
    return DecisionAgentRequest(identity=IDENTITY, actor_role='process_engineer',
        policy_facts=DecisionPolicyFacts(risk_status='warning'), **changes)


def rank():
    return {'recommended_action': 'REQUEST_INSPECTION', 'alternative_actions': [],
        'confidence': 'medium', 'reasoning_summary': 'Human inspection needed', 'abstain_reason': None}


def test_wire_enum_contains_only_remaining_tools_and_empty_set_calls_no_provider():
    class Provider(FakeProvider):
        def generate_json(self, *args, **kwargs):
            self.schema = kwargs['response_schema']
            return super().generate_json(*args, **kwargs)
    p = Provider([{'next_tool': T.GET_INSPECTION_CONTEXT.value, 'reason': 'Missing evidence'}])
    planner = StructuredLLMDecisionPlanner(p)
    params = dict(policy_facts=DecisionPolicyFacts(), allowed_actions=(), results={})
    planner.select_next_tool(**params, available_tools=(T.GET_INSPECTION_CONTEXT,))
    assert p.schema['properties']['next_tool']['enum'] == [T.GET_INSPECTION_CONTEXT.value]
    assert planner.select_next_tool(**params, available_tools=()).next_tool is None
    assert len(p.calls) == 1


def test_repeated_and_premature_choices_fall_back_once_and_are_visible_in_session():
    p = FakeProvider([
        {'next_tool': None, 'reason': 'Stop too early'},
        {'next_tool': T.GET_ASSET_CONDITION.value, 'reason': 'Repeat previously read tool'}, rank()])
    result = ManufacturingDecisionAgent(tools=tools(), planner=StructuredLLMDecisionPlanner(p)).run(request())
    assert [c.tool_name for c in result.session.tool_calls] == [t.value for t in (T.GET_ASSET_CONDITION, T.GET_INSPECTION_CONTEXT)]
    assert result.session.planner_errors == ('premature_stop_missing_context', 'tool_selection_outside_allowlist')
    assert len(p.calls) == 3  # no terminal selection call


@pytest.mark.parametrize('planner_enabled', [False, True])
def test_source_blocker_abstains_without_ranking_and_keeps_evidence(planner_enabled):
    data = packet()
    data['recommendation_blockers'] = ['Two authoritative readings conflict; human reconciliation required']
    p = FakeProvider([{'next_tool': T.GET_ASSET_CONDITION.value, 'reason': 'Read source'}])
    result = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=lambda _: data),
        planner=StructuredLLMDecisionPlanner(p) if planner_enabled else None).run(request())
    assert result.session.proposal.recommended_action is None
    assert result.session.recommendation_gate_reason.startswith('source_requires_human_review:')
    assert result.session.proposal.evidence_refs == ('artifact:ART-001',)
    assert result.session.proposal.human_approval_required
    assert len(result.session.tool_calls) == 1
    assert len(p.calls) == int(planner_enabled)


def test_benign_limitation_does_not_become_a_hard_blocker():
    data = packet(); data['limitations'] = ['Production estimates exclude weekends']
    result = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=lambda _: data)).run(request())
    assert result.session.proposal.recommended_action is not None
    assert result.session.recommendation_gate_reason is None


@pytest.mark.parametrize('budget', [1, 2])
def test_tool_failure_terminates_within_total_budget_including_retry(budget):
    attempts = []
    def fail(_):
        attempts.append(1)
        raise TimeoutError('synthetic timeout')
    result = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=fail), sleep=lambda _: None).run(
        request(max_tool_calls=budget))
    assert len(attempts) == len(result.session.tool_calls) == budget
    assert result.session.proposal.recommended_action is None


def test_missing_required_evidence_at_budget_limit_abstains():
    result = ManufacturingDecisionAgent(tools=tools()).run(request(max_tool_calls=1))
    assert len(result.session.tool_calls) == 1
    assert result.session.proposal.recommended_action is None


def test_http_timeout_fallback_is_observable_and_bounded():
    p = FakeProvider([ProviderUnavailable('synthetic transport timeout'), ProviderUnavailable('synthetic transport timeout'), ProviderUnavailable('synthetic transport timeout')])
    result = ManufacturingDecisionAgent(tools=tools(), planner=StructuredLLMDecisionPlanner(p)).run(request())
    assert len(result.session.planner_errors) == 3
    assert result.session.proposal.recommended_action is not None
    assert len(result.session.tool_calls) == 2


def test_unavailable_result_stops_and_abstains():
    class Unavailable:
        def call(self, **kwargs):
            return DecisionToolResult(tool_name=kwargs['tool_name'], status='unavailable', as_of=NOW,
                                      source_refs=('source:unavailable',))
    result = ManufacturingDecisionAgent(tools=Unavailable()).run(request())
    assert len(result.session.tool_calls) == 1
    assert result.session.proposal.recommended_action is None
    assert result.session.recommendation_gate_reason.startswith('unverified_context:')


def test_source_owned_blocker_survives_fixture_port_projection():
    from tests.test_decision_context_signals import load, IDENTITY as I, NOW as N
    from app.operations.operational_context_ports import FixtureMaintenanceReadinessContextReadPort
    data = load('maintenance-readiness-context-v1.json')
    data['recommendation_blockers'] = ['Source reconciliation required']
    result = FixtureMaintenanceReadinessContextReadPort(context=data, source_ref='fixture:gate').lookup(identity=I, retrieved_at=N)
    assert result.data['recommendation_blockers'] == ['Source reconciliation required']


def test_unknown_signals_are_not_invented_as_a_measurement_requirement():
    result = DecisionToolResult(tool_name=T.GET_ASSET_CONDITION, status='available', as_of=NOW,
        data={'decision_signals': {'trend_severity': 'unknown'}})
    assert remaining_tools(DecisionPolicyFacts(), {T.GET_ASSET_CONDITION: result}) == (T.GET_INSPECTION_CONTEXT,)


@pytest.mark.parametrize('invalid', ['conflict', ['  '], [False]])
def test_malformed_source_blocker_is_a_schema_failure_not_a_recommendation(invalid):
    data = packet(); data['recommendation_blockers'] = invalid
    result = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=lambda _: data)).run(request())
    assert result.session.proposal.recommended_action is None
    assert result.session.tool_calls[0].error_code == 'schema_validation'

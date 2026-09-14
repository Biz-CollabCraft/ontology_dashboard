"""Regression for strict-schema rejection hidden by deterministic fallback."""
import pytest
from app.operations.decision_llm_planner import ToolSelection, ActionRanking, StructuredLLMDecisionPlanner
from app.operations.decision_support_agent import ManufacturingDecisionAgent, DecisionAgentRequest
from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_tools import DecisionToolName as T
from app.operations.decision_support_contract import DecisionAction as A
from tests.test_decision_llm_planner import FakeProvider, tools, IDENTITY


@pytest.mark.parametrize('model', [ToolSelection, ActionRanking])
def test_wire_schema_requires_every_property_including_nullable_fields(model):
    schema = model.model_json_schema()
    assert set(schema['required']) == set(schema['properties'])
    assert schema['additionalProperties'] is False
    assert all('default' not in prop for prop in schema['properties'].values())


def test_llm_tool_choice_is_distinguishable_from_deterministic_fallback():
    provider = FakeProvider([
        {'next_tool': T.GET_INSPECTION_CONTEXT.value, 'reason': 'Inspect measurement requirements first'},
        {'next_tool': T.GET_ASSET_CONDITION.value, 'reason': 'Verify asset context'},
        {'recommended_action': A.REQUEST_ADDITIONAL_DIAGNOSIS.value, 'alternative_actions': [],
         'confidence': 'medium', 'reasoning_summary': 'Additional measurement required', 'abstain_reason': None},
    ])
    result = ManufacturingDecisionAgent(tools=tools(), planner=StructuredLLMDecisionPlanner(provider)).run(
        DecisionAgentRequest(identity=IDENTITY, actor_role='process_engineer',
                             policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert [c.tool_name for c in result.session.tool_calls] == [T.GET_INSPECTION_CONTEXT.value, T.GET_ASSET_CONDITION.value]
    assert result.session.proposal.recommended_action == A.REQUEST_ADDITIONAL_DIAGNOSIS
    assert result.session.proposal.human_approval_required
    assert len(provider.calls) == 3

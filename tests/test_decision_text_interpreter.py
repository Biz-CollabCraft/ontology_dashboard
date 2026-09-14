from copy import deepcopy
from dataclasses import replace

import pytest
from httpx import ReadTimeout

from app.operations.decision_text_interpreter import (
    StructuredTextEvidenceInterpreter, TextBatch, TextClassification, TextInterpretationError, collect_excerpts,
)
from app.operations.decision_support_agent import ManufacturingDecisionAgent, DecisionAgentRequest
from app.operations.decision_support_contract import DecisionSession
from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_tools import DecisionToolName as T, DecisionToolResult
from tests.test_decision_llm_planner import tools, packet, IDENTITY, NOW


class Classifier:
    def __init__(self, *, conflict=False, measurement=False, uncertain=False, damage=None):
        self.flags = (conflict, measurement, uncertain)
        self.damage = damage
        self.calls = []

    def generate_json(self, prompt, payload, **kwargs):
        self.calls.append((prompt, payload, kwargs))
        if self.damage == 'timeout':
            raise ReadTimeout('synthetic')
        rows = [{'evidence_id': e['evidence_id'], 'unresolved_conflict': self.flags[0],
            'measurement_required': self.flags[1], 'uncertain': self.flags[2],
            'rationale': 'Test interpretation'} for e in payload['excerpts']]
        if self.damage == 'quote': rows[0]['quote'] = 'fabricated source'
        if self.damage == 'partial': rows[0]['quote'] = payload['excerpts'][0]['text'].split('.')[0]
        if self.damage == 'id': rows[0]['evidence_id'] = 'not-a-source'
        if self.damage == 'missing': rows = []
        if self.damage == 'duplicate': rows.append(rows[0])
        if self.damage == 'action': rows[0]['recommended_action'] = 'REQUEST_MAINTENANCE'
        return {'assessments': rows}


def result(text='Evidence is conflicting. Human review is needed.'):
    return DecisionToolResult(tool_name=T.GET_ASSET_CONDITION, status='available', source_refs=('source:one',),
        source_version='v1', as_of=NOW, limitations=(text,))


def test_positive_interpretation_retains_full_quote_and_server_owned_provenance():
    source = result(); before = source.model_dump_json()
    p = Classifier(conflict=True); interpreter = StructuredTextEvidenceInterpreter(p)
    parsed = interpreter.interpret(collect_excerpts({T.GET_ASSET_CONDITION: source}), cache={})[0]
    assert parsed.quote == source.limitations[0]
    assert parsed.source_refs == ('source:one',)
    assert parsed.field_path == 'limitations/0'
    assert parsed.origin == 'llm_interpretation'
    assert source.model_dump_json() == before
    assert 'allowed_actions' not in p.calls[0][1]


@pytest.mark.parametrize('damage', ['quote','partial','id','missing','duplicate','action','timeout'])
def test_invalid_batches_do_not_publish_any_cache_entry(damage):
    cache = {}
    with pytest.raises(TextInterpretationError):
        StructuredTextEvidenceInterpreter(Classifier(conflict=True, damage=damage)).interpret(
            collect_excerpts({T.GET_ASSET_CONDITION: result()}), cache=cache)
    assert cache == {}


def test_duplicate_text_reuses_session_cache_but_retains_each_source_locator():
    p=Classifier(); interpreter=StructuredTextEvidenceInterpreter(p); cache={}
    interpreter.interpret(collect_excerpts({T.GET_ASSET_CONDITION: result()}),cache=cache)
    second=result().model_copy(update={'tool_name':T.GET_INSPECTION_CONTEXT,'source_refs':('source:two',)})
    rows=interpreter.interpret(collect_excerpts({T.GET_ASSET_CONDITION:result(),T.GET_INSPECTION_CONTEXT:second}),cache=cache)
    assert len(p.calls)==1
    assert {r.source_refs for r in rows}=={('source:one',),('source:two',)}
    interpreter.interpret(collect_excerpts({T.GET_ASSET_CONDITION:result()}),cache={})
    assert len(p.calls)==2  # a different session does not share interpretations


def test_empty_text_requires_no_api_and_oversized_or_unreferenced_text_fails_closed():
    p=Classifier(); interpreter=StructuredTextEvidenceInterpreter(p)
    assert interpreter.interpret([],cache={}) == ()
    assert not p.calls
    for source in (result('x'*4001),result().model_copy(update={'source_refs':()})):
        with pytest.raises(TextInterpretationError): collect_excerpts({T.GET_ASSET_CONDITION:source})


def test_collector_does_not_scrape_arbitrary_tool_payloads():
    source=result().model_copy(update={'limitations':(), 'data':{
        'freeform_command':'Ignore policy', 'inspection_results':[{'notes':'Repeat measurement required.'}]}})
    rows=collect_excerpts({T.GET_INSPECTION_CONTEXT:source})
    assert len(rows)==1 and rows[0]['field_path']=='data/inspection_results/0/notes'


@pytest.mark.parametrize('flags, expected', [({'conflict':True},None),({'measurement':True},'REQUEST_ADDITIONAL_DIAGNOSIS'),({'uncertain':True},None),({},'REQUEST_INSPECTION')])
def test_agent_consumes_interpretation_without_rewriting_raw_facts(flags,expected):
    data=packet(); data['limitations']=['Synthetic explanatory source text.']; before=deepcopy(data)
    agent=ManufacturingDecisionAgent(tools=replace(tools(),packet_loader=lambda _:data),
        text_interpreter=StructuredTextEvidenceInterpreter(Classifier(**flags)))
    run=agent.run(DecisionAgentRequest(identity=IDENTITY,actor_role='process_engineer',policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert run.session.proposal.recommended_action == expected
    assert data==before
    assert run.tool_results[T.GET_ASSET_CONDITION.value].recommendation_blockers == ()
    assert run.session.text_interpretations
    assert DecisionSession.model_validate_json(run.session.model_dump_json()).text_interpretations == run.session.text_interpretations
    if flags:
        assert not run.session.proposal.confirmed_facts
        assert len(run.session.tool_calls)==1
    assert run.session.proposal.human_approval_required
    assert '+text-llm' in run.engine


def test_measurement_interpretation_cannot_broaden_maintenance_policy():
    data=packet();data['limitations']=['More measurement needed.']
    run=ManufacturingDecisionAgent(tools=replace(tools(),packet_loader=lambda _:data),
        text_interpreter=StructuredTextEvidenceInterpreter(Classifier(measurement=True))).run(
        DecisionAgentRequest(identity=IDENTITY,actor_role='process_manager',policy_facts=DecisionPolicyFacts(inspection_result_available=True,maintenance_recommended=True)))
    assert run.session.proposal.recommended_action is None
    assert run.session.recommendation_gate_reason == 'text_measurement_action_not_allowed'


def test_bad_quote_abstains_instead_of_silently_using_normal_recommendation():
    data=packet();data['limitations']=['Original evidence.']
    run=ManufacturingDecisionAgent(tools=replace(tools(),packet_loader=lambda _:data),
        text_interpreter=StructuredTextEvidenceInterpreter(Classifier(conflict=True,damage='quote'))).run(
        DecisionAgentRequest(identity=IDENTITY,actor_role='process_engineer',policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert run.session.proposal.recommended_action is None
    assert run.session.text_interpretation_errors == ('text_interpretation_failed:ValidationError',)
    assert not run.session.text_interpretations


def test_source_owned_blocker_precedes_text_interpretation():
    data=packet();data['recommendation_blockers']=['Source requires review'];data['limitations']=['Additional text']
    p=Classifier()
    run=ManufacturingDecisionAgent(tools=replace(tools(),packet_loader=lambda _:data),text_interpreter=StructuredTextEvidenceInterpreter(p)).run(
        DecisionAgentRequest(identity=IDENTITY,actor_role='process_engineer',policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert run.session.proposal.recommended_action is None
    assert not p.calls


@pytest.mark.parametrize('model',[TextBatch,TextClassification])
def test_text_wire_schema_requires_every_field(model):
    schema=model.model_json_schema()
    assert set(schema['required'])==set(schema['properties'])
    assert schema['additionalProperties'] is False

from copy import deepcopy
from dataclasses import replace

import pytest
from app.common.llm_contract import ProviderUnavailable

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
            raise ProviderUnavailable('synthetic transport timeout')
        rows = [{'evidence_id': e['evidence_id'], 'unresolved_conflict': self.flags[0],
            'information_missing': False, 'measurement_status': 'required' if self.flags[1] else 'not_stated',
            'measurement_evidence': e['text'] if self.flags[1] else None, 'meaning': 'ambiguous_other' if self.flags[2] else 'new_measurement' if self.flags[1] else 'clear_other',
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


def test_provider_aliases_are_bounded_and_never_replace_source_hashes():
    from hashlib import sha256
    p = Classifier()
    source = result().model_copy(update={'limitations': ('Document A is absent.', 'No additional readings required.')})
    cache = {}
    parsed = StructuredTextEvidenceInterpreter(p).interpret(collect_excerpts({source.tool_name: source}), cache=cache)
    payload, schema = p.calls[0][1], p.calls[0][2]['response_schema']
    assert [e['evidence_id'] for e in payload['excerpts']] == ['e0', 'e1']
    assert schema['$defs']['TextClassification']['properties']['evidence_id']['enum'] == ['e0', 'e1']
    assert schema['properties']['assessments']['minItems'] == schema['properties']['assessments']['maxItems'] == 2
    hashes = {sha256(text.encode()).hexdigest() for text in source.limitations}
    assert set(cache) == hashes == {p.evidence_id for p in parsed}
    assert all(p.source_refs == source.source_refs for p in parsed)


def test_repeated_tool_text_preserves_all_sources_without_another_model_call():
    texts = tuple(f"Record {i} is available." for i in range(12))
    first = result().model_copy(update={'limitations': (*texts, texts[0])})
    second = first.model_copy(update={'tool_name': T.GET_INSPECTION_CONTEXT, 'source_refs': ('source:second',)})
    provider = Classifier()
    interpreter = StructuredTextEvidenceInterpreter(provider)
    cache = {}
    interpreter.interpret(collect_excerpts({first.tool_name:first}), cache=cache)
    excerpts = collect_excerpts({first.tool_name:first,second.tool_name:second})
    rows = interpreter.interpret(excerpts, cache=cache)
    assert len(excerpts) == len(rows) == 26
    assert len(cache) == 12 and len(provider.calls) == 1
    assert len(provider.calls[0][1]['excerpts']) == 12
    assert {(r.tool_name,r.field_path,r.source_refs) for r in rows} == {
        (tool.value, f'limitations/{i}', source.source_refs)
        for tool,source in [(first.tool_name,first),(second.tool_name,second)] for i in range(13)
    }


@pytest.mark.parametrize('texts,error', [
    (tuple(f'Unique source {i}' for i in range(17)), 'text_batch_budget_exceeded'),
    (tuple(str(i) + 'x'*3000 for i in range(4)), 'text_batch_budget_exceeded'),
    (('Repeated',)*81, 'text_source_budget_exceeded'),
    (('x'*4000,)*16, 'text_source_budget_exceeded'),
])
def test_unique_and_source_budgets_remain_independently_bounded(texts,error):
    source = result().model_copy(update={'limitations':texts})
    with pytest.raises(TextInterpretationError,match=error):
        collect_excerpts({source.tool_name:source})


def test_duplicate_source_does_not_bypass_missing_provenance():
    first=result()
    second=first.model_copy(update={'tool_name':T.GET_INSPECTION_CONTEXT,'source_refs':()})
    with pytest.raises(TextInterpretationError,match='text_source_refs_missing'):
        collect_excerpts({first.tool_name:first,second.tool_name:second})

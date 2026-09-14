from dataclasses import replace

import pytest

from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_support_agent import ManufacturingDecisionAgent, DecisionAgentRequest
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter, TextInterpretationError, collect_excerpts
from tests.test_decision_llm_planner import tools, packet, IDENTITY
from tests.test_decision_text_interpreter import result


class AssessmentProvider:
    def __init__(self, status, evidence=None, missing=True):
        self.status, self.evidence, self.missing = status, evidence, missing

    def generate_json(self, prompt, payload, **kwargs):
        return {'assessments': [dict(evidence_id=e['evidence_id'], unresolved_conflict=False,
            information_missing=self.missing, measurement_status=self.status,
            measurement_evidence=self.evidence, meaning='new_measurement' if self.status == 'required' else 'clear_other', rationale='Synthetic classification')
            for e in payload['excerpts']]}


@pytest.mark.parametrize('status', ['not_stated', 'not_required', 'optional'])
def test_missing_information_does_not_trigger_diagnosis(status):
    data = packet()
    data['limitations'] = ['The certificate is absent from the archive.']
    run = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=lambda _: data),
        text_interpreter=StructuredTextEvidenceInterpreter(AssessmentProvider(status))).run(
        DecisionAgentRequest(identity=IDENTITY, actor_role='process_engineer',
            policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert run.session.proposal.recommended_action == 'REQUEST_INSPECTION'
    assert len(run.session.tool_calls) == 2
    assert run.session.text_interpretations[0].information_missing
    assert not run.session.text_interpretations[0].measurement_required
    assert run.session.proposal.human_approval_required


@pytest.mark.parametrize('evidence', [None, '', 'invented measurement instruction'])
def test_required_measurement_without_exact_support_fails_closed(evidence):
    cache = {}
    with pytest.raises(TextInterpretationError):
        StructuredTextEvidenceInterpreter(AssessmentProvider('required', evidence)).interpret(
            collect_excerpts({result().tool_name: result()}), cache=cache)
    assert cache == {}


def test_explicit_required_measurement_is_derived_from_status_and_keeps_support():
    text = 'The certificate is absent. New readings must be collected before assessment.'
    source = result(text)
    support = 'New readings must be collected before assessment.'
    parsed = StructuredTextEvidenceInterpreter(AssessmentProvider('required', support)).interpret(
        collect_excerpts({source.tool_name: source}), cache={})[0]
    assert parsed.measurement_required
    assert parsed.measurement_evidence == support
    assert parsed.quote == text
    assert parsed.information_missing


def test_unclear_requirement_is_human_review_not_a_positive_measurement_claim():
    source = result('It is unclear whether check again means a document review or new readings.')
    parsed = StructuredTextEvidenceInterpreter(AssessmentProvider('unclear', missing=False)).interpret(
        collect_excerpts({source.tool_name: source}), cache={})[0]
    assert parsed.uncertain
    assert not parsed.measurement_required


@pytest.mark.parametrize('meaning,status,expected', [
    ('ambiguous_request', 'not_stated', None),
    ('ambiguous_other', 'not_stated', None),
    ('record_review', 'not_stated', 'REQUEST_INSPECTION'),
    ('record_review', 'required', 'REQUEST_INSPECTION'),
    ('new_measurement', 'required', 'REQUEST_ADDITIONAL_DIAGNOSIS'),
])
def test_meaning_controls_review_and_blocks_record_review_from_measurement(meaning, status, expected):
    text = 'Synthetic source retained for human review.'
    class Provider(AssessmentProvider):
        def generate_json(self, *args, **kwargs):
            result = super().generate_json(*args, **kwargs)
            for row in result['assessments']:
                row['meaning'] = meaning
            return result
    data = packet()
    data['limitations'] = [text]
    run = ManufacturingDecisionAgent(tools=replace(tools(), packet_loader=lambda _: data),
        text_interpreter=StructuredTextEvidenceInterpreter(
            Provider(status, text if status == 'required' else None, missing=False))).run(
        DecisionAgentRequest(identity=IDENTITY, actor_role='process_engineer',
            policy_facts=DecisionPolicyFacts(risk_status='warning')))
    assert run.session.proposal.recommended_action == expected
    assert run.session.proposal.human_approval_required
    assert not run.session.mutation_attempted
    if meaning.startswith('ambiguous'):
        assert run.session.recommendation_gate_reason == 'text_interpretation_requires_human_review'
        assert run.session.text_interpretations[0].quote == text


def test_optional_measurement_quote_is_preserved_without_creating_a_requirement():
    source = result('Another measurement is optional for training.')
    parsed = StructuredTextEvidenceInterpreter(AssessmentProvider('optional', source.limitations[0], missing=False)).interpret(
        collect_excerpts({source.tool_name: source}), cache={})[0]
    assert parsed.measurement_evidence == source.limitations[0]
    assert not parsed.measurement_required
    assert not parsed.uncertain

from copy import deepcopy
import importlib
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    return importlib.import_module('validate_decision_gold')

@pytest.fixture
def data():
    return json.loads((ROOT/'tests/fixtures/decision_gold/v1/candidates.json').read_text())


def test_draft_is_consistent_but_not_releasable(module,data):
    assert module.validate(data)==[]
    errors=module.validate(data,require_review=True)
    assert len(errors)==48
    assert all('pending human review' in e for e in errors)


def test_related_family_cannot_cross_splits(module,data):
    c=data['cases'][0]
    c['split']='evaluation'
    c['content_sha256']=module.content_hash(c)
    assert any('family crosses splits' in e for e in module.validate(data))


def test_approval_cannot_survive_changed_labels(module,data):
    c=data['cases'][0]
    c['review']={'status':'approved','reviewer':'synthetic-test-reviewer','reviewed_at':'2026-09-14T00:00:00+00:00','approved_content_sha256':module.content_hash(c)}
    c['annotation']['rationale']+=' Changed after review.'
    c['content_sha256']=module.content_hash(c)
    assert any('review does not bind' in e for e in module.validate(data))


def test_unresolved_case_cannot_be_released_by_approval_alone(module,data):
    c=next(c for c in data['cases'] if c['annotation']['status']=='unresolved')
    c['review']={'status':'approved','reviewer':'synthetic-test-reviewer','reviewed_at':'2026-09-14T00:00:00+00:00','approved_content_sha256':module.content_hash(c)}
    assert any(e.startswith(c['id']+':') and 'not ready' in e for e in module.validate(data,require_review=True))


def test_duplicate_text_and_ungrounded_quote_are_rejected(module,data):
    data['cases'][1]['source']['text']=data['cases'][0]['source']['text']
    data['cases'][1]['annotation']['supporting_quote']='not in the source'
    assert any('duplicate normalized text' in e for e in module.validate(data))
    assert any('ungrounded' in e for e in module.validate(data))


def test_expected_policy_profiles_match_existing_guard(module):
    from app.operations.decision_policy import DecisionPolicyFacts,DecisionPolicyGuard
    for profile,actions in module.PROFILES.items():
        maintenance=profile=='maintenance_review'
        actual=DecisionPolicyGuard().evaluate(DecisionPolicyFacts(risk_status='warning',inspection_result_available=maintenance,maintenance_recommended=maintenance))
        assert set(actual.allowed_actions)==actions


def test_model_comparison_refuses_unreviewed_gold_before_registration(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    comparison=importlib.import_module('evaluate_decision_model_comparison')
    with pytest.raises(ValueError,match='completed human review'):
        comparison.inputs(ROOT/'tests/fixtures/decision_gold/v1/candidates.json')


def test_model_comparison_uses_only_reviewed_evaluation_split(module,data,tmp_path,monkeypatch):
    # Test-only review metadata; never write these approvals into the real dataset.
    data['cases']=[c for c in data['cases'] if c['annotation']['status']=='proposed']
    for c in data['cases']:
        c['review']={'status':'approved','reviewer':'synthetic-test-reviewer','reviewed_at':'2026-09-14T00:00:00+00:00','approved_content_sha256':module.content_hash(c)}
    path=tmp_path/'reviewed-test-only.json';path.write_text(json.dumps(data))
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    comparison=importlib.import_module('evaluate_decision_model_comparison')
    rows=comparison.inputs(path)
    assert {r['id'] for r in rows}=={c['id'] for c in data['cases'] if c['split']=='evaluation'}
    assert {r['suite'] for r in rows}=={'reviewed_evaluation'}

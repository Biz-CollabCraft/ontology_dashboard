import importlib
from pathlib import Path

import httpx
import pytest


def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    monkeypatch.setenv('LLM_API_KEY', 'synthetic-unit-test-key')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.openai.com/v1')
    monkeypatch.setenv('LLM_MODEL', 'wrong-env-model')
    return importlib.import_module('evaluate_decision_model_comparison')


@pytest.mark.parametrize('model', ['gpt-4o-mini', 'gpt-5.6-luna'])
def test_explicit_model_overrides_environment_and_records_actual_response(monkeypatch, model):
    m = module(monkeypatch)
    sent = []
    def post(self, body):
        sent.append(body)
        return httpx.Response(200, json={'model': model, 'choices': [], 'usage': {}}, request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions'))
    monkeypatch.setattr(m.OpenAICompatibleProvider, '_post_chat_completion', post)
    provider = m.ModelProvider(model)
    provider._post_chat_completion({'model': 'wrong', 'messages': [], 'temperature': 0,
                                    'response_format': {'type': 'json_schema'}})
    assert provider.model == model == sent[0]['model']
    assert provider.events[0]['returned_model'] == model
    if model == 'gpt-5.6-luna':
        assert sent[0]['reasoning_effort'] == 'low'
        assert 'temperature' not in sent[0]
    else:
        assert sent[0]['temperature'] == 0


def test_wrong_returned_model_is_not_counted_as_requested_model(monkeypatch):
    m = module(monkeypatch)
    def post(self, body):
        return httpx.Response(200, json={'model': 'gpt-4o-mini', 'choices': []}, request=httpx.Request('POST', 'https://api.openai.com/v1/chat/completions'))
    monkeypatch.setattr(m.OpenAICompatibleProvider, '_post_chat_completion', post)
    with pytest.raises(ValueError, match='does not match'):
        m.ModelProvider('gpt-5.6-luna')._post_chat_completion({'messages': [], 'response_format': {'type': 'json_schema'}})


def test_explicit_draft_evaluation_excludes_unresolved_without_approving(monkeypatch):
    m = module(monkeypatch)
    dataset = m.ROOT / 'tests/fixtures/decision_gold/v1/candidates.json'
    before = dataset.read_bytes()
    with pytest.raises(ValueError, match='completed human review'):
        m.inputs(dataset)
    cases = m.inputs(dataset, allow_draft=True)
    assert len(cases) == 20
    assert all(c['suite'] == 'draft_evaluation' and c['gold'] is not None for c in cases)
    assert not {'D05-03', 'D05-04', 'H05-03', 'H05-04'} & {c['id'] for c in cases}
    assert dataset.read_bytes() == before
    with pytest.raises(ValueError, match='requires --gold-dataset'):
        m.inputs(allow_draft=True)

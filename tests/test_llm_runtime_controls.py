import httpx
import pytest
from app.infra.llm.provider import OpenAICompatibleProvider


def setup(monkeypatch, model='gpt-5.6-luna'):
    monkeypatch.setenv('LLM_MODEL', model)
    monkeypatch.setenv('LLM_API_KEY', 'synthetic-unit-test-key')
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.openai.com/v1')
    for key in ['LLM_REASONING_EFFORT','LLM_MAX_COMPLETION_TOKENS']:
        monkeypatch.delenv(key, raising=False)


def test_luna_runtime_controls_survive_schema_retry(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setenv('LLM_REASONING_EFFORT', 'low')
    monkeypatch.setenv('LLM_MAX_COMPLETION_TOKENS', '4096')
    sent=[]
    def post(url, *, headers, json, timeout):
        sent.append(dict(json))
        body={'error':'unsupported schema'} if len(sent)==1 else {'choices':[{'message':{'content':'{"ok":true}'}}]}
        return httpx.Response(400 if len(sent)==1 else 200,json=body,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    value=OpenAICompatibleProvider().generate_json('Return JSON',{},response_schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False})
    assert value=={'ok':True}
    assert len(sent)==2
    for body in sent:
        assert body['model']=='gpt-5.6-luna'
        assert body['reasoning_effort']=='low'
        assert body['max_completion_tokens']==4096
        assert 'temperature' not in body
    assert [b['response_format']['type'] for b in sent]==['json_schema','json_object']


def test_optional_controls_do_not_change_unconfigured_model(monkeypatch):
    setup(monkeypatch,'gpt-4o-mini')
    sent=[]
    def post(url, *, headers, json, timeout):
        sent.append(json)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{}'}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    OpenAICompatibleProvider().generate_json('Return JSON',{})
    assert sent[0]['temperature']==0
    assert 'reasoning_effort' not in sent[0] and 'max_completion_tokens' not in sent[0]


@pytest.mark.parametrize('key,value',[('LLM_REASONING_EFFORT','invalid'),('LLM_MAX_COMPLETION_TOKENS','0'),('LLM_MAX_COMPLETION_TOKENS','-1'),('LLM_MAX_COMPLETION_TOKENS','invalid')])
def test_invalid_controls_fail_before_request(monkeypatch,key,value):
    setup(monkeypatch)
    monkeypatch.setenv(key,value)
    with pytest.raises(ValueError):OpenAICompatibleProvider()


@pytest.mark.parametrize('failure', ['timeout', 'status'])
def test_transport_errors_are_normalized_at_adapter_boundary(monkeypatch, failure):
    from app.common.llm_contract import ProviderUnavailable
    setup(monkeypatch)
    def post(url, **kwargs):
        request = httpx.Request('POST', url)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic timeout', request=request)
        return httpx.Response(503, request=request)
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(ProviderUnavailable) as caught:
        OpenAICompatibleProvider().generate_json('test', {})
    assert isinstance(caught.value.__cause__, httpx.HTTPError)


def test_real_adapter_timeout_reaches_text_interpreter_safe_failure(monkeypatch):
    from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter, TextInterpretationError, collect_excerpts
    from tests.test_decision_text_interpreter import result, T
    setup(monkeypatch)
    def post(*args, **kwargs):
        raise httpx.ReadTimeout('injected timeout')
    monkeypatch.setattr(httpx, 'post', post)
    cache = {}
    with pytest.raises(TextInterpretationError):
        StructuredTextEvidenceInterpreter(OpenAICompatibleProvider()).interpret(
            collect_excerpts({T.GET_ASSET_CONDITION: result()}), cache=cache)
    assert cache == {}

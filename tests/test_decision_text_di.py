from types import SimpleNamespace

import pytest

from tests.test_decision_llm_planner import packet, tools, IDENTITY
from tests.test_decision_text_interpreter import Classifier


@pytest.mark.parametrize('enabled,mode',[(False,None),(True,None),(True,'llm')])
def test_dependency_wiring_and_session_readback(monkeypatch,enabled,mode):
    import app.dependencies as deps
    source=packet();source['limitations']=['A repeat measurement is required before assessment.']
    classifier=Classifier(measurement=True)
    original=classifier.generate_json
    def generate(prompt,payload,**kwargs):
        if kwargs['response_schema_name']=='decision_tool_selection':
            return {'next_tool':payload['available_tools'][0],'reason':'Read source'}
        assert kwargs['response_schema_name']=='decision_text_interpretation'
        return original(prompt,payload,**kwargs)
    classifier.generate_json=generate
    class Repository:
        def __init__(self,target):pass
        def capture(self,identity):return self
        def ports(self):return tools().operational_ports
    monkeypatch.setattr(deps,'get_service',lambda:SimpleNamespace(agent_review_packet=lambda *args:source))
    monkeypatch.setattr(deps,'database_target',lambda:'synthetic-test-db')
    monkeypatch.setattr(deps,'OperationalContextRepository',Repository)
    monkeypatch.setattr(deps,'configured_provider',lambda:classifier)
    monkeypatch.setenv('LLM_PROVIDER','openai-compatible' if enabled else 'deterministic')
    monkeypatch.delenv('DECISION_AGENT_PLANNER', raising=False)
    if mode: monkeypatch.setenv('DECISION_AGENT_PLANNER', mode)
    deps.get_decision_session_service.cache_clear()
    try:
        service=deps.get_decision_session_service()
        agent=service.agent_factory(IDENTITY)
        assert (agent.text_interpreter is not None)==enabled
        assert (agent.planner is not None)==(mode=='llm')
        result=service.create(identity=IDENTITY,actor_role='process_engineer')
        session=service.get(decision_session_id=result.session.decision_session_id,identity=IDENTITY)
        assert session == result.session
        assert bool(session.text_interpretations)==enabled
        assert session.proposal.recommended_action == ('REQUEST_ADDITIONAL_DIAGNOSIS' if enabled else 'REQUEST_INSPECTION')
        assert session.proposal.human_approval_required
        schemas = [call[2]['response_schema_name'] for call in classifier.calls]
        if mode is None:
            assert all(name == 'decision_text_interpretation' for name in schemas)

    finally:
        deps.get_decision_session_service.cache_clear()


@pytest.mark.parametrize('mode,provider', [('unsupported', 'openai-compatible'), ('llm', 'offline')])
def test_invalid_planner_configuration_fails_explicitly(monkeypatch, mode, provider):
    import app.dependencies as deps
    monkeypatch.setattr(deps, 'get_service', lambda: SimpleNamespace())
    monkeypatch.setattr(deps, 'database_target', lambda: 'synthetic-test-db')
    monkeypatch.setenv('DECISION_AGENT_PLANNER', mode)
    monkeypatch.setenv('LLM_PROVIDER', provider)
    deps.get_decision_session_service.cache_clear()
    try:
        with pytest.raises(ValueError):
            deps.get_decision_session_service()
    finally:
        deps.get_decision_session_service.cache_clear()

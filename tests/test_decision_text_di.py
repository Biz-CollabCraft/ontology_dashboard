from types import SimpleNamespace

import pytest

from tests.test_decision_llm_planner import packet, tools, IDENTITY
from tests.test_decision_text_interpreter import Classifier


@pytest.mark.parametrize('enabled',[False,True])
def test_dependency_wiring_and_session_readback(monkeypatch,enabled):
    import app.dependencies as deps
    source=packet();source['limitations']=['A repeat measurement is required before assessment.']
    source['snapshot_basis']['event_id'] = IDENTITY.evidence_snapshot_id
    monkeypatch.setattr('app.dependencies.get_maintenance_loop_service', lambda: SimpleNamespace(event_lineage=lambda **kwargs: {}))
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
    monkeypatch.setattr(deps,'get_service',lambda:SimpleNamespace(runtime_agent_review_packet=lambda *args, **kwargs:source))
    monkeypatch.setattr(deps,'database_target',lambda:'synthetic-test-db')
    monkeypatch.setattr(deps,'OperationalContextRepository',Repository)
    monkeypatch.setattr(deps,'configured_provider',lambda:classifier)
    monkeypatch.setenv('LLM_PROVIDER','openai-compatible' if enabled else 'deterministic')
    deps.get_decision_session_service.cache_clear()
    try:
        service=deps.get_decision_session_service()
        agent=service.agent_factory(IDENTITY)
        assert (agent.text_interpreter is not None)==enabled
        result=service.create(identity=IDENTITY,actor_role='process_engineer')
        session=service.get(decision_session_id=result.session.decision_session_id,identity=IDENTITY)
        assert session == result.session
        assert bool(session.text_interpretations)==enabled
        assert session.proposal.recommended_action == ('REQUEST_ADDITIONAL_DIAGNOSIS' if enabled else 'REQUEST_INSPECTION')
        assert session.proposal.human_approval_required
    finally:
        deps.get_decision_session_service.cache_clear()

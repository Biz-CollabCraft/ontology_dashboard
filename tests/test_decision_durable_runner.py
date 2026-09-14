import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import pytest

from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_run_store import DecisionRunBusy, DecisionRunLeaseLost
from app.operations.decision_durable_runner import DurableDecisionRunner
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_tools import DecisionToolFailure, DecisionToolName
from app.operations.decision_retry import RetryFailureKind
from app.operations.decision_session_service import DecisionSessionApplicationService
from tests.test_decision_session_service import IDENTITY, packet, agent_factory
from app.operations.decision_policy import decision_policy_facts_from_packet

@pytest.fixture
def store(tmp_path):
    database = tmp_path / "runs.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(Path("systems/backend/migrations/sqlite/0052_decision_agent_runs.sql").read_text())
    return DecisionRunRepository(database, lease_seconds=0.3)


def request(**kwargs):
    return DecisionAgentRequest(identity=IDENTITY, actor_role="process_engineer", policy_facts=decision_policy_facts_from_packet(packet(IDENTITY)), **kwargs)


def test_parallel_reads_overlap_and_completed_state_survives_new_service(store):
    base = agent_factory(IDENTITY)
    barrier = Barrier(2)
    seen = []
    class Tools:
        def call(self, **kwargs):
            barrier.wait(timeout=5)
            seen.append(kwargs["tool_name"])
            return base.tools.call(**kwargs)
    agent = ManufacturingDecisionAgent(tools=Tools())
    service = DecisionSessionApplicationService(packet, lambda _: agent, store)
    result = service.create(identity=IDENTITY, actor_role="process_engineer", request_id="stable-request", actor_id="u1")
    assert len(seen) == 2
    assert result.session.proposal.recommended_action == "REQUEST_INSPECTION"
    fresh = DecisionSessionApplicationService(packet, lambda _: agent, DecisionRunRepository(store.database))
    assert fresh.create(identity=IDENTITY, actor_role="process_engineer", request_id="stable-request", actor_id="u1") == result
    assert fresh.get(decision_session_id=result.session.decision_session_id, identity=IDENTITY) == result.session
    assert len(seen) == 2
    assert fresh.get(decision_session_id=result.session.decision_session_id, identity=IDENTITY.model_copy(update={"workspace_id":"other"})) is None


def test_claim_scope_busy_expiry_and_old_writer_fencing(store):
    initial = {"result": None}
    _, old = store.claim("DS-test", IDENTITY, "binding", initial)
    with pytest.raises(DecisionRunBusy):
        store.claim("DS-test", IDENTITY, "binding", initial)
    time.sleep(0.35)
    _, new = store.claim("DS-test", IDENTITY, "binding", initial)
    with pytest.raises(DecisionRunLeaseLost):
        store.save("DS-test", IDENTITY, old, initial)
    store.release("DS-test", IDENTITY, old)
    store.save("DS-test", IDENTITY, new, {"result": "saved"})
    assert store.load("DS-test", IDENTITY)["result"] == "saved"
    assert store.load("DS-test", IDENTITY.model_copy(update={"organization_id":"other"})) is None
    with pytest.raises(ValueError, match="changed"):
        store.claim("DS-test", IDENTITY, "different", initial)


@pytest.mark.parametrize("budget,max_calls,expected_calls,expected_action", [(3,5,3,"REQUEST_INSPECTION"),(0,5,2,None),(3,2,2,None),(3,1,1,None)])
def test_retry_is_bounded_and_missing_context_cannot_recommend(store,budget,max_calls,expected_calls,expected_action):
    base=agent_factory(IDENTITY)
    counts={}
    class Tools:
        def call(self, **kwargs):
            tool=kwargs["tool_name"]
            counts[tool]=counts.get(tool,0)+1
            if tool == DecisionToolName.GET_ASSET_CONDITION and counts[tool]==1:
                raise DecisionToolFailure(RetryFailureKind.TIMEOUT,"injected")
            return base.tools.call(**kwargs)
    result=DurableDecisionRunner(ManufacturingDecisionAgent(tools=Tools(),sleep=lambda _:None),store).run(request(retry_budget=budget,max_tool_calls=max_calls),"DS-budget")
    assert len(result.session.tool_calls)==expected_calls
    assert result.session.proposal.recommended_action==expected_action
    assert result.session.retry_budget_remaining==budget-(expected_calls==3)
    assert result.session.proposal.human_approval_required
    assert not result.session.mutation_attempted


def test_completed_sibling_persists_before_other_read_finishes(store):
    from threading import Event
    base=agent_factory(IDENTITY)
    release=Event()
    class Tools:
        def call(self,**kwargs):
            if kwargs["tool_name"]==DecisionToolName.GET_INSPECTION_CONTEXT:
                assert release.wait(5)
            return base.tools.call(**kwargs)
    with ThreadPoolExecutor() as pool:
        future=pool.submit(DurableDecisionRunner(ManufacturingDecisionAgent(tools=Tools()),store).run,request(),"DS-partial")
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                state=store.load("DS-partial",IDENTITY)
                if state and state["results"]:break
                time.sleep(.01)
            assert list(state["results"])==[DecisionToolName.GET_ASSET_CONDITION.value]
            assert state["result"] is None
            # Heartbeat keeps a live worker's lease beyond its original duration.
            time.sleep(.4)
            with pytest.raises(DecisionRunBusy):
                DurableDecisionRunner(base,store).run(request(),"DS-partial")
        finally:
            release.set()
        assert future.result().session.proposal.recommended_action=="REQUEST_INSPECTION"


def test_evidence_contents_change_rejects_reuse(store):
    service=DecisionSessionApplicationService(packet,agent_factory,store)
    service.create(identity=IDENTITY,actor_role="process_engineer",request_id="bound-request")
    def changed(identity):
        value=packet(identity)
        value["limitations"]=["Different evidence under same label"]
        return value
    service.packet_loader=changed
    with pytest.raises(ValueError,match="changed"):
        service.create(identity=IDENTITY,actor_role="process_engineer",request_id="bound-request")


def test_crash_after_interpretation_does_not_repeat_llm(store):
    from tests.test_decision_text_interpreter import Classifier
    from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter
    provider=Classifier(measurement=True)
    base=agent_factory(IDENTITY)
    class Tools:
        def call(self,**kwargs):
            return base.tools.call(**kwargs).model_copy(update={"limitations":("A repeat measurement is required before assessment.",)})
    agent=ManufacturingDecisionAgent(tools=Tools(),text_interpreter=StructuredTextEvidenceInterpreter(provider))
    original=store.save
    def interrupted(*args):
        original(*args)
        if args[-1]["phase"]=="final":
            raise SystemExit("injected process exit after persisted interpretation")
    store.save=interrupted
    with pytest.raises(SystemExit):
        DurableDecisionRunner(agent,store).run(request(),"DS-text")
    calls=len(provider.calls)
    store.save=original
    result=DurableDecisionRunner(agent,store).run(request(),"DS-text")
    assert len(provider.calls)==calls==1
    assert result.session.proposal.recommended_action=="REQUEST_ADDITIONAL_DIAGNOSIS"


def assert_hard_crash_recovery(store, tmp_path):
    """Kill an OS process after one committed result, then resume in a new process."""
    import os
    import subprocess
    import sys
    child=tmp_path / "child.py"
    child.write_text("""
import os,time
from pathlib import Path
from tests.test_decision_durable_runner import request
from tests.test_decision_session_service import IDENTITY,agent_factory
from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_durable_runner import DurableDecisionRunner
from app.operations.decision_support_agent import ManufacturingDecisionAgent
from app.operations.decision_tools import DecisionToolName
base=agent_factory(IDENTITY)
class Tools:
 def call(self,**kwargs):
  tool=kwargs['tool_name']
  with open(Path(os.environ['RUN_MARKERS']) / (tool.value+'.calls'),'a') as f:f.write('attempt\\n')
  if os.environ.get('BLOCK_READ')=='1' and tool==DecisionToolName.GET_INSPECTION_CONTEXT:
   time.sleep(60)
  return base.tools.call(**kwargs)
store=DecisionRunRepository(os.environ['RUN_DATABASE'],lease_seconds=.3)
result=DurableDecisionRunner(ManufacturingDecisionAgent(tools=Tools(),sleep=lambda _:None),store).run(request(),'DS-killed')
Path(os.environ['RUN_MARKERS'],'result.json').write_text(result.model_dump_json())
""")
    env=dict(os.environ,RUN_DATABASE=store.database,RUN_MARKERS=str(tmp_path),BLOCK_READ="1")
    root=Path(__file__).resolve().parents[1]
    env["PYTHONPATH"]=os.pathsep.join([str(root),str(root/'systems/backend'),str(root/'ml/src'),os.environ.get('PYTHONPATH','')])
    process=subprocess.Popen([sys.executable,str(child)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            state=store.load('DS-killed',IDENTITY)
            if state and state['results']:break
            assert process.poll() is None,'child failed before checkpoint'
            time.sleep(.02)
        assert list(state['results'])==[DecisionToolName.GET_ASSET_CONDITION.value]
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill();process.wait(timeout=5)
    time.sleep(.4)
    env['BLOCK_READ']='0'
    assert subprocess.run([sys.executable,str(child)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20).returncode==0
    state=store.load('DS-killed',IDENTITY)
    session=state['result']['session']
    assert session['proposal']['recommended_action']=='REQUEST_INSPECTION'
    assert session['retry_budget_remaining']==2
    assert len(session['tool_calls'])==3
    assert session['tool_calls'][1]['error_code']=='network'
    assert (tmp_path/(DecisionToolName.GET_ASSET_CONDITION.value+'.calls')).read_text().count('attempt')==1
    assert (tmp_path/(DecisionToolName.GET_INSPECTION_CONTEXT.value+'.calls')).read_text().count('attempt')==2
    assert session['proposal']['human_approval_required'] and not session['mutation_attempted']


def test_real_process_kill_sqlite(store,tmp_path):
    assert_hard_crash_recovery(store,tmp_path)


def test_changed_context_or_model_configuration_cannot_resume(store):
    agent=agent_factory(IDENTITY)
    agent.context_fingerprint="context-v1"
    DurableDecisionRunner(agent,store).run(request(),"DS-version")
    agent.context_fingerprint="context-v2"
    with pytest.raises(ValueError,match="changed"):
        DurableDecisionRunner(agent,store).run(request(),"DS-version")


def test_partial_session_read_has_no_positive_proposal(store):
    from app.operations.decision_durable_runner import configuration_binding
    agent=agent_factory(IDENTITY)
    initial={"request":request().model_dump(mode="json"),"created_at":agent.now().isoformat(),
             "calls":[],"budget":3,"result":None}
    store.claim("DS-pending",IDENTITY,"binding",initial)
    service=DecisionSessionApplicationService(packet,agent_factory,store)
    pending=service.get(decision_session_id="DS-pending",identity=IDENTITY)
    assert pending.status=="waiting_for_tool"
    assert pending.proposal is None


def test_same_client_key_different_actor_is_a_separate_run(store):
    service=DecisionSessionApplicationService(packet,agent_factory,store)
    a=service.create(identity=IDENTITY,actor_role="process_engineer",request_id="request-owner",actor_id="one")
    b=service.create(identity=IDENTITY,actor_role="process_engineer",request_id="request-owner",actor_id="two")
    assert a.session.decision_session_id!=b.session.decision_session_id

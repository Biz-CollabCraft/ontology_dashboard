from hashlib import sha256
from pathlib import Path
import time

from app.infra.db.migrations import migrate
from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_session_service import DecisionSessionApplicationService, _packet_binding
from app.operations.decision_durable_runner import DurableDecisionRunner, configuration_binding
from app.operations.decision_policy import decision_policy_facts_from_packet
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_tools import ManufacturingDecisionTools
from tests.test_decision_session_service import IDENTITY, agent_factory, packet


def test_server_owned_supervisor_starts_drains_and_stops():
    from app.operations.decision_worker import DecisionWorkerSupervisor

    supervisor = DecisionWorkerSupervisor(max_workers=1)
    handle = supervisor.submit(lambda: "completed")
    assert handle.future.result(timeout=2) == "completed"
    assert supervisor.snapshot()["worker_id"].startswith("decision-worker-")
    supervisor.stop(wait=True)
    assert supervisor.running is False


def test_enqueue_registers_durable_run_and_worker_completes(tmp_path: Path):
    database = tmp_path / "decision-worker.db"
    migrate(str(database))
    store = DecisionRunRepository(database)

    def agent(identity):
        tools = ManufacturingDecisionTools(packet_loader=packet, operational_ports={})
        return ManufacturingDecisionAgent(tools=tools, sleep=lambda _seconds: None)

    service = DecisionSessionApplicationService(
        packet_loader=packet,
        agent_factory=agent,
        run_store=store,
    )
    session_id, handle, completed = service.enqueue(
        identity=IDENTITY,
        actor_role="process_engineer",
        request_id="async-worker-001",
        actor_id="test-user",
    )
    assert session_id.startswith("DS-")
    assert completed is None
    assert handle is not None
    result = handle.future.result(timeout=10)
    assert result.session.decision_session_id == session_id
    loaded = service.get(decision_session_id=session_id, identity=IDENTITY)
    assert loaded is not None
    assert loaded.proposal.recommended_action is not None
    resumed = service.resume(session_id=session_id, identity=IDENTITY)
    assert resumed is None
    service.stop_workers(wait=True)


def test_fresh_service_resumes_pending_run_for_tenant_scope(tmp_path: Path):
    database = tmp_path / "decision-worker-resume.db"
    migrate(str(database))
    store = DecisionRunRepository(database, lease_seconds=0.1)
    packet_value = packet(IDENTITY)
    agent_value = agent_factory(IDENTITY)
    request = DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=decision_policy_facts_from_packet(packet_value),
    )
    session_id = "DS-pending-resume-001"
    binding = _packet_binding(packet_value)
    initial = DurableDecisionRunner.initial_state(request, evidence_binding=binding)
    initial["created_at"] = agent_value.now().isoformat()
    _, token = store.claim(
        session_id,
        IDENTITY,
        sha256((configuration_binding(agent_value, request) + binding).encode()).hexdigest(),
        initial,
    )
    assert token is not None
    store.release(session_id, IDENTITY, token)

    fresh = DecisionSessionApplicationService(
        packet_loader=packet,
        agent_factory=lambda identity: agent_factory(identity),
        run_store=store,
    )
    fresh.start_resumer(identity_provider=lambda: [IDENTITY], interval_seconds=0.1)
    for _ in range(50):
        loaded = fresh.get(decision_session_id=session_id, identity=IDENTITY)
        if loaded is not None and loaded.proposal is not None:
            break
        time.sleep(0.05)
    assert loaded is not None
    assert loaded.proposal is not None
    fresh.stop_workers(wait=True)

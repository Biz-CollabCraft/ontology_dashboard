from pathlib import Path

from app.infra.db.migrations import migrate
from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_session_service import DecisionSessionApplicationService
from app.operations.decision_support_agent import ManufacturingDecisionAgent
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

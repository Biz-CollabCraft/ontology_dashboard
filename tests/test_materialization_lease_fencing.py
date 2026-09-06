"""A reclaimed worker must not publish or revive a terminal run."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.dependencies import build_manufacturing_service
from app.operations.agent_review_summary_materialization import AgentReviewSummaryMaterializer, summary_key, summary_key_payload
from app.infra.db.operational_decision_support_service import PersistedOperationalDecisionSupportService
from app.operations.operational_decision_brief import DecisionBriefRole
from test_operational_decision_api import IDENTITY
from test_predictive_maintenance_postgresql import postgresql_database

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=['sqlite', 'postgresql'])
def database(request, tmp_path):
    return tmp_path / 'lease.db' if request.param == 'sqlite' else request.getfixturevalue('postgresql_database')


def reservation(service, packet):
    key = summary_key_payload(packet=packet, project_id='manufacturing-demo-project', history_window='24h', provider=None)
    return service.repository.create_agent_review_workflow_run(
        trigger='polling_watcher', status='running', project_id='manufacturing-demo-project',
        asset_id=packet['asset_id'], event_id=key['event_id'], dataset_version_id=key['dataset_version'],
        history_window='24h', summary_key=summary_key(key), source_sha256=key['source_sha256'],
        context_sha256=key['context_sha256'], packet_schema_version=key['packet_schema_version'],
        prompt_version=key['prompt_version'], model_version=key['model_version'],
    )


def publish(service, packet, run_id):
    return AgentReviewSummaryMaterializer(service.repository, None).materialize(
        packet=packet, organization_id='org-ontology-demo', project_id='manufacturing-demo-project',
        workspace_id='manufacturing-demo', history_window='24h', workflow_run_id=run_id, force=True,
    )


def test_summary_publish_and_run_completion_are_atomic(database):
    service = build_manufacturing_service(database, root=ROOT)
    packet = service.agent_review_packet('CNC-S04-L04-01')
    run = reservation(service, packet)
    publish(service, packet, run['workflow_run_id'])
    finished = service.repository.get_agent_review_workflow_run(run['workflow_run_id'])
    assert finished['status'] == 'partial'
    saved = service.repository.get_agent_review_summary(run['summary_key'])
    assert finished['trace']['materialization']['summary_id'] == saved['summary_id']


def test_reclaimed_summary_worker_cannot_overwrite_or_revive(database):
    service = build_manufacturing_service(database, root=ROOT)
    packet = service.agent_review_packet('CNC-S04-L04-01')
    old = reservation(service, packet)
    service.repository.expire_stale_agent_review_workflow_run(
        project_id='manufacturing-demo-project', summary_key=old['summary_key'],
        started_before=(datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
    )
    new = reservation(service, packet)
    publish(service, packet, new['workflow_run_id'])
    before = service.repository.get_agent_review_summary(old['summary_key'])
    with pytest.raises(RuntimeError, match='lease_lost'):
        publish(service, packet, old['workflow_run_id'])
    service.repository.finish_agent_review_workflow_run(old['workflow_run_id'], status='completed')
    assert service.repository.get_agent_review_summary(old['summary_key']) == before
    assert service.repository.get_agent_review_workflow_run(old['workflow_run_id'])['status'] == 'failed'


def test_summary_write_failure_rolls_back_terminal_transition(database, monkeypatch):
    service = build_manufacturing_service(database, root=ROOT)
    packet = service.agent_review_packet('CNC-S04-L04-01')
    run = reservation(service, packet)
    connect = service.repository._connect

    class FailingConnection:
        def __enter__(self):
            self.context = connect()
            self.connection = self.context.__enter__()
            return self
        def __exit__(self, *args):
            return self.context.__exit__(*args)
        def execute(self, sql, *args):
            if 'INSERT INTO agent_review_summaries' in sql:
                raise RuntimeError('injected_summary_write_failure')
            return self.connection.execute(sql, *args)

    with monkeypatch.context() as patch:
        patch.setattr(service.repository, '_connect', FailingConnection)
        with pytest.raises(RuntimeError, match='injected_summary_write_failure'):
            publish(service, packet, run['workflow_run_id'])
    assert service.repository.get_agent_review_workflow_run(run['workflow_run_id'])['status'] == 'running'
    assert service.repository.get_agent_review_summary(run['summary_key']) is None


@pytest.mark.parametrize('late_failure', [False, True])
def test_reclaimed_brief_worker_cannot_publish_or_finish_new_run(database, late_failure):
    kwargs = {'database_url': str(database)} if str(database).startswith('postgresql:') else {'database_path': database}
    service = PersistedOperationalDecisionSupportService(ROOT, **kwargs)
    original = service._agent
    now = datetime.now(timezone.utc)
    newer = {}

    class LateAgent:
        def run(self, **kwargs):
            service._agent = original
            brief, trace = service.materialize(identity=IDENTITY, actor_role=DecisionBriefRole.PROCESS_MANAGER, risk_status='warning', trigger='ui_manual_regeneration', now=now + timedelta(seconds=121))
            newer['brief'] = brief
            if late_failure:
                raise TimeoutError('late worker failed')
            return original(IDENTITY).run(**kwargs)

    service._agent = lambda identity: LateAgent()
    with pytest.raises((RuntimeError, TimeoutError)):
        service.materialize(identity=IDENTITY, actor_role=DecisionBriefRole.PROCESS_MANAGER, risk_status='critical', trigger='ui_manual_regeneration', now=now)
    brief, _ = service.cached_brief(identity=IDENTITY, actor_role=DecisionBriefRole.PROCESS_MANAGER)
    assert brief == newer['brief']
    runs = service.workflow_runs(project_id=IDENTITY.project_id, asset_id=IDENTITY.asset_id, status=None, limit=10)
    assert sorted(r['status'] for r in runs) == ['completed', 'failed']

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.infra.db.migrations import migrate
from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository, planning_context
from app.operations.operational_context_contract import OperationalRequestIdentity
from scripts.build_operational_context_demo_seed import build_seed
from test_predictive_maintenance_postgresql import postgresql_database

@pytest.fixture(params=['sqlite','postgresql'])
def repository(request,tmp_path):
    target=request.getfixturevalue('postgresql_database') if request.param=='postgresql' else str(tmp_path/'contexts.db')
    migrate(target)
    return OperationalContextRepository(target)

@pytest.fixture
def snapshot():
    return ContextSnapshot.model_validate(next(x for x in build_seed() if x['owner_domain']=='production' and '2026-08-01' in x['source_updated_at']))

def identity(s,**updates):
    return OperationalRequestIdentity(organization_id=s.organization_id,project_id=s.project_id,workspace_id=s.workspace_id,asset_id=s.asset_id,evidence_snapshot_id='artifact-1',decision_as_of=s.source_updated_at+timedelta(hours=1)).model_copy(update=updates)

def lookup(r,s,**updates):
    i=identity(s,**updates)
    return r.lookup(s.owner_domain,identity=i,retrieved_at=i.decision_as_of)

def test_idempotency_and_immutable_version(repository,snapshot):
    assert repository.import_snapshots([snapshot])=={'inserted':1,'unchanged':0}
    assert repository.import_snapshots([snapshot])=={'inserted':0,'unchanged':1}
    changed=snapshot.model_copy(update={'source_ref':'different-source'})
    with pytest.raises(ValueError,match='immutable'):repository.import_snapshots([changed])
    assert lookup(repository,snapshot).data==snapshot.payload
    assert 'synthetic_demo_context' in ' '.join(lookup(repository,snapshot).limitations)

def test_scope_and_asof_cannot_leak(repository,snapshot):
    repository.import_snapshots([snapshot])
    for updates in ({'organization_id':'other'},{'project_id':'other'},{'workspace_id':'other'},{'asset_id':'other'},{'decision_as_of':snapshot.source_updated_at-timedelta(seconds=1)},{'decision_as_of':snapshot.valid_to}):
        result=lookup(repository,snapshot,**updates)
        assert result.status.value=='not_connected' and result.data=={}

def test_stale_snapshot_withholds_values(repository,snapshot):
    snapshot=snapshot.model_copy(update={'max_age_seconds':10})
    repository.import_snapshots([snapshot]);r=lookup(repository,snapshot)
    assert r.status.value=='stale' and r.data=={}

def test_latest_eligible_version_and_atomic_import(repository,snapshot):
    repository.import_snapshots([snapshot]);second=snapshot.model_copy(update={'source_version':'new','source_updated_at':snapshot.source_updated_at+timedelta(hours=2)})
    repository.import_snapshots([second]);assert lookup(repository,snapshot).source_version==snapshot.source_version
    assert lookup(repository,snapshot,decision_as_of=snapshot.source_updated_at+timedelta(hours=3)).source_version=='new'
    third=second.model_copy(update={'source_version':'rollback-me'})
    conflict=snapshot.model_copy(update={'source_ref':'changed'})
    with pytest.raises(ValueError):repository.import_snapshots([third,conflict])
    assert lookup(repository,snapshot,decision_as_of=snapshot.source_updated_at+timedelta(hours=3)).source_version=='new'

def test_planning_exact_snapshot_and_missing_values(repository):
    s=ContextSnapshot.model_validate(next(x for x in build_seed() if x['owner_domain']=='planning'))
    repository.import_snapshots([s]);i=identity(s,evidence_snapshot_id=s.evidence_snapshot_id)
    assert planning_context(repository,i)['production_plan']['planned_units']==s.payload['production_plan']['planned_units']
    missing=planning_context(repository,i.model_copy(update={'evidence_snapshot_id':'wrong'}))
    assert missing['production_impact'] is None and 'production_plan' not in missing

def test_validators_reject_scope_time_and_contract(snapshot):
    for update in ({'source_updated_at':datetime(2026,1,1)},{'valid_to':snapshot.valid_from},{'asset_id':'wrong-asset'},{'payload':{'invented':1}}):
        with pytest.raises(Exception):ContextSnapshot.model_validate({**snapshot.model_dump(),**update})


def test_storage_failure_never_falls_back_to_fixture(repository,snapshot,monkeypatch):
    def unavailable(*args,**kwargs):raise RuntimeError('database down')
    monkeypatch.setattr(repository,'_row',unavailable)
    result=lookup(repository,snapshot)
    assert result.status.value=='failed' and result.data=={}


def test_corrupt_snapshot_is_contained(repository,snapshot,monkeypatch):
    repository.import_snapshots([snapshot]);row=dict(repository._row(snapshot.owner_domain,identity(snapshot)))
    row['payload_json']='{"invented":true}'
    monkeypatch.setattr(repository,'_row',lambda *args:row)
    result=lookup(repository,snapshot)
    assert result.status.value=='failed' and result.data=={}


def test_postgresql_rls_without_superuser_bypass(repository,snapshot):
    if not repository.postgres:pytest.skip('PostgreSQL RLS only')
    import uuid,psycopg
    from psycopg import sql
    role='context_reader_'+uuid.uuid4().hex[:10]
    repository.import_snapshots([snapshot])
    with psycopg.connect(repository.database,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN').format(sql.Identifier(role)))
        try:
            admin.execute(sql.SQL('GRANT SELECT ON operational_context_sources, operational_context_bindings TO {}').format(sql.Identifier(role)))
            with admin.transaction():
                admin.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                admin.execute("SELECT set_config('app.organization_id',%s,true)",(snapshot.organization_id,))
                admin.execute("SELECT set_config('app.project_id',%s,true)",(snapshot.project_id,))
                assert admin.execute('SELECT count(*) FROM operational_context_sources').fetchone()[0]==1
                admin.execute("SELECT set_config('app.organization_id','other',true)")
                assert admin.execute('SELECT count(*) FROM operational_context_sources').fetchone()[0]==0
        finally:
            admin.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))


def test_context_version_change_invalidates_brief_cache(repository,snapshot):
    from app.infra.db.operational_decision_support_service import PersistedOperationalDecisionSupportService
    from app.operations.operational_decision_brief import DecisionBriefRole
    target={'database_url':repository.database} if repository.postgres else {'database_path':Path(repository.database)}
    service=PersistedOperationalDecisionSupportService(Path(__file__).resolve().parents[1],**target)
    i=identity(snapshot)
    first=service._cache_key(identity=i,actor_role=DecisionBriefRole.PROCESS_MANAGER)
    repository.import_snapshots([snapshot])
    second=service._cache_key(identity=i,actor_role=DecisionBriefRole.PROCESS_MANAGER)
    assert first!=second


def test_captured_view_is_stable_across_atomic_new_import(repository,snapshot):
    repository.import_snapshots([snapshot])
    i=identity(snapshot)
    captured=repository.capture(i)
    updated=snapshot.model_copy(update={'source_version':'new-owner-version','source_updated_at':snapshot.source_updated_at+timedelta(minutes=30)})
    repository.import_snapshots([updated])
    assert captured.lookup('production',identity=i,retrieved_at=i.decision_as_of).source_version==snapshot.source_version
    assert repository.lookup('production',identity=i,retrieved_at=i.decision_as_of).source_version=='new-owner-version'
    wrong=captured.lookup('production',identity=i.model_copy(update={'workspace_id':'other'}),retrieved_at=i.decision_as_of)
    assert wrong.status.value=='failed' and not wrong.data
    with pytest.raises(RuntimeError,match='read-only'):
        captured.import_snapshots([updated])


def test_evidence_context_change_invalidates_summary_cache():
    from app.operations.agent_review_summary_materialization import _summary_context_sha256
    first = {'evidence_context': {'selected_basis': [{'source_ref': 'owner:v1'}]}}
    second = {'evidence_context': {'selected_basis': [{'source_ref': 'owner:v2'}]}}
    assert _summary_context_sha256(first) != _summary_context_sha256(second)


def test_context_import_during_brief_generation_prevents_publication(repository,snapshot,monkeypatch):
    from types import SimpleNamespace
    from app.infra.db.operational_decision_support_service import PersistedOperationalDecisionSupportService
    from app.operations.operational_decision_brief import DecisionBriefRole
    target={'database_url':repository.database} if repository.postgres else {'database_path':Path(repository.database)}
    service=PersistedOperationalDecisionSupportService(Path(__file__).resolve().parents[1],**target)
    i=identity(snapshot)
    original_agent=service._agent
    def changing_agent(request_identity):
        agent=original_agent(request_identity)
        def run(**kwargs):
            result=agent.run(**kwargs)
            repository.import_snapshots([snapshot])
            return result
        return SimpleNamespace(run=run)
    monkeypatch.setattr(service,'_agent',changing_agent)
    with pytest.raises(RuntimeError,match='context_changed'):
        service.materialize(identity=i,actor_role=DecisionBriefRole.PROCESS_MANAGER,risk_status='warning',trigger='manual_materialization')
    brief,trace=service.cached_brief(identity=i,actor_role=DecisionBriefRole.PROCESS_MANAGER)
    assert brief is None and trace.status=='pending'

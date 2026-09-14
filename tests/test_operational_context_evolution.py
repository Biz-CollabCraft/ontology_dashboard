"""Regression evidence for schema evolution and owner-version/Event identity separation."""
import json
from copy import deepcopy
from datetime import timedelta

import pytest
from pydantic import Field
from app.infra.db.operational_context_repository import (
    ContextSnapshot, MODELS, digest, normalized_times,
)
from app.operations.operational_context_versions import registry, v1
from scripts.build_operational_context_demo_seed import build_seed
from test_operational_context_repository import repository, snapshot, identity, lookup
from test_predictive_maintenance_postgresql import postgresql_database


def counts(repo, sample):
    with repo.connection(sample.organization_id, sample.project_id) as c:
        return tuple(repo.execute(c, f'SELECT count(*) AS n FROM {table}').fetchone()['n']
            for table in ('operational_context_sources','operational_context_bindings'))


def test_one_owner_plan_can_bind_multiple_events_without_fake_source_versions(repository):
    first=ContextSnapshot.model_validate(next(x for x in build_seed() if x['owner_domain']=='planning'))
    raw=first.model_dump(mode='json')
    raw['evidence_snapshot_id'] += ':event-2'
    raw['payload']['event_impact']['event_id']=raw['evidence_snapshot_id']
    raw['payload']['event_impact']['estimated_lost_units']=25
    second=ContextSnapshot.model_validate(raw)
    assert first.source_version==second.source_version
    assert repository.import_snapshots([first,second])=={'inserted':2,'unchanged':0}
    assert counts(repository,first)==(1,2)
    for sample in (first,second):
        i=identity(sample,evidence_snapshot_id=sample.evidence_snapshot_id)
        result=repository.lookup('planning',identity=i,retrieved_at=i.decision_as_of)
        assert result.status.value=='available'
        assert result.data['event_impact']==sample.payload['event_impact']
        assert result.source_version==first.source_version
    assert repository.import_snapshots([first,second])=={'inserted':0,'unchanged':2}


def test_same_owner_version_cannot_change_source_facts_for_a_new_event(repository):
    first=ContextSnapshot.model_validate(next(x for x in build_seed() if x['owner_domain']=='planning'))
    repository.import_snapshots([first])
    raw=first.model_dump(mode='json')
    raw['evidence_snapshot_id'] += ':event-2'
    raw['payload']['event_impact']['event_id']=raw['evidence_snapshot_id']
    raw['payload']['production_plan']['planned_units']+=1
    with pytest.raises(ValueError,match='immutable'):
        repository.import_snapshots([ContextSnapshot.model_validate(raw)])
    assert counts(repository,first)==(1,1)


def test_v1_survives_v3_application_defaults_and_dispatches_by_stored_version(repository,snapshot,monkeypatch):
    repository.import_snapshots([snapshot])
    i=identity(snapshot)
    before=dict(repository._row('production',i))
    class ProductionV3(v1.ProductionDecisionContext):
        optional_owner_note: str | None = Field(default=None)
    # Simulate both application model evolution and availability of a new persisted schema.
    monkeypatch.setitem(MODELS,'production',ProductionV3)
    monkeypatch.setitem(registry.VALIDATORS,('operational-context.production',3),ProductionV3.model_validate)
    result=lookup(repository,snapshot)
    assert result.status.value=='available'
    assert result.data==snapshot.payload and 'optional_owner_note' not in result.data
    assert dict(repository._row('production',i))==before
    upgraded=snapshot.model_copy(update={'source_version':'v3-owner','schema_version':3,
        'source_updated_at':snapshot.source_updated_at+timedelta(minutes=30),
        'payload':{**snapshot.payload,'optional_owner_note':'owner supplied'}})
    repository.import_snapshots([upgraded])
    assert lookup(repository,snapshot).data['optional_owner_note']=='owner supplied'
    earlier=lookup(repository,snapshot,decision_as_of=snapshot.source_updated_at+timedelta(minutes=10))
    assert earlier.status.value=='available' and earlier.data==snapshot.payload
    assert repository.import_snapshots([snapshot])=={'inserted':0,'unchanged':1}


def test_unknown_schema_is_rejected_and_cannot_be_misread(repository,snapshot,monkeypatch):
    with pytest.raises(ValueError,match='unsupported operational schema'):
        ContextSnapshot.model_validate({**snapshot.model_dump(),'schema_version':999})
    repository.import_snapshots([snapshot])
    row=dict(repository._row('production',identity(snapshot)))
    row['schema_version']=999
    monkeypatch.setattr(repository,'_row',lambda *args:row)
    assert lookup(repository,snapshot).status.value=='failed'


def seed_legacy(repo,samples):
    with repo.connection(samples[0].organization_id,samples[0].project_id) as c:
        for sample in samples:
            row=sample.model_dump(mode='json')
            row.pop('schema_id');row.pop('schema_version')
            if sample.owner_domain in MODELS:
                row['payload']=MODELS[sample.owner_domain].model_validate(row['payload']).model_dump(mode='json')
            row=normalized_times(row)
            checksum=digest(row)
            values={k:v for k,v in row.items() if k!='payload'}
            values.update(payload_json=json.dumps(row['payload']),content_sha256=checksum)
            repo.execute(c,f"INSERT INTO operational_context_snapshots ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))


def test_legacy_copy_preserves_originals_and_is_atomic_and_idempotent(repository):
    samples=[ContextSnapshot.model_validate(x) for x in build_seed()]
    seed_legacy(repository,samples)
    scope={k:getattr(samples[0],k) for k in ('organization_id','project_id','workspace_id')}
    with repository.connection(samples[0].organization_id,samples[0].project_id) as c:
        before=[dict(r) for r in repository.execute(c,'SELECT * FROM operational_context_snapshots ORDER BY owner_domain,asset_id,source_version').fetchall()]
    assert repository.migrate_legacy(**scope,allow_demo=True)=={'validated':14,'applied':False}
    assert counts(repository,samples[0])==(0,0)
    assert repository.migrate_legacy(**scope,allow_demo=True,apply=True)=={'validated':14,'applied':True,'inserted':14,'unchanged':0}
    assert repository.migrate_legacy(**scope,allow_demo=True,apply=True)['unchanged']==14
    with repository.connection(samples[0].organization_id,samples[0].project_id) as c:
        after=[dict(r) for r in repository.execute(c,'SELECT * FROM operational_context_snapshots ORDER BY owner_domain,asset_id,source_version').fetchall()]
    assert before==after
    for sample in samples:
        i=identity(sample,evidence_snapshot_id=sample.evidence_snapshot_id or 'unbound')
        assert repository.lookup(sample.owner_domain,identity=i,retrieved_at=i.decision_as_of).status.value=='available'


def test_binding_conflict_rolls_back_other_new_sources_in_same_import(repository,snapshot):
    plan=ContextSnapshot.model_validate(next(x for x in build_seed() if x['owner_domain']=='planning'))
    repository.import_snapshots([plan])
    changed=plan.model_dump(mode='json')
    changed['payload']['event_impact']['estimated_lost_units']+=1
    with pytest.raises(ValueError,match='immutable'):
        repository.import_snapshots([snapshot,ContextSnapshot.model_validate(changed)])
    assert counts(repository,plan)==(1,1)


def test_capture_fingerprint_distinguishes_exact_binding_from_global(repository,snapshot):
    repository.import_snapshots([snapshot])
    i=identity(snapshot)
    before=repository.version_fingerprint(i)
    exact=snapshot.model_copy(update={'evidence_snapshot_id':i.evidence_snapshot_id})
    repository.import_snapshots([exact])
    assert repository.version_fingerprint(i)!=before
    assert counts(repository,snapshot)==(1,2)

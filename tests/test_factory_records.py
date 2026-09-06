import json
from pathlib import Path
from datetime import timedelta
import pytest
from app.operations.factory_records import RecordBundle,import_bundle,read_records
from app.infra.db.operational_context_repository import OperationalContextRepository
from app.infra.db.migrations import migrate
from app.operations.operational_context_contract import OperationalRequestIdentity

@pytest.fixture
def setup(tmp_path):
    root=Path(__file__).resolve().parents[1]
    b=RecordBundle.model_validate_json((root/'docs/eval/standalone-page-2026-09-06/factory-records/manifest.json').read_text())
    target=str(tmp_path/'records.db');migrate(target);r=OperationalContextRepository(target)
    a=b.assets[0];i=OperationalRequestIdentity(organization_id=b.organization_id,project_id=b.project_id,workspace_id=b.workspace_id,asset_id=a.asset_id,evidence_snapshot_id=a.evidence_snapshot_id,decision_as_of=b.generated_at)
    return r,b,i

def read(r,b,i,**kw):
    return read_records(r,identity=i,dataset_version_id=kw.get('dataset',b.dataset_version_id),model_version=kw.get('model',b.assets[0].model_version),asset_ids=[a.asset_id for a in b.assets])

def test_aggregate_raw_records_and_immutable_import(setup):
    r,b,i=setup
    assert import_bundle(r,b)=={'inserted':1,'unchanged':0}
    assert import_bundle(r,b)=={'inserted':0,'unchanged':1}
    v=read(r,b,i)
    assert v['counts']==dict(running=92,stopped=5,maintenance=3,unknown=0)
    assert v['similar_events_30d']==2
    assert len(v['incident_refs'])==2
    assert v['policy']['action_threshold']==0.6
    with pytest.raises(ValueError,match='immutable'):
        import_bundle(r,b.model_copy(update={'source_ref':'changed'}))

@pytest.mark.parametrize('change',[{'workspace_id':'other'},{'project_id':'other'},{'organization_id':'other'},{'evidence_snapshot_id':'wrong'}])
def test_scope_snapshot_isolation(setup,change):
    r,b,i=setup;import_bundle(r,b)
    assert read(r,b,i.model_copy(update=change))['status']=='not_connected'

def test_time_model_dataset_and_coverage(setup):
    r,b,i=setup;import_bundle(r,b)
    assert read(r,b,i,model='wrong')['status']=='not_connected'
    assert read(r,b,i,dataset='wrong')['status']=='not_connected'
    for at in (b.generated_at-timedelta(seconds=1),b.valid_to):
        assert read(r,b,i.model_copy(update={'decision_as_of':at}))['status']=='not_connected'
    raw=b.model_dump(mode='json');raw['bundle_id']='coverage';raw['assets'][0]['history_from']=(b.generated_at-timedelta(days=20)).isoformat();raw['assets'][0]['incidents']=raw['assets'][0]['incidents'][:2]
    import_bundle(r,RecordBundle.model_validate(raw))
    # Newer explicit version takes precedence, incomplete history never becomes zero.
    assert read(r,RecordBundle.model_validate(raw),i)['similar_events_30d'] is None

def test_duplicate_incidents_rejected(setup):
    _,b,_=setup;raw=b.model_dump(mode='json');raw['assets'][0]['incidents']*=2
    with pytest.raises(ValueError,match='duplicate incident'):RecordBundle.model_validate(raw)

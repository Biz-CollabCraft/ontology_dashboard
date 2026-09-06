from datetime import datetime, timedelta, timezone
import pytest
from app.operations.factory_records import RecordBundle,import_bundle,read_records
from app.infra.db.operational_context_repository import OperationalContextRepository
from app.infra.db.migrations import migrate
from app.operations.operational_context_contract import OperationalRequestIdentity

def _record_bundle() -> RecordBundle:
    generated_at = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    assets = []
    for index in range(100):
        if index < 92:
            state = 'running'
        elif index < 97:
            state = 'stopped'
        else:
            state = 'maintenance'
        asset_id = f'CNC-TEST-{index:03d}'
        incidents = []
        if index == 0:
            incidents = [
                {'incident_id': 'INC-1', 'occurred_at': generated_at - timedelta(days=5), 'failure_type': 'tool_wear_failure'},
                {'incident_id': 'INC-2', 'occurred_at': generated_at - timedelta(days=15), 'failure_type': 'tool_wear_failure'},
            ]
        assets.append({
            'asset_id': asset_id,
            'evidence_snapshot_id': f'RESULT#{asset_id}',
            'model_version': 'model-v1',
            'asset_type': 'cnc',
            'failure_type': 'tool_wear_failure',
            'history_from': generated_at - timedelta(days=31),
            'history_through': generated_at,
            'statuses': [{
                'recorded_at': generated_at - timedelta(hours=1),
                'valid_until': generated_at + timedelta(hours=1),
                'state': state,
            }],
            'incidents': incidents,
            'attention_threshold': 0.3,
            'action_threshold': 0.6,
            'policy_version': 'policy-v1',
        })
    return RecordBundle.model_validate({
        'bundle_id': 'factory-record-test-v1',
        'organization_id': 'org-ontology-demo',
        'project_id': 'manufacturing-demo-project',
        'workspace_id': 'manufacturing-demo',
        'dataset_version_id': 'dataset-v1',
        'source_classification': 'synthetic_demo_context',
        'source_ref': 'fixture:test-factory-records',
        'generated_at': generated_at,
        'valid_from': generated_at - timedelta(minutes=1),
        'valid_to': generated_at + timedelta(days=1),
        'assets': assets,
    })


@pytest.fixture
def setup(tmp_path):
    b=_record_bundle()
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
    raw=b.model_dump(mode='json');raw['bundle_id']='zz-coverage';raw['assets'][0]['history_from']=(b.generated_at-timedelta(days=20)).isoformat();raw['assets'][0]['incidents']=raw['assets'][0]['incidents'][:2]
    import_bundle(r,RecordBundle.model_validate(raw))
    # Newer explicit version takes precedence, incomplete history never becomes zero.
    assert read(r,RecordBundle.model_validate(raw),i)['similar_events_30d'] is None

def test_duplicate_incidents_rejected(setup):
    _,b,_=setup;raw=b.model_dump(mode='json');raw['assets'][0]['incidents']*=2
    with pytest.raises(ValueError,match='duplicate incident'):RecordBundle.model_validate(raw)

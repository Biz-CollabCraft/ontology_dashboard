import pytest
from app.infra.db.operational_context_repository import ContextSnapshot


@pytest.fixture
def row():
    source_asset = 'CMP-S04-L02-01'
    snapshot_id = 'RESULT#CMP-S04-L02-01#2026-08-29T23:00:00+09:00'
    targets = [f'CNC-S04-L02-{index:02d}' for index in range(1, 5)]
    orders = []
    wip = []
    edges = []
    for index, target in enumerate(targets, start=1):
        order_id = f'ORDER-{index}'
        operation_id = f'OP-{index}'
        orders.append({
            'order_id': order_id,
            'product_id': 'PRODUCT-A',
            'product_label': '정밀 가공 부품',
            'required_quantity': 100,
            'completed_quantity': 50,
            'due_at': '2026-08-30T09:00:00+09:00',
            'priority': index,
            'operation_id': operation_id,
            'assigned_asset_id': target,
            'relationship_state': 'assumed_demo',
            'source_refs': ['fixture:test-production'],
        })
        wip.append({
            'wip_id': f'WIP-{index}',
            'order_id': order_id,
            'operation_id': operation_id,
            'asset_id': target,
            'quantity': 50,
            'lot_ids': [f'LOT-{index}'],
            'status': 'in_process',
            'relationship_state': 'assumed_demo',
            'source_refs': ['fixture:test-production'],
        })
        edges.append({
            'from_asset_id': source_asset,
            'to_asset_id': target,
            'relation_type': 'SUPPLIES_AIR_TO',
            'source_sha256': f'sha-{index}',
        })
    return {
        'organization_id': 'org-ontology-demo',
        'project_id': 'manufacturing-demo-project',
        'workspace_id': 'manufacturing-demo',
        'asset_id': source_asset,
        'owner_domain': 'production',
        'source_version': 'test-supply-v2',
        'schema_id': 'operational-context.production',
        'schema_version': 2,
        'source_ref': 'fixture:test-supply-production',
        'source_classification': 'synthetic_demo_context',
        'source_updated_at': '2026-08-29T22:50:00+09:00',
        'valid_from': '2026-08-29T22:00:00+09:00',
        'valid_to': '2026-08-30T22:00:00+09:00',
        'max_age_seconds': 86400,
        'evidence_snapshot_id': snapshot_id,
        'payload': {
            'source_classification': 'synthetic_demo_context',
            'production_orders': orders,
            'wip': wip,
            'alternative_resources': [],
            'limitations': ['demo fixture'],
            'supply_basis': {
                'dataset_version_id': 'dataset-v1',
                'evidence_snapshot_id': snapshot_id,
                'edges': edges,
                'assumptions': ['demo supply relation'],
            },
        },
    }

def test_supply_context_preserves_original_asset_ids(row):
    s=ContextSnapshot.model_validate(row)
    assert s.schema_version==2
    assert len({w['asset_id'] for w in s.payload['wip']})==4
    assert all(w['asset_id']!=s.asset_id for w in s.payload['wip'])

@pytest.mark.parametrize('mutation',['snapshot','source','target','legacy'])
def test_supply_scope_guards(row,mutation):
    if mutation=='snapshot':row['evidence_snapshot_id']='wrong'
    if mutation=='source':row['payload']['supply_basis']['edges'][0]['from_asset_id']='other'
    if mutation=='target':row['payload']['production_orders'][0]['assigned_asset_id']='other'
    if mutation=='legacy':
        row['schema_version']=1
        del row['payload']['supply_basis']
    with pytest.raises(ValueError):ContextSnapshot.model_validate(row)

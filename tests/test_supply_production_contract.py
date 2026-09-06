import copy,json
from pathlib import Path
import pytest
from app.infra.db.operational_context_repository import ContextSnapshot

@pytest.fixture
def row():
    return json.loads(Path('docs/eval/standalone-page-2026-09-06/supply-dependency/manifest.json').read_text())[0]

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

"""Export existing demo fixtures as explicitly synthetic, versioned DB seed data."""
import argparse
import json
from pathlib import Path
from app.infra.db.operational_context_repository import ContextSnapshot, MODELS
from app.operations.domain_context_adapters import _FixtureOperationContextAdapter
ROOT=Path(__file__).resolve().parents[1]


def build_seed(organization_id='org-ontology-demo',project_id='manufacturing-demo-project',workspace_id='manufacturing-demo'):
    rows=[]
    files={'production':'operational-decision-context','maintenance_readiness':'maintenance-readiness-context','quality_delivery':'quality-delivery-context'}
    for domain,prefix in files.items():
        for suffix in ('-v1','-evidence-aligned-v1'):
            path=ROOT/'data/fixtures/operation_context'/f'{prefix}{suffix}.json';raw=json.loads(path.read_text());t=raw['temporal_scope']
            data={key:raw[key] for key in MODELS[domain].model_fields if key in raw}
            data['source_classification']='synthetic_demo_context'
            row=dict(organization_id=organization_id,project_id=project_id,workspace_id=workspace_id,asset_id=raw.get('asset_id') or raw['production_orders'][0]['assigned_asset_id'],owner_domain=domain,source_version=t['snapshot_id'],source_ref=str(path.relative_to(ROOT)),source_classification='synthetic_demo_context',source_updated_at=t['generated_at'],valid_from=t['valid_from'],valid_to=t['valid_to'],payload=data)
            rows.append(ContextSnapshot.model_validate(row).model_dump(mode='json'))
    path=ROOT/'data/fixtures/operation_context/production-planning-context-v1.json';raw=json.loads(path.read_text());adapter=_FixtureOperationContextAdapter([raw]);t=raw['temporal_scope']
    for fp in sorted((ROOT/'data/fixtures').glob('GS-*.json')):
        f=json.loads(fp.read_text());observed=f['observation']['timestamp'];asset=f['equipment']['equipment_id']
        data=adapter.operation_context(fixture=f,artifact={'observed_at':observed},project_id=project_id)
        if data is None:continue
        event=f"RESULT#{asset}#{observed}";data['event_impact']['event_id']=event
        row=dict(organization_id=organization_id,project_id=project_id,workspace_id=workspace_id,asset_id=asset,owner_domain='planning',source_version=t['snapshot_id'],source_ref=str(path.relative_to(ROOT)),source_classification='synthetic_demo_context',source_updated_at=t['generated_at'],valid_from=t['valid_from'],valid_to=t['valid_to'],evidence_snapshot_id=event,payload=data)
        rows.append(ContextSnapshot.model_validate(row).model_dump(mode='json'))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--organization-id',default='org-ontology-demo');p.add_argument('--project-id',default='manufacturing-demo-project');p.add_argument('--workspace-id',default='manufacturing-demo')
    args=p.parse_args();rows=build_seed(args.organization_id,args.project_id,args.workspace_id);args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'snapshots':len(rows),'source_classification':'synthetic_demo_context'}))
if __name__=='__main__':main()

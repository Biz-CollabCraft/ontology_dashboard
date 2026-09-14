"""Validate and import immutable source records. No migrations or overwrites."""
import argparse
import json
import os
from pathlib import Path
from app.operations.factory_records import RecordBundle, import_bundle
from app.infra.db.operational_context_repository import OperationalContextRepository

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--organization-id',required=True);p.add_argument('--project-id',required=True);p.add_argument('--workspace-id',required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--allow-demo',action='store_true')
    a=p.parse_args();b=RecordBundle.model_validate_json(a.manifest.read_text())
    if (b.organization_id,b.project_id,b.workspace_id)!=(a.organization_id,a.project_id,a.workspace_id):raise ValueError('target scope mismatch')
    if b.source_classification=='synthetic_demo_context' and (not a.allow_demo or os.getenv('APP_ENV')=='production'):raise ValueError('demo import not permitted')
    result={'validated_assets':len(b.assets),'applied':a.apply}
    if a.apply:
        db=os.environ['ONTOLOGY_DASHBOARD_DATABASE_URL']
        result.update(import_bundle(OperationalContextRepository(db),b))
    print(json.dumps(result))
if __name__=='__main__':main()

"""Validate, preview, then atomically import owner-approved versioned context."""
import argparse
import json
import os
from pathlib import Path
from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository


def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--manifest',type=Path)
    source.add_argument('--legacy',action='store_true',help='Verify and copy scoped legacy DB rows; originals remain intact')
    p.add_argument('--organization-id',required=True)
    p.add_argument('--project-id',required=True)
    p.add_argument('--workspace-id',required=True)
    p.add_argument('--apply',action='store_true',help='Default validates only; never runs migrations automatically')
    p.add_argument('--allow-demo',action='store_true',help='Explicitly permit synthetic seeds outside production')
    args=p.parse_args()
    if args.legacy:
        database=os.environ.get('ONTOLOGY_DASHBOARD_DATABASE_URL') or os.environ.get('ONTOLOGY_DASHBOARD_DB')
        if not database:raise ValueError('set database target through environment')
        allow_demo=args.allow_demo and os.getenv('APP_ENV','').lower()!='production'
        print(json.dumps(OperationalContextRepository(database).migrate_legacy(
            organization_id=args.organization_id,project_id=args.project_id,
            workspace_id=args.workspace_id,apply=args.apply,allow_demo=allow_demo)))
        return
    raw=json.loads(args.manifest.read_text())
    if not isinstance(raw,list):raise ValueError('manifest must be a list of ContextSnapshot objects')
    snapshots=[ContextSnapshot.model_validate(item) for item in raw]
    expected=(args.organization_id,args.project_id,args.workspace_id)
    for s in snapshots:
        if (s.organization_id,s.project_id,s.workspace_id)!=expected:raise ValueError('manifest scope differs from explicit target scope')
        if s.source_classification=='synthetic_demo_context' and (not args.allow_demo or os.getenv('APP_ENV','').lower()=='production'):
            raise ValueError('synthetic demo seeds are not allowed for this import')
    result={'validated':len(snapshots),'applied':False}
    if args.apply:
        database=os.environ.get('ONTOLOGY_DASHBOARD_DATABASE_URL') or os.environ.get('ONTOLOGY_DASHBOARD_DB')
        if not database:raise ValueError('set database target through environment, never credentials in command arguments')
        result.update(OperationalContextRepository(database).import_snapshots(snapshots),applied=True)
    print(json.dumps(result))

if __name__=='__main__':main()

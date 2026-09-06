"""Preview/apply only reviewed Context migrations and explicitly synthetic demo seeds."""
import argparse
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values
from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository, digest
from scripts.build_operational_context_demo_seed import build_seed

ALLOWED_MIGRATIONS = (
    '0049_versioned_operational_context',
    '0050_operational_context_versions_and_bindings',
)
TABLES = ('operational_context_snapshots', 'operational_context_sources', 'operational_context_bindings')


def settings(env_file):
    env = dotenv_values(env_file)
    url = env.get('ONTOLOGY_DASHBOARD_DATABASE_URL')
    if url:
        u = urlsplit(url)
        return url, u.hostname
    values = dict(host=env['ONTOLOGY_DASHBOARD_TEAM_DB_HOST'], port=env['ONTOLOGY_DASHBOARD_TEAM_DB_PORT'],
        dbname=env['ONTOLOGY_DASHBOARD_TEAM_DB_NAME'], user=env['ONTOLOGY_DASHBOARD_TEAM_DB_USER'],
        password=env['ONTOLOGY_DASHBOARD_TEAM_DB_PASSWORD'], sslmode=env.get('ONTOLOGY_DASHBOARD_TEAM_DB_SSLMODE', 'require'))
    return make_conninfo(**values), values['host']


def deploy(*, conninfo, expected_host, actual_host, scope, demo_fixtures=False, apply=False, expected_manifest_sha256=None):
    if actual_host != expected_host:
        raise ValueError('database host differs from explicitly selected target')
    if demo_fixtures and scope != ('org-ontology-demo','manufacturing-demo-project','manufacturing-demo'):
        raise ValueError('built-in synthetic seeds are limited to the explicit manufacturing demo workspace')
    rows = build_seed(*scope) if demo_fixtures else []
    manifest_hash = digest(rows)
    if apply and demo_fixtures and manifest_hash != expected_manifest_sha256:
        raise ValueError('apply requires the exact manifest checksum reviewed in preview')
    snapshots = [ContextSnapshot.model_validate(row) for row in rows]
    # Only SQL placeholder translation is used; this object never opens a connection.
    repository = OperationalContextRepository('postgresql://unused')
    with psycopg.connect(conninfo, connect_timeout=8, row_factory=dict_row) as c:
        if not apply:
            c.execute('SET TRANSACTION READ ONLY')
        c.execute("SET LOCAL lock_timeout='5s'")
        c.execute("SET LOCAL statement_timeout='30s'")
        for key,value in zip(('organization_id','project_id','workspace_id'),scope):
            c.execute("SELECT set_config(%s,%s,true)",('app.'+key,value))
        if apply:
            c.execute("SELECT pg_advisory_xact_lock(hashtext('ontology_dashboard_schema_migrations'))")
        existing = {r['version'] for r in c.execute('SELECT version FROM schema_migrations')}
        files = {p.stem:p for p in (ROOT/'systems/backend/migrations/postgresql').glob('*.sql')}
        pending = sorted(set(files)-existing)
        if set(pending)-set(ALLOWED_MIGRATIONS):
            raise ValueError('unreviewed pending migration; refusing to apply')
        project = c.execute('SELECT id,organization_id,display_name FROM projects WHERE id=%s AND organization_id=%s',(scope[1],scope[0])).fetchone()
        workspace = c.execute('SELECT id FROM workspaces WHERE id=%s AND project_id=%s AND organization_id=%s',(scope[2],scope[1],scope[0])).fetchone()
        if not project or not workspace:
            raise ValueError('target organization/project/workspace does not exist')
        if snapshots:
            assets={s.asset_id for s in snapshots}
            known={r['asset_id'] for r in c.execute('SELECT DISTINCT asset_id FROM pm_result_artifacts WHERE organization_id=%s AND project_id=%s AND workspace_id=%s AND asset_id=ANY(%s)',(*scope,list(assets)))}
            if assets-known:
                raise ValueError('seed references assets absent from selected demo runtime')
        def counts():
            out={}
            for table in TABLES:
                exists=c.execute('SELECT to_regclass(%s) AS name',('public.'+table,)).fetchone()['name']
                out[table]=c.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] if exists else None
            return out
        before=counts()
        if apply and before['operational_context_snapshots'] and before['operational_context_sources'] is None:
            raise ValueError('legacy rows exist; run the verified scoped legacy-copy rollout first')
        proof=dict(observed_at=datetime.now(timezone.utc).isoformat(),target_host=actual_host,
            target_scope=list(scope),project=dict(project),applied=apply,
            pending_migrations=pending,migration_checksums={v:digest(files[v].read_text()) for v in pending},
            manifest_sha256=manifest_hash,manifest_count=len(rows),
            source_classification='synthetic_demo_context' if rows else None,counts_before=before,
            transaction='read_only' if not apply else 'schema_and_seed_one_transaction')
        if apply:
            for version in pending:
                c.execute(files[version].read_text())
                c.execute('INSERT INTO schema_migrations(version) VALUES(%s)',(version,))
            proof['import_result']=repository._import_on_connection(c,snapshots)
            proof['counts_after']=counts()
            proof['migration_recheck']=[v for v in ALLOWED_MIGRATIONS if c.execute('SELECT 1 FROM schema_migrations WHERE version=%s',(v,)).fetchone()]
        c.commit()
        proof['committed']=apply
    return proof


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--env-file',type=Path,required=True)
    p.add_argument('--expected-host',required=True)
    p.add_argument('--organization-id',required=True)
    p.add_argument('--project-id',required=True)
    p.add_argument('--workspace-id',required=True)
    p.add_argument('--demo-fixtures',action='store_true')
    p.add_argument('--expected-manifest-sha256')
    p.add_argument('--apply',action='store_true')
    p.add_argument('--evidence',type=Path,required=True)
    args=p.parse_args()
    conninfo,host=settings(args.env_file)
    proof=deploy(conninfo=conninfo,expected_host=args.expected_host,actual_host=host,
        scope=(args.organization_id,args.project_id,args.workspace_id),demo_fixtures=args.demo_fixtures,
        apply=args.apply,expected_manifest_sha256=args.expected_manifest_sha256)
    args.evidence.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(proof,ensure_ascii=False))

if __name__=='__main__':
    main()

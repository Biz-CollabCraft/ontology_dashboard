import pytest
import psycopg
from scripts.deploy_operational_context import deploy
from app.infra.db.operational_context_repository import OperationalContextRepository
from test_predictive_maintenance_postgresql import postgresql_database

SCOPE=('org-ontology-demo','manufacturing-demo-project','manufacturing-demo')


def test_wrong_host_or_unreviewed_seed_never_connects(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('must not connect before target and manifest validation')
    monkeypatch.setattr(psycopg,'connect',forbidden)
    with pytest.raises(ValueError,match='host'):
        deploy(conninfo='unused',expected_host='expected',actual_host='wrong',scope=SCOPE)
    with pytest.raises(ValueError,match='checksum'):
        deploy(conninfo='unused',expected_host='expected',actual_host='expected',scope=SCOPE,
            demo_fixtures=True,apply=True,expected_manifest_sha256='wrong')


def test_schema_and_seed_failure_roll_back_together(postgresql_database,monkeypatch):
    version='0050_operational_context_versions_and_bindings'
    with psycopg.connect(postgresql_database) as c:
        c.execute('DROP TABLE operational_context_bindings')
        c.execute('DROP TABLE operational_context_sources')
        c.execute('DELETE FROM schema_migrations WHERE version=%s',(version,))
    args=dict(conninfo=postgresql_database,expected_host='local-test',actual_host='local-test',scope=SCOPE)
    preview=deploy(**args)
    assert preview['pending_migrations']==[version] and not preview['committed']
    original=OperationalContextRepository._import_on_connection
    def failed_seed(*args):raise RuntimeError('injected seed write failure')
    monkeypatch.setattr(OperationalContextRepository,'_import_on_connection',failed_seed)
    with pytest.raises(RuntimeError,match='injected'):
        deploy(**args,apply=True)
    with psycopg.connect(postgresql_database) as c:
        assert c.execute("SELECT to_regclass('public.operational_context_sources')").fetchone()[0] is None
        assert c.execute('SELECT version FROM schema_migrations WHERE version=%s',(version,)).fetchone() is None
    monkeypatch.setattr(OperationalContextRepository,'_import_on_connection',original)
    applied=deploy(**args,apply=True)
    assert applied['committed'] and applied['counts_after']['operational_context_sources']==0
    assert deploy(**args)['pending_migrations']==[]


def test_unreviewed_pending_migration_blocks_deployment(postgresql_database):
    with psycopg.connect(postgresql_database) as c:
        c.execute("DELETE FROM schema_migrations WHERE version LIKE '0048_%'")
    with pytest.raises(ValueError,match='unreviewed'):
        deploy(conninfo=postgresql_database,expected_host='local-test',actual_host='local-test',scope=SCOPE)

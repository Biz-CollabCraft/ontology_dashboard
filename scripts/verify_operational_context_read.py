"""Exercise the read API against an isolated local PG database and fixture event.

Uses TEST_POSTGRES_* and the existing disposable test database helper. Never
connects using application DATABASE_URL and never invokes a summary provider.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tests'), str(ROOT/'systems/backend'), str(ROOT)]

from fastapi.testclient import TestClient
from app.dependencies import build_manufacturing_service, get_service, get_identity_service, get_operational_context_repository
from app.infra.db.operational_context_repository import OperationalContextRepository, ContextSnapshot
from app.main import app
from app.operations.operational_context_read import OperationalContextRead
from identity_test_support import build_identity_service
from test_predictive_maintenance_postgresql import postgresql_database
from scripts.build_operational_context_demo_seed import build_seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import os
    if os.environ.get('TEST_POSTGRES_HOST', '127.0.0.1') not in ('127.0.0.1', 'localhost'):
        raise ValueError('proof requires local disposable PostgreSQL')
    database_fixture = postgresql_database.__wrapped__()
    target = next(database_fixture)
    try:
        repository = OperationalContextRepository(target)
        imported = repository.import_snapshots([ContextSnapshot.model_validate(row) for row in build_seed()])
        with tempfile.TemporaryDirectory(prefix='context-read-api-') as temp:
            local = Path(temp)/'auth-and-event.db'
            service = build_manufacturing_service(local, root=ROOT)
            app.dependency_overrides[get_identity_service] = lambda: build_identity_service(local, app_env='test', seed_demo=True)
            app.dependency_overrides[get_service] = lambda: service
            app.dependency_overrides[get_operational_context_repository] = lambda: repository
            asset = 'CNC-S04-L02-03'
            packet = service.agent_review_packet(asset, 'manufacturing-demo-project')
            basis = packet['snapshot_basis']
            params = dict(project_id='manufacturing-demo-project',workspace_id='manufacturing-demo',
                          evidence_snapshot_id=basis['artifact_id'],decision_as_of=basis['observed_at'])
            with TestClient(app) as client:
                assert client.post('/api/auth/login', json={'email':'manager@ontology.local','password':'Manager!2026'}).status_code == 200
                url = f'/api/objects/{asset}/operational-context'
                first = client.get(url, params=params); assert first.status_code == 200
                body = OperationalContextRead.model_validate(first.json()).model_dump(mode='json')
                repeat = client.get(url, params=params); assert repeat.status_code == 200
                assert body['context_fingerprint'] == repeat.json()['context_fingerprint']
                mismatch = client.get(url, params={**params, 'evidence_snapshot_id':'wrong-event'})
                assert mismatch.status_code == 409
                later = client.get(url, params={**params, 'decision_as_of':'2026-08-29T00:00:00+09:00'})
                assert later.status_code == 200
                assert all(not row['context']['data'] for row in later.json()['domains'].values())
                proof = dict(scope='local ASGI HTTP with fixture event and isolated PostgreSQL context; no live provider',
                    imported=imported, api_status=first.status_code, snapshot_mismatch_status=mismatch.status_code,
                    repeat_fingerprint_equal=True, response=body, later_asof_response=later.json())
                args.output.parent.mkdir(parents=True,exist_ok=True)
                args.output.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
                print('API proof saved; 200 read/repeat/later-asof, 409 wrong snapshot; isolated DB cleaned on exit.')
    finally:
        app.dependency_overrides.clear()
        try:
            next(database_fixture)
        except StopIteration:
            pass


if __name__ == '__main__':
    main()

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
import sqlite3

import pytest
from fastapi import HTTPException
from app.operations.runtime_maintenance_read import read_runtime_maintenance
from app.operations.router import _trusted_decision_support_risk
from app.operations.operational_context_contract import OperationalRequestIdentity

class Repo:
    def __init__(self):
        self.c=sqlite3.connect(':memory:'); self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE pm_maintenance_events (maintenance_id TEXT,organization_id TEXT,project_id TEXT,workspace_id TEXT,dataset_version_id TEXT,asset_id TEXT,completed_at TEXT,maintenance_type TEXT);
        CREATE TABLE closed_loop_work_orders (organization_id TEXT,project_id TEXT,workspace_id TEXT,asset_id TEXT,status TEXT,created_at TEXT,updated_at TEXT);''')
    @contextmanager
    def connection(self,*args): yield self.c
    def execute(self,c,sql,args):return c.execute(sql,args)

def test_maintenance_scope_asof_and_mutable_work_order():
    r=Repo();at='2026-08-29T14:00:00+00:00'
    for mid,ds,asset,when in [('before','d','a','2026-08-09T10:00:00+00:00'),('future','d','a','2026-09-01T00:00:00+00:00'),('other','other','a','2026-08-28T00:00:00+00:00'),('other-asset','d','b','2026-08-28T00:00:00+00:00')]:
        r.c.execute('INSERT INTO pm_maintenance_events VALUES (?,?,?,?,?,?,?,?)',(mid,'o','p','w',ds,asset,when,'repair'))
    args=dict(organization_id='o',project_id='p',workspace_id='w',dataset_version_id='d',asset_id='a',observed_at=at)
    context,history=read_runtime_maintenance(r,**args)
    assert context=={'last_maintenance_days_ago':20,'similar_events_30d':None,'open_work_order_exists':False}
    assert [x['source'] for x in history]==['maintenance:before']
    r.c.execute('INSERT INTO closed_loop_work_orders VALUES (?,?,?,?,?,?,?)',('o','p','w','a','completed','2026-08-01T00:00:00+00:00','2026-09-01T00:00:00+00:00'))
    assert read_runtime_maintenance(r,**args)[0]['open_work_order_exists'] is None

def test_runtime_prediction_contract_identity_fallback(monkeypatch):
    from app.operations import router
    at=datetime(2026,8,29,14,tzinfo=timezone.utc)
    item=SimpleNamespace(asset_id='a',artifact_id='result-a',observed_at=at,status_grade='warning',provenance=SimpleNamespace(result_artifact_id='result-a'))
    monkeypatch.setattr(router,'_runtime_event_id',lambda x:x.artifact_id)
    monkeypatch.setattr(router,'get_predictive_maintenance_runtime_service',lambda:SimpleNamespace(latest_results=lambda **kw:SimpleNamespace(items=[item])))
    def missing(*args,**kwargs):raise KeyError('not a producer artifact')
    service=SimpleNamespace(runtime_agent_review_packet=missing)
    identity=OperationalRequestIdentity(organization_id='o',project_id='p',workspace_id='manufacturing-demo',asset_id='a',evidence_snapshot_id='result-a',decision_as_of=at)
    assert _trusted_decision_support_risk(identity,service)=='warning'
    with pytest.raises(HTTPException) as err:_trusted_decision_support_risk(identity.model_copy(update={'evidence_snapshot_id':'wrong'}),service)
    assert err.value.status_code==409

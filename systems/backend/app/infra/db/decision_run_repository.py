"""Scoped SQLite/PostgreSQL state with fenced leases and database-clock expiry."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from uuid import uuid4
from app.infra.db.connection import tenant_connection
from app.operations.decision_run_store import DecisionRunBusy, DecisionRunLeaseLost

class DecisionRunRepository:
    def __init__(self, database, *, lease_seconds=30):
        self.database=str(database)
        self.postgres=self.database.startswith(("postgresql://","postgresql+psycopg://"))
        if not 0 < lease_seconds <= 3600: raise ValueError("invalid decision run lease duration")
        self.lease_seconds=float(lease_seconds)

    @contextmanager
    def connection(self, identity):
        if self.postgres:
            with tenant_connection(self.database.replace('postgresql+psycopg://','postgresql://',1),identity.organization_id,project_id=identity.project_id) as c: yield c
        else:
            with sqlite3.connect(self.database.removeprefix('sqlite:///'),timeout=30) as c:
                c.row_factory=sqlite3.Row
                c.execute('BEGIN IMMEDIATE')
                yield c

    def execute(self,c,query,params=()):
        return c.execute(query.replace('?','%s') if self.postgres else query,params)

    def clock(self,c):
        query="SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now" if self.postgres else "SELECT (julianday('now')-2440587.5)*86400.0 AS now"
        return float(c.execute(query).fetchone()['now'])

    def scope(self,session_id,identity):
        digest=hashlib.sha256(identity.model_dump_json().encode()).hexdigest()
        return (session_id,identity.organization_id,identity.project_id,digest)

    def load(self,session_id,identity):
        with self.connection(identity) as c:
            row=self.execute(c,'SELECT state_json FROM decision_agent_runs WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=?',self.scope(session_id,identity)).fetchone()
            return json.loads(row['state_json']) if row else None

    def claim(self,session_id,identity,binding,initial):
        scope=self.scope(session_id,identity)
        with self.connection(identity) as c:
            now=self.clock(c)
            self.execute(c,'INSERT INTO decision_agent_runs (decision_session_id,organization_id,project_id,identity_hash,binding,state_json,updated_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',(*scope,binding,json.dumps(initial,ensure_ascii=False),now))
            row=self.execute(c,'SELECT binding,state_json FROM decision_agent_runs WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=?',scope).fetchone()
            if row is None:raise ValueError('decision_run_scope_mismatch')
            if row['binding']!=binding:raise ValueError('decision_run_configuration_or_evidence_changed')
            state=json.loads(row['state_json'])
            if state.get('result') is not None:return state,None
            token=uuid4().hex
            cursor=self.execute(c,'UPDATE decision_agent_runs SET lease_owner=?,lease_until=?,updated_at=? WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=? AND (lease_owner IS NULL OR lease_until<=?)',(token,now+self.lease_seconds,now,*scope,now))
            if cursor.rowcount!=1:raise DecisionRunBusy('decision_run_in_progress')
            # Read after fencing: an earlier owner may have saved just before lease acquisition.
            state=json.loads(self.execute(c,'SELECT state_json FROM decision_agent_runs WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=?',scope).fetchone()['state_json'])
            return state,token

    def save(self,session_id,identity,token,state):
        payload=json.dumps(state,ensure_ascii=False)
        if len(payload.encode())>4_000_000:raise ValueError('decision_run_state_budget_exceeded')
        with self.connection(identity) as c:
            now=self.clock(c)
            cursor=self.execute(c,'UPDATE decision_agent_runs SET state_json=?,updated_at=? WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=? AND lease_owner=? AND lease_until>?',(payload,now,*self.scope(session_id,identity),token,now))
            if cursor.rowcount!=1:raise DecisionRunLeaseLost('decision_run_lease_lost')

    def heartbeat(self,session_id,identity,token):
        with self.connection(identity) as c:
            now=self.clock(c)
            cursor=self.execute(c,'UPDATE decision_agent_runs SET lease_until=?,updated_at=? WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=? AND lease_owner=? AND lease_until>?',(now+self.lease_seconds,now,*self.scope(session_id,identity),token,now))
            if cursor.rowcount!=1:raise DecisionRunLeaseLost('decision_run_lease_lost')

    def release(self,session_id,identity,token):
        with self.connection(identity) as c:
            self.execute(c,'UPDATE decision_agent_runs SET lease_owner=NULL,lease_until=0 WHERE decision_session_id=? AND organization_id=? AND project_id=? AND identity_hash=? AND lease_owner=?',(*self.scope(session_id,identity),token))

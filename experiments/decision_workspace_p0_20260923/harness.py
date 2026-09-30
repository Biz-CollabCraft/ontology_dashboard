#!/usr/bin/env python3
"""Review-gated, synthetic P0 measurements. No measurement runs at import time."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPECTED_HEAD = "891f4567542b4a6d1af7fbef0d2f0f3525f98132"
ADMIN = "postgresql://decision_p0:decision-p0-synthetic-only@127.0.0.1:55434/decision_p0_control"
DB_PREFIX = ADMIN.rsplit("/", 1)[0] + "/"


def validate_dsn(dsn, *, admin=False):
    p = urlsplit(dsn)
    if (p.scheme != "postgresql" or p.hostname != "127.0.0.1" or p.port != 55434
            or p.username != "decision_p0" or p.password != "decision-p0-synthetic-only"
            or p.query or p.fragment):
        raise ValueError("only the isolated synthetic PostgreSQL endpoint is permitted")
    name = p.path.removeprefix("/")
    if admin:
        if dsn != ADMIN:
            raise ValueError("unexpected admin database")
    elif name == "decision_p0_control" or not re.fullmatch(r"decision_p0_[a-z0-9_]+", name):
        raise ValueError("runtime database must be a fresh decision_p0_* database")
    return name


def prepare_environment():
    # Never load .env; inherited provider/DB settings cannot select a real service.
    for key in list(os.environ):
        if key.startswith(("LLM_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "PG")):
            os.environ.pop(key)
    os.environ.update(APP_ENV="test", DATABASE_URL="", ONTOLOGY_DASHBOARD_DB="",
                      ONTOLOGY_DASHBOARD_DB_POOL_ENABLED="false",
                      PGCONNECT_TIMEOUT="5", PGOPTIONS="-c statement_timeout=15000 -c lock_timeout=5000",
                      ONTOLOGY_DASHBOARD_MIGRATION_ROOT=str(ROOT / "systems/backend/migrations"),
                      PYTHONDONTWRITEBYTECODE="1")
    sys.dont_write_bytecode = True
    os.environ.pop("PYTHONOPTIMIZE", None)
    paths = [str(ROOT), str(ROOT / "systems/backend"), str(ROOT / "ml/src"), str(ROOT / "tests")]
    sys.path[:0] = paths
    os.environ["PYTHONPATH"] = os.pathsep.join(paths)


def preflight():
    if sys.flags.optimize:
        raise RuntimeError("optimized Python would disable existing durability assertions")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != EXPECTED_HEAD:
        raise RuntimeError("HEAD differs from reviewed 891f4567")
    if subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=ROOT, capture_output=True).returncode != 1:
        raise RuntimeError("expected detached HEAD")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", ".",
                       ":(exclude)experiments/decision_workspace_p0_20260923"], cwd=ROOT).returncode:
        raise RuntimeError("protected tracked source differs from reviewed HEAD")
    versions = {k: importlib.metadata.version(k) for k in ("langgraph", "psycopg", "fastapi", "httpx", "pytest")}
    if not versions["langgraph"].startswith("1.2."):
        raise RuntimeError("actual LangGraph 1.2.x is required")
    return {"head": head, "detached": True, "versions": versions, "python": sys.executable}


def source_digest():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    return {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if p and (ROOT / p).is_file()}


class Journal:
    def __init__(self, output):
        self.output = output
        self.lock = threading.Lock()
        self.rows = []
        self.start = time.perf_counter()
        self.file = (output / "raw.jsonl").open("x", buffering=1)

    def emit(self, event, **values):
        with self.lock:
            row = dict(seq=len(self.rows), event=event, t=time.perf_counter() - self.start,
                       pid=os.getpid(), thread=threading.get_ident(), **values)
            self.file.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            self.file.flush()
            self.rows.append(row)
        return row

    def require(self, condition, invariant, **values):
        self.emit("invariant", name=invariant, passed=bool(condition), **values)
        if not condition:
            raise AssertionError(invariant)


def deny_external_network():
    original = socket.socket.connect
    def connect(sock, address):
        if not (isinstance(address, tuple) and address[:2] == ("127.0.0.1", 55434)):
            raise RuntimeError("P0 disallows external network connections")
        return original(sock, address)
    socket.socket.connect = connect
    # psycopg uses libpq rather than Python sockets: every harness DSN is separately validated.


def create_database(journal, label):
    import psycopg
    from psycopg import sql
    from app.infra.db.migrations import migrate
    name = "decision_p0_" + label + "_" + uuid4().hex[:12]
    dsn = DB_PREFIX + name
    validate_dsn(dsn)
    validate_dsn(ADMIN, admin=True)
    # The control DB connection executes exactly CREATE DATABASE, no reads/migrations/tests.
    with psycopg.connect(ADMIN, autocommit=True, connect_timeout=5) as control:
        control.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    journal.emit("database_created", database=name)
    os.environ.update(DATABASE_URL=dsn, ONTOLOGY_DASHBOARD_DB=dsn, PGCONNECT_TIMEOUT="5")
    applied = migrate(dsn)
    journal.require("0052_decision_agent_runs" in applied, "durable migration applied", database=name)
    # Nonempty synthetic business records complement the real migrated business tables.
    with psycopg.connect(dsn) as c:
        c.execute("CREATE TABLE p0_synthetic_business (kind text PRIMARY KEY, payload jsonb NOT NULL)")
        for kind in ("work_order", "inspection", "maintenance_action", "outbox"):
            c.execute("INSERT INTO p0_synthetic_business VALUES (%s, %s::jsonb)",
                      (kind, json.dumps({"synthetic": True, "status": "unchanged", "version": 1})))
    return dsn


def business_digest(dsn):
    import psycopg
    from psycopg import sql
    validate_dsn(dsn)
    with psycopg.connect(dsn) as c:
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        c.execute("SET LOCAL row_security = off")
        tables = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        result = {}
        for table in tables:
            if table == "decision_agent_runs":
                continue
            rows = [r[0] for r in c.execute(sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(sql.Identifier(table)))]
            rows = sorted(json.dumps(json.loads(r), sort_keys=True, default=str) for r in rows)
            result[table] = {"rows": len(rows), "sha256": sha256(json.dumps(rows).encode()).hexdigest()}
    return result


def measured_store(dsn, journal, label):
    from app.infra.db.decision_run_repository import DecisionRunRepository
    class MeasuredStore(DecisionRunRepository):
        sid = None
        def claim(self, sid, *args):
            start = time.perf_counter()
            result = super().claim(sid, *args)
            self.sid = sid
            journal.emit("checkpoint_claim", case=label, session=sid, seconds=time.perf_counter()-start,
                         replay=result[1] is None)
            return result

        def save(self, sid, identity, token, state):
            start = time.perf_counter()
            try:
                super().save(sid, identity, token, state)
            except BaseException as exc:
                journal.emit("checkpoint_save_error", case=label, session=sid, phase=state["phase"],
                             seconds=time.perf_counter()-start, error_type=type(exc).__name__)
                raise
            journal.emit("checkpoint_save", case=label, session=sid, phase=state["phase"],
                         seconds=time.perf_counter()-start, results=len(state["results"]),
                         calls=len(state["calls"]), completed=state["result"] is not None)

        def heartbeat(self, sid, identity, token):
            start = time.perf_counter()
            try:
                super().heartbeat(sid, identity, token)
            except BaseException as exc:
                journal.emit("checkpoint_heartbeat_error", case=label, session=sid,
                             seconds=time.perf_counter()-start, error_type=type(exc).__name__)
                raise
            journal.emit("checkpoint_heartbeat", case=label, session=sid,
                         seconds=time.perf_counter()-start)
    return MeasuredStore(dsn, lease_seconds=.9)


def make_http_app(service):
    from fastapi import FastAPI
    from app.operations.router import create_decision_session, get_decision_session
    from app.dependencies import get_decision_session_service, get_service, get_rate_limiter, require_csrf
    from app.infra.rate_limit import InMemoryRateLimiter
    from types import SimpleNamespace
    from tests.test_decision_session_service import IDENTITY
    principal = SimpleNamespace(organization_id=IDENTITY.organization_id, user_id="p0-synthetic",
        is_admin=False, roles=["process_engineer"], active_project_roles=["process_engineer"],
        project_scopes=[IDENTITY.project_id], workspace_scopes=[IDENTITY.workspace_id],
        active_project_id=IDENTITY.project_id)
    app = FastAPI()
    base = "/api/objects/{asset_id}/decision-sessions"
    app.add_api_route(base, create_decision_session, methods=["POST"])
    app.add_api_route(base + "/{decision_session_id}", get_decision_session, methods=["GET"])
    app.dependency_overrides[get_decision_session_service] = lambda: service
    app.dependency_overrides[get_service] = lambda: object()
    limiter = InMemoryRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[require_csrf] = lambda: None
    for route in app.routes:
        for dep in getattr(getattr(route, "dependant", None), "dependencies", []):
            if dep.name == "principal":
                app.dependency_overrides[dep.call] = lambda: principal
    return app


def install_engine_probe(journal):
    # Observe actual Python frames, without replacing runner or LangGraph functions.
    def profile(frame, event, arg):
        if event not in ("call", "return"):
            return
        filename, name = frame.f_code.co_filename.replace("\\", "/"), frame.f_code.co_name
        graph = "/langgraph/" in filename and name in ("invoke", "stream", "compile")
        runner = filename.endswith("/decision_durable_runner.py") and name in ("run", "gather", "interpret", "finalize")
        if graph or runner:
            journal.emit("engine_frame", edge=event, function=name, file=filename)
    sys.setprofile(profile)
    threading.setprofile(profile)


def scenario(dsn, journal, delay, repeat, *, changed=False):
    from fastapi.testclient import TestClient
    from app.operations.decision_session_service import DecisionSessionApplicationService
    from app.operations.decision_support_agent import ManufacturingDecisionAgent
    from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter
    from tests.test_decision_session_service import IDENTITY, packet, agent_factory
    label = ("changed" if changed else "slow" if delay == 10 else "normal") + f"_{repeat}"
    baseline = business_digest(dsn)
    journal.emit("business_before", case=label, digest=baseline)
    before = len(journal.rows)
    store = measured_store(dsn, journal, label)
    entered, finished = threading.Event(), threading.Event()
    packet_changed = threading.Event()
    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    counts = {"tool": 0, "interpreter": 0, "provider": 0, "active": 0, "max": 0}
    original_packet = packet(IDENTITY)
    current_packet = deepcopy(original_packet)
    base = agent_factory(IDENTITY)

    class Tools:
        def call(self, **kwargs):
            with lock:
                counts["tool"] += 1
                counts["active"] += 1
                counts["max"] = max(counts["max"], counts["active"])
            started = journal.emit("tool_start", case=label, tool=kwargs["tool_name"].value)
            try:
                barrier.wait()
                time.sleep(.05)
                return base.tools.call(**kwargs).model_copy(update={"limitations": ("Synthetic explanatory source text.",)})
            finally:
                journal.emit("tool_end", case=label, tool=kwargs["tool_name"].value,
                             started=started["t"])
                with lock:
                    counts["active"] -= 1

    class Provider:
        def generate_json(self, prompt, payload, **kwargs):
            counts["provider"] += 1
            return {"assessments": [{"evidence_id": e["evidence_id"], "unresolved_conflict": False,
                "measurement_required": False, "uncertain": False, "rationale": "Synthetic P0 classification"}
                for e in payload["excerpts"]]}

    class Interpreter(StructuredTextEvidenceInterpreter):
        def interpret(self, excerpts, *, cache):
            counts["interpreter"] += 1
            start = time.perf_counter()
            journal.emit("interpreter_start", case=label, delay=delay)
            entered.set()
            try:
                if changed and not packet_changed.wait(5):
                    raise AssertionError("packet mutation coordination timed out")
                time.sleep(delay)  # Deliberately synchronous; production scheduling is unchanged.
                return super().interpret(excerpts, cache=cache)
            finally:
                journal.emit("interpreter_end", case=label, seconds=time.perf_counter()-start)
                finished.set()

    agent = ManufacturingDecisionAgent(tools=Tools(), text_interpreter=Interpreter(Provider()))
    service = DecisionSessionApplicationService(lambda _: deepcopy(current_packet), lambda _: agent, store)
    app = make_http_app(service)
    url = f"/api/objects/{IDENTITY.asset_id}/decision-sessions"
    params = dict(project_id=IDENTITY.project_id, workspace_id=IDENTITY.workspace_id,
                  evidence_snapshot_id=IDENTITY.evidence_snapshot_id, decision_as_of=IDENTITY.decision_as_of.isoformat())
    create_params = dict(params, request_id="p0-request-" + label, role="process_engineer")
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        start = time.perf_counter()
        pending = pool.submit(client.post, url, params=create_params)
        journal.require(entered.wait(15), "interpreter entered", case=label)
        if changed:
            current_packet["risk_summary"]["failure_probability"] = .1
            journal.emit("packet_changed", case=label, during_interpretation=not finished.is_set())
            packet_changed.set()
        if delay == 10:
            for index in range(5):
                blocked_at_start = not finished.is_set()
                t = time.perf_counter()
                response = client.get(url + "/" + store.sid, params=params)
                seconds = time.perf_counter() - t
                blocked_at_end = not finished.is_set()
                journal.emit("concurrent_get", case=label, index=index, seconds=seconds,
                             status=response.status_code, blocked_at_start=blocked_at_start,
                             blocked_at_end=blocked_at_end)
                journal.require(blocked_at_start and blocked_at_end, "GET completed during synchronous interpretation", case=label)
                journal.require(response.status_code == 200 and response.json()["session"]["proposal"] is None,
                                "pending GET has no positive publication", case=label)
                time.sleep(.1)
        response = pending.result(timeout=30)
        detail = None
        if response.status_code != 200:
            try:
                detail = str(response.json().get("detail"))[:500]
            except Exception:
                detail = "non-json error response"
        journal.emit("http_create", case=label, seconds=time.perf_counter()-start,
                     status=response.status_code, detail=detail)
        if changed:
            journal.require(response.status_code == 409 and response.json()["detail"] == "decision_session_context_changed",
                            "changed packet rejects POST publication", case=label)
            fresh = DecisionSessionApplicationService(lambda _: deepcopy(current_packet), lambda _: agent, store)
            from app.dependencies import get_decision_session_service
            app.dependency_overrides[get_decision_session_service] = lambda: fresh
            read = client.get(url + "/" + store.sid, params=params)
            journal.require(read.status_code == 409, "changed packet rejects fresh-service GET publication", case=label)
            journal.require(not service._sessions and not fresh._sessions, "changed packet not published in memory", case=label)
            old_counts = dict(counts)
            replay = client.post(url, params=create_params)
            journal.require(replay.status_code == 409 and counts == old_counts,
                            "changed packet replay rejected without additional work", case=label)
        else:
            journal.require(response.status_code == 200, "POST completed", case=label)
            session = response.json()["session"]
            journal.require(session["proposal"]["recommended_action"] == "REQUEST_INSPECTION"
                            and session["proposal"]["human_approval_required"] and not session["mutation_attempted"],
                            "expected bounded positive recommendation", case=label)
            old_counts = dict(counts)
            # Fresh application service and repository: replay cannot depend on service memory.
            from app.dependencies import get_decision_session_service
            replay_store = measured_store(dsn, journal, label)
            fresh = DecisionSessionApplicationService(lambda _: deepcopy(current_packet), lambda _: agent, replay_store)
            app.dependency_overrides[get_decision_session_service] = lambda: fresh
            replay = client.post(url, params=create_params)
            journal.require(replay.status_code == 200 and replay.json() == response.json(), "completed replay identical", case=label)
            delta = {k: counts[k] - old_counts[k] for k in ("tool", "interpreter", "provider")}
            journal.require(all(v == 0 for v in delta.values()), "completed replay zero calls", case=label, delta=delta)

    rows = journal.rows[before:]
    frames = [r for r in rows if r["event"] == "engine_frame" and r["edge"] == "call"]
    journal.require(any("/langgraph/" in r["file"] and r["function"] == "invoke" for r in frames)
                    and {"gather", "interpret", "finalize"} <= {r["function"] for r in frames},
                    "actual LangGraph invoke and durable stages observed", case=label)
    journal.require(counts["tool"] == 2 and counts["interpreter"] == counts["provider"] == 1
                    and counts["max"] == 2, "actual bounded parallelism and call counts", case=label, counts=counts)
    intervals = [(r["started"], r["t"]) for r in rows if r["event"] == "tool_end"]
    overlap = min(b for _, b in intervals) - max(a for a, _ in intervals)
    journal.require(overlap > 0, "parallel tool intervals overlap", case=label, overlap_seconds=overlap)
    saves = [r for r in rows if r["event"] == "checkpoint_save"]
    journal.require({"gather", "interpret", "final", "completed"} <= {r["phase"] for r in saves},
                    "all checkpoint stages persisted", case=label)
    journal.require(current_packet == original_packet if not changed else
                    current_packet == {**original_packet, "risk_summary": {**original_packet["risk_summary"], "failure_probability": .1}},
                    "synthetic source unchanged except deliberate packet change", case=label)
    after = business_digest(dsn)
    journal.require(after == baseline, "protected business state digest unchanged", case=label, digest=after)
    journal.emit("case_complete", case=label, delay=delay, repeat=repeat, counts=counts,
                 overlap_seconds=overlap, checkpoint_seconds=sum(r["seconds"] for r in saves))
    spans = {}
    for row in rows:
        if row["event"] != "engine_frame" or not row["file"].endswith("/decision_durable_runner.py"):
            continue
        key = (row["thread"], row["function"])
        if row["edge"] == "call":
            spans[key] = row["t"]
        elif key in spans:
            journal.emit("stage_timing", case=label, stage=row["function"], seconds=row["t"]-spans.pop(key))


def recovery_and_fencing(journal):
    from app.infra.db.decision_run_repository import DecisionRunRepository
    from tests.test_decision_durable_runner import assert_hard_crash_recovery, test_claim_scope_busy_expiry_and_old_writer_fencing
    for label, check in (("recovery", assert_hard_crash_recovery), ("fencing", test_claim_scope_busy_expiry_and_old_writer_fencing)):
        dsn = create_database(journal, label)
        baseline = business_digest(dsn)
        store = DecisionRunRepository(dsn, lease_seconds=.3)
        start = time.perf_counter()
        journal.emit("existing_test_start", test=check.__name__, database=validate_dsn(dsn))
        if label == "recovery":
            markers = journal.output / "recovery"
            markers.mkdir()
            check(store, markers)
            for path in sorted(markers.glob("*.calls")):
                journal.emit("recovery_tool_attempts", tool=path.stem, calls=path.read_text().count("attempt"))
        else:
            check(store)
        journal.require(business_digest(dsn) == baseline, "recovery/fencing protected digest unchanged", case=label)
        journal.emit("existing_test_pass", test=check.__name__, seconds=time.perf_counter()-start)


def summarize(journal, status, error=None):
    rows = journal.rows
    summary = {"status": status, "error": error, "completed_cases": [r for r in rows if r["event"] == "case_complete"],
        "concurrent_gets": [r for r in rows if r["event"] == "concurrent_get"],
        "checkpoint_saves": [r for r in rows if r["event"] == "checkpoint_save"],
        "stage_timings": [r for r in rows if r["event"] == "stage_timing"],
        "create_timings": [r for r in rows if r["event"] == "http_create"],
        "interpreter_timings": [r for r in rows if r["event"] == "interpreter_end"],
        "invariants": [r for r in rows if r["event"] == "invariant"],
        "recovery_and_fencing": [r for r in rows if r["event"] == "existing_test_pass"],
        "limitations": ["In-process ASGI HTTP with synthetic auth/CSRF dependencies; no TCP/proxy/browser latency.",
            "Two synthetic read tools rendezvous then sleep 50ms; overlap verifies scheduling, not tool throughput.",
            "All real migrated public tables except decision_agent_runs are digested; most are empty.",
            "Nonempty synthetic business sentinels are additional protection, not live business data.",
            "Checkpoint timing is application-owned PostgreSQL saves, not a LangGraph checkpointer.",
            "Existing recovery test proves fresh-process resume and attempt accounting; no full application restart."]}
    (journal.output / "summary.json").write_text(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="metadata/source preflight only; no DB or measurement")
    parser.add_argument("--parent-authorized", action="store_true", help="run only after parent reviews and authorizes")
    args = parser.parse_args()
    if not args.check and not args.parent_authorized:
        parser.error("measurement is gated: parent review authorization is required")
    prepare_environment()
    metadata = preflight()
    if args.check:
        print(json.dumps({**metadata, "status": "preflight_only", "measurements_run": False}, indent=2))
        return
    output = HERE / "runs" / (time.strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8])
    output.mkdir(parents=True)
    journal = Journal(output)
    baseline = source_digest()
    manifest = {**metadata, "command": sys.argv, "parent_authorized_flag": True,
        "endpoint": "127.0.0.1:55434", "admin_database": "decision_p0_control", "admin_use": "CREATE DATABASE only",
        "repeats": 3, "delays_seconds": [.1, 10], "synthetic_only": True,
        "protected_source_sha256": baseline,
        "harness_sha256": {p.name: sha256(p.read_bytes()).hexdigest() for p in HERE.glob("*.py")},
        "database_cleanup": False, "db_pool_enabled": False,
        "measurement_status": "running"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    status, error = "failed", None
    try:
        deny_external_network()
        install_engine_probe(journal)
        for delay in (.1, 10):
            for repeat in range(1, 4):
                dsn = create_database(journal, f"{'slow' if delay == 10 else 'normal'}_{repeat}")
                scenario(dsn, journal, delay, repeat)
        dsn = create_database(journal, "changed")
        scenario(dsn, journal, .1, 1, changed=True)
        recovery_and_fencing(journal)
        journal.require(source_digest() == baseline, "tracked protected source unchanged")
        status = "passed"
    except BaseException as exc:
        # Record only frame locations and exception types; never arbitrary exception strings or DSNs.
        error = type(exc).__name__
        frames = []
        for frame in traceback.extract_tb(exc.__traceback__):
            path = Path(frame.filename).resolve()
            try:
                filename = str(path.relative_to(ROOT))
            except ValueError:
                filename = path.name
            frames.append({"file": filename, "line": frame.lineno, "function": frame.name})
        journal.emit("run_stopped", error_type=error, traceback=frames)
    finally:
        sys.setprofile(None)
        threading.setprofile(None)
        manifest["measurement_status"] = status
        manifest["databases"] = [r["database"] for r in journal.rows if r["event"] == "database_created"]
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        summarize(journal, status, error)
        journal.file.close()
        print(f"P0 {status}: {output}")
    if status != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Isolated P0 harness. No product code changes. Run only with supervisor authorization."""
from __future__ import annotations
import argparse, contextvars, functools, hashlib, json, os, sys, threading, time, traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
ROOT = Path(__file__).resolve().parents[2]
for rel in ("systems/backend", "packages/backend", "packages/ml_core", ".", "tests"):
    sys.path.insert(0, str(ROOT / rel))
sys.path.insert(0, str(Path(__file__).parent))
REQUEST = contextvars.ContextVar("p0_request", default="unknown")
SCOPE = dict(organization_id="org-ontology-demo", project_id="manufacturing-demo-project", workspace_id="manufacturing-demo")
class Recorder:
    def __init__(self, path):
        self.file = open(path, "x", buffering=1)
        self.lock = threading.Lock()
        self.zero = time.monotonic()
        self.phase = "setup"
        self.measurement_zero = None
        self.hard_stop = threading.Event()
    def emit(self, kind, **values):
        with self.lock:
            self.file.write(json.dumps(dict(kind=kind, monotonic=time.monotonic(), elapsed=time.monotonic()-self.zero, phase=self.phase, request_id=REQUEST.get(), **values), default=str, ensure_ascii=False)+"\n")
    def set_phase(self, phase):
        self.phase = phase
        self.emit("phase", name=phase)
def identity(packet, provider):
    from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload
    payload = summary_key_payload(packet=packet, provider=provider, history_window="24h", **SCOPE)
    return dict(**payload, summary_key=summary_key(payload))
class Provider:
    name = "ontology-p0-test-double"
    def __init__(self, recorder, scenario):
        self.recorder, self.scenario = recorder, scenario
        self.calls = 0
        self.lock = threading.Lock()
        self.started = threading.Event()
    def generate(self, packet):
        from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
        started = time.monotonic()
        with self.lock:
            self.calls += 1
            call_id = self.calls
        elapsed = started - (self.recorder.measurement_zero or started)
        injected = self.scenario == "timeout" and self.recorder.phase == "measurement" and 0 <= elapsed < 60
        delay = 10.0 if self.scenario == "slow" else (min(10.0, 60-elapsed) if injected else .1)
        self.recorder.emit("provider_start", call_id=call_id, expected=identity(packet,self), injected_timeout=injected, delay=delay)
        self.started.set()
        if REQUEST.get().startswith("get"):
            self.recorder.hard_stop.set()
        time.sleep(delay)
        self.recorder.emit("provider", call_id=call_id, start=started, end=time.monotonic(), duration=time.monotonic()-started, expected=identity(packet,self), injected_timeout=injected, result="TimeoutError" if injected else "valid")
        if injected:
            raise TimeoutError("ontology_p0_injected_timeout")
        return dict(compose_deterministic_agent_review_summary(packet), mode="llm")
def instrument(service, rec):
    for name in ("_agent_review_summary_candidates","_runtime_agent_review_packet_for_candidate","runtime_agent_review_packet","cached_agent_review_summary_for_packet","_materialize_agent_review_packet","_materialize_agent_review_packet_now"):
        original = getattr(service, name)
        def build(original, name):
            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                start=time.monotonic()
                packet=kwargs.get("packet")
                expected=identity(packet, service.agent_review_summary_provider) if packet else None
                rec.emit("stage_start", stage=name, start=start, expected=expected)
                try:
                    result=original(*args, **kwargs)
                    details={}
                    if name in ("runtime_agent_review_packet","_runtime_agent_review_packet_for_candidate"):
                        details["expected"]=identity(result, service.agent_review_summary_provider)
                    elif isinstance(result,tuple) and len(result)==2:
                        details["trace"]=result[1]
                    rec.emit("stage", stage=name, start=start, end=time.monotonic(), duration=time.monotonic()-start, result="ok", **details)
                    return result
                except Exception as exc:
                    rec.emit("stage", stage=name, start=start, end=time.monotonic(), duration=time.monotonic()-start, result=type(exc).__name__, error=str(exc))
                    raise
            return wrapped
        setattr(service,name,build(original,name))
def sequence(assets,duration):
    events=[]
    for n,at in enumerate(range(0,duration,5)):
        events.append(dict(at=at,asset_id=assets[n%len(assets)],event_id=f"P0-E{n:04d}",kind="new"))
    # Same identity offered ten times and ten snapshots on one asset.
    for n in range(10):
        events.append(dict(at=35+n*.01,asset_id=assets[0],event_id="P0-EXACT",kind="exact_repeat"))
        events.append(dict(at=75+n*.01,asset_id=assets[0],event_id=f"P0-BURST{n:02d}",kind="burst"))
    # Predetermined event at 5s races with the initial slow scan.
    return sorted(events,key=lambda x:x["at"])
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--database",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--scenario",choices=["normal","slow","timeout"],default="normal")
    p.add_argument("--duration",type=int,default=480)
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--context-probe",action="store_true")
    args=p.parse_args()
    from urllib.parse import urlsplit
    parsed=urlsplit(args.database)
    if parsed.hostname not in ("127.0.0.1","localhost") or parsed.port!=55433 or not parsed.path.startswith("/ontology_p0_"):
        raise SystemExit("Refusing database outside isolated P0 server/name")
    os.environ.update(APP_ENV="test",DATABASE_URL=args.database,ONTOLOGY_DASHBOARD_DB=args.database,FACTORY_SIGNAL_DB=args.database,LLM_PROVIDER="deterministic",LLM_API_KEY="",OPENAI_API_KEY="",ANTHROPIC_API_KEY="",ONTOLOGY_DASHBOARD_REDIS_URL="")
    out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    rec=Recorder(out/"raw.jsonl")
    from fixture import setup,emit,snapshot_business
    fx=setup(args.database,work_dir=out/"fixture")
    from app.dependencies import build_manufacturing_service,get_service
    service=build_manufacturing_service(args.database,root=ROOT)
    provider=Provider(rec,args.scenario)
    service.agent_review_summary_provider=provider
    instrument(service,rec)
    from app.main import app
    from fastapi.testclient import TestClient
    app.dependency_overrides[get_service]=lambda:service
    client=TestClient(app)
    login=client.post("/api/auth/login",json={"email":"manager@ontology.local","password":"Manager!2026"})
    if login.status_code!=200:
        raise RuntimeError(f"login failed: {login.status_code} {login.text}")
    assets=fx["assets"]
    latest={}; latest_lock=threading.Lock()
    base=datetime(2026,9,23,tzinfo=timezone.utc)
    def admission(ev):
        start=time.monotonic()
        spec=dict(ev,observed_at=(base+timedelta(seconds=ev.get("at",0)+1000)).isoformat())
        candidate=emit(args.database,spec)
        with latest_lock: latest[ev["asset_id"]]=candidate
        rec.emit("event",event=ev,expected={**SCOPE,**candidate},start=start,end=time.monotonic(),result="admitted")
        return candidate
    for i,asset in enumerate(assets):
        admission(dict(at=-100+i,asset_id=asset,event_id=f"P0-INITIAL{i}",kind="initial"))
    manifest=dict(preflight=args.preflight,context_probe=args.context_probe,database_role="ontology_p0 synthetic bootstrap superuser",rls_enforcement="not established by this run; policy definitions migrated but superuser bypass",scenario=args.scenario,duration=args.duration,scope=SCOPE,fixture=fx,watcher=dict(interval=60,limit=None,policy="always",max_attempts=2,source="live",sleep="after completion"),provider=dict(normal_delay=.1,slow_delay=10,timeout_window=[0,60],timeout_delay_cap=10,retries="existing workflow max_attempts"),api="FastAPI TestClient in-process HTTP; no network socket",clock="time.monotonic",sequence=sequence(assets,args.duration))
    manifest["sequence_sha256"]=hashlib.sha256(json.dumps(manifest["sequence"],sort_keys=True).encode()).hexdigest()
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,default=str))
    rec.emit("business_snapshot",position="before",data=snapshot_business(args.database))
    def get_one(asset,request_id,due=None):
        REQUEST.set(request_id)
        with latest_lock: expected=dict(latest[asset])
        start=time.monotonic()
        try:
            response=client.get(f"/api/objects/{asset}/agent-review-summary",params=dict(project_id=SCOPE["project_id"],dataset_version_id=expected["dataset_version_id"],event_id=expected["event_id"]))
            body=response.json()
            rec.emit("get",start=start,end=time.monotonic(),duration=time.monotonic()-start,status=response.status_code,due=due,schedule_lag=None if due is None else start-due,expected={**SCOPE,**expected},response=body)
            return body
        except Exception as exc:
            rec.emit("get",start=start,end=time.monotonic(),duration=time.monotonic()-start,status=0,expected={**SCOPE,**expected},error=repr(exc))
            return {}
    from scripts.watch_agent_review_summaries import run_once
    def poll(n):
        REQUEST.set(f"watcher-{n}")
        start=time.monotonic()
        try:
            result=run_once(database="isolated-p0",service=service,project_id=SCOPE["project_id"],history_window="24h",limit=None,max_attempts=2,watch=True,interval_seconds=60,max_iterations=None,stale_policy="summary_key",source="live",require_live_provider=False,generation_policy="always")
            rec.emit("poll",start=start,end=time.monotonic(),duration=time.monotonic()-start,result=result)
            return result
        except Exception as exc:
            rec.emit("poll",start=start,end=time.monotonic(),duration=time.monotonic()-start,error=repr(exc))
            return {}
    rec.set_phase("preflight")
    get_one(assets[0],"get-preflight-miss")
    poll(0)
    hit=get_one(assets[0],"get-preflight-hit")
    if not hit.get("summary") or (hit.get("trace") or {}).get("reuse_eligibility")!="EXACT_VALIDATED":
        rec.emit("preflight_invalid",reason="baseline exact hit not established")
        raise RuntimeError("preflight baseline not exact-ready; no load authorized")
    if args.context_probe:
        from fixture import mutate_context
        asset=assets[0]
        candidate=latest[asset]
        def load_packet():
            return service.runtime_agent_review_packet(asset,SCOPE["project_id"],organization_id=SCOPE["organization_id"],workspace_id=SCOPE["workspace_id"],dataset_version_id=candidate["dataset_version_id"],event_id=candidate["event_id"],history_window="24h")
        original_packet=load_packet()
        before_identity=identity(original_packet,provider)
        rec.emit("probe_initial_storage",expected=before_identity,stored=service.repository.get_agent_review_summary(before_identity["summary_key"]) is not None)
        mutation=mutate_context(args.database,candidate,1)
        packet=load_packet()
        after_identity=identity(packet,provider)
        rec.emit("context_mutation",version=1,before=before_identity,after=after_identity,mutation=mutation,effective=before_identity["summary_key"]!=after_identity["summary_key"])
        if before_identity["summary_key"]==after_identity["summary_key"]:
            raise RuntimeError("ineffective context mutation; cannot claim probe validity")
        get_one(asset,"get-probe-historical")
        provider.scenario="slow"
        provider.started.clear()
        result={}
        def generation():
            REQUEST.set("probe-generation")
            started=time.monotonic()
            try:
                summary,trace=service._materialize_agent_review_packet(packet=packet,history_window="24h",trigger="manual_materialization",engine="simple",packet_loader=load_packet,**SCOPE)
                result.update(summary_present=summary is not None,trace=trace)
            except Exception as exc:
                result.update(error=type(exc).__name__,message=str(exc))
            rec.emit("probe_generation_end",start=started,end=time.monotonic(),duration=time.monotonic()-started,**result)
        worker=threading.Thread(target=generation); worker.start()
        if not provider.started.wait(15):
            raise RuntimeError("provider did not start in context probe")
        time.sleep(.25)
        mutation=mutate_context(args.database,candidate,2)
        newest_identity=identity(load_packet(),provider)
        rec.emit("context_mutation",version=2,before=after_identity,after=newest_identity,mutation=mutation,effective=after_identity["summary_key"]!=newest_identity["summary_key"])
        get_one(asset,"get-probe-during-generation")
        worker.join(timeout=30)
        rec.emit("probe_storage",old_key=after_identity["summary_key"],new_key=newest_identity["summary_key"],old_key_stored=service.repository.get_agent_review_summary(after_identity["summary_key"]) is not None,new_key_stored=service.repository.get_agent_review_summary(newest_identity["summary_key"]) is not None,worker_alive=worker.is_alive())
        get_one(asset,"get-probe-after-generation")
        if after_identity["summary_key"]==newest_identity["summary_key"] or worker.is_alive() or service.repository.get_agent_review_summary(after_identity["summary_key"]) is not None or service.repository.get_agent_review_summary(newest_identity["summary_key"]) is not None:
            rec.hard_stop.set()
            rec.emit("probe_gate_failure",reason="mutation ineffective, worker unfinished or stale publication")
        provider.scenario=args.scenario
    if args.preflight:
        rec.emit("business_snapshot",position="after",data=snapshot_business(args.database))
        rec.set_phase("complete")
        return
    rec.set_phase("warmup")
    poll(1); time.sleep(60); poll(2); time.sleep(60)
    rec.set_phase("measurement"); rec.measurement_zero=time.monotonic()
    zero=rec.measurement_zero
    stop=threading.Event()
    completed_polls=[]
    def watcher():
        n=3
        while not stop.is_set():
            poll(n); completed_polls.append(time.monotonic()); n+=1
            stop.wait(60)
    def reads():
        n=0
        while not stop.is_set():
            due=zero+n
            if stop.wait(max(0,due-time.monotonic())): break
            get_one(assets[n%len(assets)],f"get-{n:05d}",due=due)
            n+=1
    tw=threading.Thread(target=watcher); tr=threading.Thread(target=reads)
    tw.start(); tr.start()
    for ev in manifest["sequence"]:
        if rec.hard_stop.wait(max(0,zero+ev["at"]-time.monotonic())): break
        admission(ev)
    rec.hard_stop.wait(max(0,zero+args.duration-time.monotonic()))
    rec.emit("measurement_end",completed_poll_count=len(completed_polls),hard_stop=rec.hard_stop.is_set())
    rec.set_phase("drain")
    drain_start=time.monotonic()
    # Continue the unchanged watcher cadence and consumer reads up to the fixed cap.
    # Drain readiness is assessed independently from exact lookup traces by oracle.
    while time.monotonic()-drain_start<300 and not rec.hard_stop.is_set():
        exact=True
        for asset in assets:
            body=get_one(asset,f"get-drain-{asset}")
            trace=body.get("trace",{}); mat=trace.get("materialization",{})
            if mat.get("status")!="ready" or not body.get("summary") or trace.get("reuse_eligibility")!="EXACT_VALIDATED": exact=False
        if exact: break
        rec.hard_stop.wait(5)
    stop.set(); tw.join(timeout=180); tr.join(timeout=30)
    rec.emit("drain_end",duration=time.monotonic()-drain_start,watcher_alive=tw.is_alive(),read_alive=tr.is_alive())
    rec.emit("business_snapshot",position="after",data=snapshot_business(args.database))
    rec.set_phase("complete")
if __name__=="__main__":
    main()

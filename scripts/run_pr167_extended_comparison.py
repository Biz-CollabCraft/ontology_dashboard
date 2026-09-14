"""Preregister/resume a 3-model fixture comparison with explicit reasoning settings.

Every batch invokes one fixture once on each of three models; 16 batches total.
Outputs are outside Git. Credentials are used only for api.openai.com.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"systems/backend")]
from scripts import compare_agent_review_summary_models as cmp
from app.infra.llm import OpenAICompatibleProvider
MODELS=["gpt-4o-mini-2024-07-18","gpt-5-mini-2025-08-07","gpt-5.6-luna"]
COMMON={"provider":"openai-compatible","timeout_seconds":90,"response_format_policy":"json_schema_with_provider_json_object_retry"}
SETTINGS={m:{"temperature":"omitted_provider_default" if m.startswith("gpt-5") else 0,
             "reasoning_effort":"low" if m.startswith("gpt-5") else "not_applicable",
             "max_completion_tokens":4096,"endpoint":"https://api.openai.com/v1/chat/completions"} for m in MODELS}
PRICES={m:{"input_per_1m":a,"output_per_1m":b,"currency":"USD",
           "source":"https://developers.openai.com/api/docs/models/"+name,"as_of":"2026-09-07T00:00:00+00:00"}
        for m,a,b,name in zip(MODELS,[.15,.25,.2],[.6,2,1.2],["gpt-4o-mini","gpt-5-mini","gpt-5.6-luna"])}

def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")
    temporary.replace(path)

class EvalProvider(OpenAICompatibleProvider):
    def __init__(self,model):
        super().__init__()
        self.model=model
        self.timeout_seconds=90
        self.http_events=[]
        if self.base_url!="https://api.openai.com/v1" or not self.api_key:
            raise ValueError("verified endpoint and credential required")
    def _post_chat_completion(self,body):
        body=copy.deepcopy(body)
        body["max_completion_tokens"]=4096
        if self.model.startswith("gpt-5"):
            body.pop("temperature",None)
            body["reasoning_effort"]="low"
        response=super()._post_chat_completion(body)
        # Only bounded metadata, no headers, error bodies, or credential fields.
        entry={"status_code":response.status_code,"response_format":body["response_format"]["type"]}
        if response.status_code<400:
            data=response.json()
            entry.update(model=data.get("model"),usage=data.get("usage"),
                         finish_reasons=[c.get("finish_reason") for c in data.get("choices",[])])
        self.http_events.append(entry)
        return response

@contextmanager
def three_role_gold():
    ev=cmp.evaluation
    previous=(ev.GOLD_ANSWERS_PATH, ev._GOLD_ANSWERS_CACHE)
    try:
        ev.GOLD_ANSWERS_PATH=ev.GOLD_ROOT/"gold_answers_three_role_v2.json"
        ev._GOLD_ANSWERS_CACHE=None
        yield
    finally:
        ev.GOLD_ANSWERS_PATH, ev._GOLD_ANSWERS_CACHE=previous

@three_role_gold()
def frozen():
    ev=cmp.evaluation
    ev.GOLD_ANSWERS_PATH=ev.GOLD_ROOT/"gold_answers_three_role_v2.json"
    ev._GOLD_ANSWERS_CACHE=None
    packets=[json.loads((ev.GOLD_ROOT/f"GS-{i:03}.json").read_text()) for i in range(1,9)]
    assert all(p["project_id"]=="manufacturing-demo-project" and
               p["snapshot_basis"]["dataset_version"]=="fixture-compatibility" for p in packets)
    return packets,cmp.run_comparison(packets=packets,models=MODELS,iterations=2,
        prices=PRICES,model_settings=COMMON,model_settings_by_model=SETTINGS)

@three_role_gold()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--env-file",type=Path)
    parser.add_argument("--prepare",action="store_true")
    parser.add_argument("--batch",type=int)
    parser.add_argument("--availability",action="store_true")
    parser.add_argument("--live", action="store_true", help="Explicitly enable historical external-provider experiment")
    args=parser.parse_args()
    if (args.availability or args.batch is not None or not args.prepare) and not args.live:
        parser.error("choose --prepare for offline registration or --live for external calls")
    out=args.output_dir
    if args.env_file:
        from dotenv import dotenv_values
        c=dotenv_values(args.env_file)
        for k in ("LLM_API_KEY","OPENAI_API_KEY","LLM_BASE_URL"):
            if c.get(k):os.environ[k]=c[k]
    if args.availability:
        import httpx
        provider=EvalProvider(MODELS[0])
        r=httpx.get("https://api.openai.com/v1/models",headers={"Authorization":f"Bearer {provider.api_key}"},timeout=30)
        r.raise_for_status()
        ids={m["id"] for m in r.json()["data"]}
        print(json.dumps({m:m in ids for m in MODELS}))
        return
    packets,template=frozen()
    binding=template["archive_manifest"]["input_binding_sha256"]
    if args.prepare:
        if (out/"registration.json").exists():
            raise SystemExit("Registration already exists; preserve it.")
        config={"registered_at":datetime.now(UTC).isoformat(),"quality_floor":.8,"max_regression":.05,
                "repeat_count":2,"baseline_model":MODELS[0],"models":MODELS,"input_binding_sha256":binding,
                "direct_acceptance_floor":1.0,"selection_rule":"eligible minimum uncached list-price cost, then p95 latency",
                "settings":SETTINGS,"shared_settings":COMMON,"planned_attempts":48,
                "scope":"eight checked-in demo fixture packets only; no database access",
                "limits":["Same prompts/gold/schema, model-specific supported sampling settings.",
                          "GPT-5 mini and Luna low reasoning; 4o mini has no reasoning knob.",
                          "Two repetitions are not statistical significance or human usefulness."]}
        save(out/"registration.json",config)
        save(out/"frozen-inputs.json",template["frozen_inputs"])
        save(out/"prices.json",PRICES)
        print(json.dumps({"registered":str(out/"registration.json"),"input_binding":binding}))
        return
    config=json.loads((out/"registration.json").read_text())
    if binding!=config["input_binding_sha256"]:
        raise SystemExit("Inputs or settings changed; refusing live calls.")
    if args.batch is None or not 0<=args.batch<16:
        raise SystemExit("Choose batch 0..15.")
    batch_path=out/f"batch-{args.batch:02}.json"
    if not batch_path.exists():
        index=args.batch%8
        iteration=args.batch//8+1
        # Rotate provider ordering across all cases, as in the original harness.
        offset=args.batch%3
        ordered=MODELS[offset:]+MODELS[:offset]
        providers={m:EvalProvider(m) for m in ordered}
        part=cmp.run_comparison(packets=[packets[index]],models=ordered,providers=providers,iterations=1,
            prices=PRICES,mode="live",model_settings=COMMON,model_settings_by_model=SETTINGS,
            row_callback=lambda rows:save(out/f"checkpoint-{args.batch:02}.json",rows))
        for row in part["rows"]:
            row["iteration"]=iteration
            row["transport_metadata"]=providers[row["model"]].http_events
        save(batch_path,part)
    parts=[json.loads(p.read_text()) for p in sorted(out.glob("batch-*.json"))]
    report=template
    report.update(mode="live",evidence_level="live_provider",run_id="pr167-gpt5-luna-low",
                  started_at=min(p["started_at"] for p in parts),recorded_at=datetime.now(UTC).isoformat(),
                  selection_config=config,order="rotating_interleaved_batches")
    rows=[row for p in parts for row in p["rows"]]
    for sequence,row in enumerate(rows):row["sequence"]=sequence
    report["rows"]=rows
    report["aggregate"]={m:cmp.aggregate([r for r in rows if r["model"]==m],"live") for m in MODELS}
    report["archive_manifest"].update(started_at=report["started_at"],finished_at=report["recorded_at"],
        selection_config_sha256=cmp.fingerprint(config),
        attempts=[{k:r[k] for k in ("sequence","model","case_id","iteration","started_at","finished_at",
            "input_sha256","packet_sha256","usage","cost","provider_duration_ms","accepted","reject_reasons")}
            |{"row_sha256":cmp.fingerprint(r),"row_ref":f"#/rows/{r['sequence']}"} for r in rows])
    report["selection_gate"]=cmp.selection_gate(report,config)
    eligible=report["selection_gate"]["eligible_models"]
    report["selected_model"]=min(eligible,key=lambda m:(report["aggregate"][m]["cost"]["estimated_total_cost"],
        report["aggregate"][m]["latency_ms"]["p95"])) if eligible else None
    report["source_sha256"]={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),ROOT/"scripts/compare_agent_review_summary_models.py",
                  ROOT/"scripts/evaluate_agent_review_summary_llm.py")}
    save(out/"comparison.json",report)
    print(json.dumps({"finished_batches":len(parts),"attempts":len(rows),"accepted":sum(r["accepted"] for r in rows),
                      "selected_model":report["selected_model"]}))
if __name__=="__main__":main()

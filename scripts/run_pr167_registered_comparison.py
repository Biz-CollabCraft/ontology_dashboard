"""Freeze and execute the bounded PR167 comparison; never prints credentials."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "systems/backend"))
sys.path.insert(0, str(ROOT))
from scripts import compare_agent_review_summary_models as comparison
from app.infra.llm import OpenAICompatibleProvider

MODELS = ["gpt-4o-mini-2024-07-18", "gpt-4.1-mini-2025-04-14", "gpt-4.1-nano-2025-04-14"]
SETTINGS = {"provider": "openai-compatible", "temperature": 0, "timeout_seconds": 30,
            "response_format_policy": "json_schema_with_provider_json_object_retry"}

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--prepare", action="store_true")
    cli.add_argument("--output-dir", type=Path, required=True)
    cli.add_argument("--env-file", type=Path)
    cli.add_argument("--live", action="store_true", help="Explicitly enable historical external-provider experiment")
    args = cli.parse_args()
    if not args.prepare and not args.live:
        cli.error("choose --prepare for offline registration or --live for external calls")
    ev = comparison.evaluation
    ev.GOLD_ANSWERS_PATH = ev.GOLD_ROOT / "gold_answers_three_role_v2.json"
    ev._GOLD_ANSWERS_CACHE = None
    manifest = json.loads((ev.GOLD_ROOT / "manifest.json").read_text())
    expected = {f"tests/fixtures/agent_review_packets/GS-{i:03}.json" for i in range(1, 9)}
    if {c["fixture_path"] for c in manifest["cases"]} != expected:
        raise SystemExit("Only the eight checked-in demo fixtures are permitted.")
    packets = [json.loads((ROOT / c["fixture_path"]).read_text()) for c in manifest["cases"]]
    if any(p["project_id"] != "manufacturing-demo-project" or p["snapshot_basis"]["dataset_version"] != "fixture-compatibility" for p in packets):
        raise SystemExit("Only demo project / fixture dataset inputs are permitted.")
    out = args.output_dir
    prices = {m: {"input_per_1m": i, "output_per_1m": o, "currency": "USD",
                   "source": "https://developers.openai.com/api/docs/models/" + m.rsplit("-202",1)[0],
                   "as_of": "2026-09-07T00:00:00+00:00"}
              for m,i,o in zip(MODELS,[0.15,0.4,0.1],[0.6,1.6,0.4])}
    if args.prepare:
        frozen = comparison.run_comparison(packets=packets, models=MODELS, iterations=2,
                    prices=prices, model_settings=SETTINGS)
        config = {"registered_at": datetime.now(UTC).isoformat(), "quality_floor": 0.8,
                  "max_regression": 0.05, "repeat_count": 2, "baseline_model": MODELS[0],
                  "models": MODELS, "input_binding_sha256": frozen["archive_manifest"]["input_binding_sha256"],
                  "selection_rule": "Among gate-eligible models minimize mean uncached list-price cost, then p95 latency.",
                  "direct_acceptance_floor": 1.0, "human_usefulness": "not_measured",
                  "splits": {"development": ["GS-001","GS-002","GS-003","GS-004"],
                             "fixed_final": ["GS-005","GS-006","GS-007","GS-008"]},
                  "limits": ["Two repeats are a bounded comparison, not statistical significance.",
                             "Eight historical fixtures are not independent field samples.",
                             "Final cases are fixed before live calls; no post-result tuning."]}
        save(out / "registration.json", config)
        save(out / "frozen-inputs.json", frozen["frozen_inputs"])
        save(out / "prices.json", prices)
        print(json.dumps({"registered": str(out / "registration.json"), "calls": len(packets)*6}))
        return
    if not (out / "registration.json").exists():
        raise SystemExit("Run --prepare before any live calls.")
    config = json.loads((out / "registration.json").read_text())
    preflight = comparison.run_comparison(packets=packets, models=MODELS, iterations=2,
        prices=prices, model_settings=SETTINGS)
    if preflight["archive_manifest"]["input_binding_sha256"] != config["input_binding_sha256"]:
        raise SystemExit("Preregistered inputs/settings changed; no live calls made.")
    if args.env_file:
        from dotenv import dotenv_values
        values = dotenv_values(args.env_file)
        for key in ("LLM_API_KEY","OPENAI_API_KEY","LLM_BASE_URL"):
            if values.get(key):
                os.environ[key] = values[key]
    os.environ["LLM_TIMEOUT_SECONDS"] = "30"
    providers = {}
    for model in MODELS:
        provider = OpenAICompatibleProvider()
        provider.model = model
        if provider.base_url != "https://api.openai.com/v1":
            raise SystemExit("Only the verified api.openai.com destination is permitted.")
        if not provider.api_key:
            raise SystemExit("Credential unavailable; no calls made.")
        providers[model] = provider
    config = json.loads((out / "registration.json").read_text())
    report = comparison.run_comparison(packets=packets, models=MODELS, providers=providers,
        iterations=2, prices=prices, model_settings=SETTINGS, mode="live", selection_config=config,
        row_callback=lambda rows: save(out / "live-attempts-checkpoint.json", rows))
    report["run_id"] = "pr167-three-role-v2-20260907"
    eligible = report["selection_gate"]["eligible_models"]
    report["selected_model"] = min(eligible, key=lambda m: (
        report["aggregate"][m]["cost"]["estimated_total_cost"],
        report["aggregate"][m]["latency_ms"]["p95"])) if eligible else None
    report["split_aggregate"] = {split: {m: comparison.aggregate(
        [r for r in report["rows"] if r["model"]==m and r["case_id"].replace("EVT-","") in cases], "live")
        for m in MODELS} for split,cases in config["splits"].items()}
    report["source_file_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT / "scripts/compare_agent_review_summary_models.py",
                  ROOT / "scripts/run_pr167_registered_comparison.py",
                  ROOT / "systems/backend/app/operations/agent_review_summary.py",
                  ROOT / "systems/backend/app/operations/agent_review_summary_provider.py",
                  ROOT / "contracts/schemas/agent-review-summary-v1.1.schema.json"]}
    save(out / "comparison.json", report)
    print(json.dumps({"output": str(out / "comparison.json"), "selected_model": report["selected_model"],
                      "aggregate": report["aggregate"], "selection_gate": report["selection_gate"]}))
if __name__ == "__main__":
    main()

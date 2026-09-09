"""Bounded, sequential/interleaved comparison over frozen briefing fixtures.

Offline example (labels are test doubles, not actual models):
  PYTHONPATH=systems/backend python scripts/compare_agent_review_summary_models.py \
    --model offline-a --model offline-b --output /tmp/comparison.json

Live requires --mode live, explicit --model candidates, --run-id, --candidate-sha
and credentials already configured in the process environment. No dotenv is read.
Optional --prices JSON maps exact model IDs to input_per_1m, output_per_1m,
currency, source and as_of (timezone-aware ISO timestamp). No default prices.
Optional --selection-config JSON requires registered_at, quality_floor,
max_regression, repeat_count, baseline_model, models and input_binding_sha256.
Thresholds are on the existing 0..1 gold scale. Registration must precede the
run and bind its archived inputs/settings. The historical scorer is insufficient
for three-role selection even when all numeric thresholds pass.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

try:
    from scripts import evaluate_agent_review_summary_llm as evaluation
except ModuleNotFoundError:
    import evaluate_agent_review_summary_llm as evaluation
from app.operations import agent_review_summary_provider as adapter

NOT_MEASURED = "not_measured"
MAX_CALLS = 360
PRODUCT_ROLES = {"process_engineer", "maintenance_technician", "process_manager"}


def archive_prose(raw):
    """Keep only returned prose and role labels, never arbitrary provider fields."""
    if isinstance(raw, str):
        return {"unstructured_text": raw}
    if not isinstance(raw, dict):
        return None
    prose = {key: raw[key] for key in ("title", "summary") if isinstance(raw.get(key), str)}
    roles = raw.get("role_summaries")
    if isinstance(roles, list):
        prose["role_summaries"] = [
            {key: item[key] for key in ("role", "quote") if isinstance(item.get(key), str)}
            for item in roles if isinstance(item, dict)
        ]
    return prose


def selection_gate(report, config):
    """Eligibility only; never choose a winner by an implicit ranking policy."""
    reasons = []
    if not isinstance(config, dict):
        return {"status": "blocked", "reasons": ["preregistration_missing"],
                "eligible_models": [], "selected_model": None}
    for key in ("quality_floor", "max_regression"):
        value = config.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            reasons.append(f"invalid_or_missing_{key}")
    repeats = config.get("repeat_count")
    if type(repeats) is not int or repeats < 1:
        reasons.append("invalid_or_missing_repeat_count")
    try:
        registered = datetime.fromisoformat(config["registered_at"])
        if registered.utcoffset() is None or registered >= datetime.fromisoformat(report["started_at"]):
            reasons.append("registration_not_before_run")
    except (KeyError, TypeError, ValueError):
        reasons.append("registration_timestamp_missing_or_invalid")
    if config.get("models") != report["models"]:
        reasons.append("preregistered_models_mismatch")
    if config.get("input_binding_sha256") != report["archive_manifest"]["input_binding_sha256"]:
        reasons.append("preregistered_inputs_or_settings_mismatch")
    baseline = config.get("baseline_model")
    if baseline not in report["models"] or len(report["models"]) < 2:
        reasons.append("comparison_baseline_missing")
    rubric = report["selection_rubric"]
    if not rubric["complete"] or set(rubric["roles"]) != PRODUCT_ROLES:
        reasons.append("complete_three_role_rubric_missing")
    if report["mode"] != "live" or report["evidence_level"] != "live_provider":
        reasons.append("live_measurements_missing")
    if any(settings.get("provider") in (None, "", NOT_MEASURED)
           or settings.get("temperature") in (None, NOT_MEASURED)
           for settings in report["archive_manifest"]["model_settings"].values()):
        reasons.append("model_settings_not_recorded")
    rows = report["rows"]
    if not rows or any(r["usage"] is None or r["provider_duration_ms"] is None
                       or r["cost"]["estimated_total_cost"] is None for r in rows):
        reasons.append("complete_latency_usage_and_priced_cost_required")
    currencies = {r["cost"].get("price", {}).get("currency") for r in rows}
    if len(currencies) != 1 or None in currencies:
        reasons.append("comparable_cost_currency_required")
    expected_packets = {p["packet_sha256"] for p in report["archive_manifest"]["packets"]}
    if type(repeats) is int and repeats > 0:
        if any({r["iteration"] for r in rows if r["model"] == m and r["packet_sha256"] == p}
               != set(range(1, repeats + 1))
               or sum(r["model"] == m and r["packet_sha256"] == p for r in rows) != repeats
               for m in report["models"] for p in expected_packets):
            reasons.append("preregistered_repeat_count_not_met")
    if reasons:
        return {"status": "blocked", "reasons": reasons, "eligible_models": [], "selected_model": None}
    # Raw prose metrics cannot be replaced with the delivered fallback's score.
    baseline_score = report["aggregate"][baseline]["raw_candidate_gold_score"]
    eligible = []
    model_reasons = {}
    for model in report["models"]:
        stats = report["aggregate"][model]
        failures = []
        score = stats["raw_candidate_gold_score"]
        if stats["raw_gold_scored_candidates"] != stats["attempts"] or score is None or baseline_score is None:
            failures.append("complete_raw_candidate_scores_required")
        else:
            if score < config["quality_floor"]:
                failures.append("below_quality_floor")
            if baseline_score - score > config["max_regression"]:
                failures.append("exceeds_max_regression")
        if stats["hard_gate_pass_rate"] != 1.0:
            failures.append("direct_acceptance_failed")
        model_reasons[model] = failures
        if not failures:
            eligible.append(model)
    return {"status": "eligible_for_human_selection" if eligible else "blocked",
            "reasons": [] if eligible else ["no_candidate_passed"], "model_reasons": model_reasons,
            "eligible_models": eligible, "selected_model": None}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_prices(prices, models):
    if not isinstance(prices, dict) or set(prices) - set(models):
        raise ValueError("prices must map configured model IDs only")
    for price in prices.values():
        if not isinstance(price, dict):
            raise ValueError("each price must be an object")
        for key in ("input_per_1m", "output_per_1m"):
            rate = price.get(key)
            if type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0:
                raise ValueError("prices require finite nonnegative rates")
        if not all(isinstance(price.get(k), str) and price[k].strip()
                   for k in ("currency", "source", "as_of")):
            raise ValueError("prices require currency, source and as_of")
        if datetime.fromisoformat(price["as_of"]).utcoffset() is None:
            raise ValueError("price as_of must include timezone")


def reported_usage(metadata):
    if not isinstance(metadata, dict):
        return None
    usage = metadata.get("usage")
    if not isinstance(usage, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in keys):
        return None
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        return None
    return {k: usage[k] for k in keys}


def cost_for(usage, price):
    if usage is None or price is None:
        return {"status": NOT_MEASURED, "estimated_total_cost": None}
    return {
        "status": "estimated_from_reported_usage", "price": copy.deepcopy(price),
        "estimated_total_cost": (usage["prompt_tokens"] * price["input_per_1m"]
                                 + usage["completion_tokens"] * price["output_per_1m"]) / 1_000_000,
    }


def aggregate(rows, mode):
    accepted = [r for r in rows if r["accepted"]]
    scored = [r["candidate_gold"] for r in rows if r["candidate_gold"] is not None]
    latencies = [r["provider_duration_ms"] for r in rows if r["provider_duration_ms"] is not None]
    usages = [r["usage"] for r in rows if r["usage"] is not None]
    costs = [r["cost"]["estimated_total_cost"] for r in rows]
    complete_cost = all(c is not None for c in costs)
    raw_scores = [r["raw_candidate_gold"] for r in rows if r["raw_candidate_gold"] is not None]
    return {
        "attempts": len(rows), "accepted_candidates": len(accepted),
        "fallback_summaries": len(rows) - len(accepted),
        "hard_gate_pass_rate": evaluation._ratio(len(accepted), len(rows)),
        "gold_scored_candidates": len(scored),
        "raw_gold_scored_candidates": len(raw_scores),
        "raw_candidate_gold_score": evaluation._average([s["accuracy_goldset_score"] for s in raw_scores]),
        "delivered_gold_score": evaluation._average(
            [r["delivered_gold"]["accuracy_goldset_score"] for r in rows if r["delivered_gold"] is not None]),
        "fallback_gold_score": evaluation._average(
            [r["fallback_gold"]["accuracy_goldset_score"] for r in rows if r["fallback_gold"] is not None]),
        "candidate_gold_score": evaluation._average([s["accuracy_goldset_score"] for s in scored]),
        "accepted_candidate_gold_score": evaluation._average(
            [r["candidate_gold"]["accuracy_goldset_score"] for r in accepted if r["candidate_gold"] is not None]),
        "required_fact_coverage": evaluation._average([s["required_fact_score"] for s in scored]),
        "role_scores": {role: evaluation._average([s["role_scores"][role]["score"]
                        for s in scored if role in s["role_scores"]])
                        for role in sorted({role for s in scored for role in s["role_scores"]})},
        "unsupported_claim_rate_scored_candidates": evaluation._ratio(
            sum(bool(s["unsupported_claim_count"]) for s in scored), len(scored)),
        "latency_ms": {"status": "measured" if mode == "live" else NOT_MEASURED,
                       "samples": len(latencies),
                       "p50": evaluation._percentile(latencies, 50),
                       "p95": evaluation._percentile(latencies, 95)},
        "tokens": {"status": "provider_reported" if len(usages) == len(rows) else NOT_MEASURED,
                   "reported_rows": len(usages),
                   "reported_subtotal": {k: sum(u[k] for u in usages) for k in
                                         ("prompt_tokens", "completion_tokens", "total_tokens")}},
        "cost": {"status": "estimated_from_reported_usage" if complete_cost else NOT_MEASURED,
                 "measured_rows": sum(c is not None for c in costs),
                 "estimated_total_cost": sum(costs) if complete_cost else None},
        "human_usefulness": NOT_MEASURED,
    }


def run_comparison(*, packets, models, providers=None, iterations=1, prices=None,
                   mode="offline", clock=time.perf_counter, model_settings=None, selection_config=None, row_callback=None, model_settings_by_model=None):
    started_at = datetime.now(UTC).isoformat()
    selection_config = copy.deepcopy(selection_config)
    if (not 1 <= len(models) <= 3 or len(set(models)) != len(models)
            or any(not isinstance(m, str) or not m.strip() for m in models)):
        raise ValueError("configure one to three distinct model IDs")
    if not packets or type(iterations) is not int or iterations < 1:
        raise ValueError("nonempty fixtures and positive iterations required")
    if len(packets) * iterations * len(models) > MAX_CALLS:
        raise ValueError("comparison exceeds 360 attempts")
    if mode not in ("offline", "live"):
        raise ValueError("unknown mode")
    if mode == "live" and (providers is None or set(providers) != set(models)):
        raise ValueError("every live candidate requires a provider")
    prices = prices or {}
    validate_prices(prices, models)
    schema = adapter.agent_review_summary_editable_schema()
    system = adapter.AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT
    scorer_sha256 = hashlib.sha256(Path(evaluation.__file__).read_bytes()).hexdigest()
    # No provider __dict__ / environment dump: archive only explicit public settings.
    settings = {m: {"model": m, "provider": NOT_MEASURED, "temperature": NOT_MEASURED,
                **{k: copy.deepcopy(v) for k, v in (model_settings or {}).items()
                if k in ("provider", "temperature", "timeout_seconds", "response_format_policy")}}
                for m in models}
    for model, overrides in (model_settings_by_model or {}).items():
        if model not in settings or not isinstance(overrides, dict):
            raise ValueError("invalid per-model settings")
        allowed = {"provider", "temperature", "timeout_seconds", "response_format_policy",
                   "reasoning_effort", "max_completion_tokens", "endpoint"}
        if set(overrides) - allowed:
            raise ValueError("unsupported per-model setting")
        settings[model].update(copy.deepcopy(overrides))
    frozen = []
    for packet in copy.deepcopy(packets):
        baseline = evaluation.compose_deterministic_agent_review_summary(packet)
        payload = adapter.build_tool_selected_agent_review_summary_prompt_payload(
            packet=packet, baseline_summary=baseline)
        frozen.append((packet, baseline, payload))
    output_roles = sorted({item["role"] for _, baseline, _ in frozen for item in baseline["role_summaries"]})
    gold_roles = sorted({role for packet, _, _ in frozen
                         for role in (evaluation._gold_answer_for(packet) or {}).get("role_points", {})})
    rows = []
    for iteration in range(iterations):
        for case_index, (packet, baseline, payload) in enumerate(frozen):
            offset = (iteration * len(frozen) + case_index) % len(models)
            for model in models[offset:] + models[:offset]:
                candidate = None
                metadata = {}
                errors = []
                duration = None
                provider_error = None
                raw = None
                attempt_started_at = datetime.now(UTC).isoformat()
                started = clock()
                try:
                    if mode == "offline":
                        raw = evaluation._editable_candidate_payload(baseline)
                    else:
                        try:
                            result = providers[model].generate_json_with_metadata(
                                system, copy.deepcopy(payload), response_schema=copy.deepcopy(schema),
                                response_schema_name="agent_review_summary_editable")
                        finally:
                            duration = round((clock() - started) * 1000, 3)
                        metadata = result.get("provider_metadata") or {}
                        raw = result["payload"]
                    # Validate the raw surface BEFORE merge can silently fill missing prose.
                    if list(jsonschema.Draft202012Validator(schema).iter_errors(raw)):
                        errors.append("editable_contract_failed")
                    elif (any(not raw[k].strip() for k in ("title", "summary"))
                          or any(not item["quote"].strip() for item in raw["role_summaries"])
                          or sorted(item["role"] for item in raw["role_summaries"])
                          != sorted(item["role"] for item in baseline["role_summaries"])):
                        errors.append("incomplete_role_prose")
                    else:
                        candidate = adapter._merge_llm_editable_fields(
                            baseline_summary=copy.deepcopy(baseline), candidate=raw)
                        errors = evaluation.validate_agent_review_summary_contract(candidate, packet=packet)
                except Exception as exc:
                    # Never persist exception messages: upstream errors may contain credentials.
                    provider_error = type(exc).__name__
                accepted = candidate is not None and not errors and provider_error is None
                usage = reported_usage(metadata) if mode == "live" else None
                raw_prose = archive_prose(raw)
                raw_score_input = ({"summary": raw_prose["unstructured_text"]}
                                   if raw_prose and "unstructured_text" in raw_prose else raw_prose)
                raw_gold = (evaluation._gold_accuracy(raw_score_input, packet=packet)
                            if raw_score_input is not None and evaluation._summary_prose(raw_score_input).strip() else None)
                delivered = candidate if accepted else baseline
                rows.append({
                    "sequence": len(rows), "iteration": iteration + 1, "model": model,
                    "case_id": packet["snapshot_basis"]["event_id"],
                    "packet_sha256": fingerprint(packet), "input_sha256": fingerprint(payload),
                    "accepted": accepted, "fallback": not accepted,
                    "validation_errors": errors, "provider_error": provider_error,
                    "reject_reasons": errors + (["provider_error:" + provider_error] if provider_error else []),
                    "started_at": attempt_started_at, "finished_at": datetime.now(UTC).isoformat(),
                    "raw_candidate_prose": raw_prose, "raw_candidate_gold": raw_gold,
                    "delivered_output": evaluation._editable_candidate_payload(delivered),
                    "delivered_kind": "accepted_candidate" if accepted else "deterministic_fallback",
                    "delivered_gold": evaluation._gold_accuracy(delivered, packet=packet),
                    "candidate_gold": evaluation._gold_accuracy(candidate, packet=packet)
                                      if candidate is not None else None,
                    "fallback_gold": evaluation._gold_accuracy(baseline, packet=packet) if not accepted else None,
                    "editable_output": evaluation._editable_candidate_payload(candidate) if accepted else None,
                    "prose_equals_baseline": evaluation._editable_candidate_payload(candidate)
                                             == evaluation._editable_candidate_payload(baseline)
                                             if candidate is not None else None,
                    "provider_duration_ms": duration, "usage": usage,
                    "usage_measurement": "provider_reported" if usage is not None else NOT_MEASURED,
                    "cost": cost_for(usage, prices.get(model)),
                })
                if row_callback is not None:
                    row_callback(copy.deepcopy(rows))
    inputs = {
        "packets": [{"case_id": p["snapshot_basis"]["event_id"], "packet_sha256": fingerprint(p),
                     "prompt_payload_sha256": fingerprint(payload)} for p, _, payload in frozen],
        "system_prompt_sha256": fingerprint(system), "response_schema_sha256": fingerprint(schema),
        "scorer_sha256": scorer_sha256,
        "gold_answers_sha256": fingerprint(evaluation._gold_answers()), "model_settings": settings,
        "prices_sha256": fingerprint(prices),
    }
    report = {
        "mode": mode, "evidence_level": "live_provider" if mode == "live" else "offline_test_double",
        "started_at": started_at,
        "recorded_at": datetime.now(UTC).isoformat(), "models": models,
        "prompt_version": adapter.AGENT_REVIEW_SUMMARY_PROMPT_VERSION,
        "role_gold_coverage": {"output_roles": output_roles, "gold_roles": gold_roles,
                               "unscored_output_roles": sorted(set(output_roles) - set(gold_roles)),
                               "missing_output_roles": sorted(set(gold_roles) - set(output_roles))},
        "system_prompt_sha256": fingerprint(system), "response_schema_sha256": fingerprint(schema),
        "scorer_sha256": scorer_sha256,
        "order": "rotating_interleaved", "concurrency": 1, "max_attempts": MAX_CALLS,
        "selection_rubric": {"id": "historical_required_fact_and_forbidden_phrase_proxy",
                            "complete": evaluation._gold_answers().get("rubric_status") == "frozen_three_role_automatic_proxy"
                                and all(set((evaluation._gold_answer_for(p) or {}).get("role_points", {})) == PRODUCT_ROLES
                                        and all((evaluation._gold_answer_for(p) or {})["role_points"].values()) for p, _, _ in frozen),
                            "roles": gold_roles,
                            "reason": "Automatic required-fact proxy only; human usefulness is not measured."},
        "archive_manifest": {"version": "agent-summary-comparison-archive-v1", **inputs,
            "input_binding_sha256": fingerprint(inputs),
            "selection_config_sha256": fingerprint(selection_config) if selection_config is not None else None,
            "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
            "attempts": [{k: row[k] for k in ("sequence", "model", "case_id", "iteration", "started_at",
                "finished_at", "packet_sha256", "input_sha256", "usage", "usage_measurement", "cost",
                "provider_duration_ms", "accepted", "reject_reasons")}
                | {"row_sha256": fingerprint(row), "row_ref": f"#/rows/{row['sequence']}"} for row in rows]},
        "frozen_inputs": {"system_prompt": system, "response_schema": schema,
                          "gold_answers": copy.deepcopy(evaluation._gold_answers()),
                          "cases": [{"packet": p, "prompt_payload": payload} for p, _, payload in frozen]},
        "rows": rows, "aggregate": {m: aggregate([r for r in rows if r["model"] == m], mode) for m in models},
        "limits": ["Offline rows are deterministic test doubles, not model-quality measurements.",
                   "Gold scorer is a required-fact/forbidden-phrase proxy, not exhaustive groundedness or human usefulness.",
                   "Provider duration includes transport and provider-internal schema retry; failed calls are included.",
                   "Prices are supplied estimates, not billing reconciliation; cache/reasoning tier pricing is not modeled.",
                   "No automatic winner: human usefulness and operational benefit remain not_measured."],
    }
    report["selection_config"] = copy.deepcopy(selection_config)
    report["selection_gate"] = selection_gate(report, selection_config)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--manifest", type=Path, default=evaluation.GOLD_ROOT / "manifest.json")
    parser.add_argument("--gold-answers", type=Path, default=evaluation.GOLD_ANSWERS_PATH)
    parser.add_argument("--prices", type=Path)
    parser.add_argument("--selection-config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-sha")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = evaluation._load_json(args.manifest)
    packets = [evaluation._load_json(evaluation.ROOT / c["fixture_path"]) for c in manifest["cases"]]
    evaluation.GOLD_ANSWERS_PATH = args.gold_answers
    evaluation._GOLD_ANSWERS_CACHE = None
    prices = evaluation._load_json(args.prices) if args.prices else {}
    selection_config = evaluation._load_json(args.selection_config) if args.selection_config else None
    providers = None
    parameters = {"temperature": NOT_MEASURED}
    if args.mode == "live":
        if not args.run_id or not args.candidate_sha:
            parser.error("live requires --run-id and --candidate-sha")
        if not any(key in os.environ for key in ("LLM_API_KEY", "OPENAI_API_KEY")):
            parser.error("live requires credentials already configured in the process environment")
        from app.infra.llm import OpenAICompatibleProvider
        providers = {}
        for model in args.model:
            provider = OpenAICompatibleProvider()
            provider.model = model
            providers[model] = provider
        modes = {p._uses_default_temperature_only() for p in providers.values()}
        if len(modes) != 1:
            parser.error("candidates have unequal provider temperature policies")
        parameters = {"temperature": "provider_default" if True in modes else 0,
                      "provider": "openai-compatible", "timeout_seconds": provider.timeout_seconds,
                      "response_format_policy": "json_schema_with_provider_json_object_retry"}
    try:
        report = run_comparison(packets=packets, models=args.model, providers=providers,
                                iterations=args.iterations, prices=prices, mode=args.mode,
                                model_settings=parameters, selection_config=selection_config)
    except ValueError as exc:
        parser.error(str(exc))
    report.update(run_id=args.run_id, candidate_sha=args.candidate_sha,
                  eval_set_id=manifest["eval_set_id"], manifest_sha256=fingerprint(manifest),
                  gold_answers_sha256=fingerprint(evaluation._gold_answers()), generation_parameters=parameters)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "mode": args.mode, "attempts": len(report["rows"])}))


if __name__ == "__main__":
    main()

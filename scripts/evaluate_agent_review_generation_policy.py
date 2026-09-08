#!/usr/bin/env python3
"""Reproducible 8 x 10 discrete-time policy simulation, with no provider calls.

Gold labels express desired material-change scheduling, not permission to rebind
prose. Changed bindings may conservatively exceed the gold generation budget.
"""
from __future__ import annotations

import copy
import json
import sys
import hashlib
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for relative in ("systems/backend", "packages/backend", "packages/ml_core"):
    sys.path.insert(0, str(ROOT / relative))

from app.operations.agent_review_summary_generation_policy import decide_generation, policy_fingerprint, material_change_required, packet_is_current
from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload


def temporal_snapshots():
    directory = ROOT / "tests/fixtures/agent_review_packets"
    fixture = json.loads((directory / "temporal_policy.json").read_text())
    for scenario in fixture["scenarios"]:
        packet = json.loads((directory / f"{scenario}.json").read_text())
        for index, step in enumerate(fixture["steps"]):
            change = step["change"]
            # Deliberately retain changed snapshot identities even for small
            # numeric changes: semantic gold REUSE cannot override provenance.
            if change == "minor_numeric":
                packet["snapshot_basis"]["source_sha256"] = f"synthetic-minor-{scenario}"
                old = packet["risk_summary"]["failure_probability"]
                if old is not None:
                    packet["risk_summary"]["failure_probability"] = old + 0.001
                    packet["model_expression_context"]["failure_probability"] = old + 0.001
                    packet["review_draft"]["summary"] = packet["review_draft"]["summary"].replace(f"{old * 100:.1f}%", f"{(old + 0.001) * 100:.1f}%")
            elif change == "retrieval_timestamp":
                packet["generated_at"] = "2026-09-07T00:02:00Z"  # Retrieval audit time, outside key.
            elif change == "risk_priority":
                packet["review_priority"] = {"level": "immediate", "reasons": ["synthetic priority change"], "source_fields": ["risk.status_grade"]}
            elif change == "work_order":
                packet["maintenance_history_summary"]["open_work_order_exists"] = True
            elif change == "display_metadata":
                # UI-only metadata outside generation inputs.
                pass  # UI state does not enter the packet.
            elif change == "maintenance_event":
                packet["maintenance_history_summary"]["last_maintenance_days_ago"] = 0
            elif change == "production_option":
                packet["operation_context_summary"]["estimated_lost_units"] = 200
            yield scenario, index, step, copy.deepcopy(packet)


def simulate_scenario(policy, snapshots, timing, profile):
    """Discrete seconds: change -> completion -> watcher -> refresh -> query.

    A query is strictly read-only. A successful completion is assumed validated
    only for its captured exact key; stale completions are discarded. This is
    a scheduler simulation, not an invocation of the runtime/provider validator.
    """
    period = timing["snapshot_period_seconds"]
    changes = {index * period: (index, step, packet) for _, index, step, packet in snapshots}
    queries = {t + offset for t in changes for offset in timing["query_offsets_seconds"]}
    refreshes = {t + timing["refresh_offset_seconds"] for t, (_, step, _) in changes.items() if step["change"] == "explicit_refresh"}
    stored, running, attempts, retry_after = set(), {}, {}, {}
    rows, decisions, query_rows = [], [], []
    first_decisions = {}
    current, previous = None, None
    baseline_packet, baseline_identity = None, None
    step_index, step = None, None
    for now in range(timing["end_seconds"] + 1):
        if now in changes:
            step_index, step, packet = changes[now]
            identity = summary_key_payload(packet=packet, project_id=packet["project_id"], history_window="24h", provider=None)
            previous, current = current, policy_fingerprint(summary_key(identity))
            rows.append({"time": now, "event": "change", "snapshot": step_index, "fingerprint": current, **step})
        for key, job in list(running.items()):
            if job["due"] != now:
                continue
            del running[key]
            outcome = "failure" if job["fail"] else ("completed" if key == current else "stale_completion_discarded")
            if outcome == "completed":
                stored.add(key)
                baseline_packet, baseline_identity = job["packet"], job["identity"]
            if outcome == "failure":
                retry_after[key] = now + timing["retry_backoff_seconds"]
            rows.append({"time": now, "event": outcome, "fingerprint": key, "attempt": job["attempt"]})
        for source, active in (("watcher", now % timing["watcher_period_seconds"] == 0), ("refresh", now in refreshes)):
            if not active or current is None:
                continue
            trace = decide_generation(
                policy=policy, current_fingerprint=current, previous_fingerprint=previous,
                reuse_eligibility="EXACT_VALIDATED" if current in stored else "INELIGIBLE",
                explicit_refresh=source == "refresh", model_id=identity["model_version"],
                input_valid=packet_is_current(packet),
                material_change=material_change_required(packet, baseline_packet, current_identity=identity, previous_identity=baseline_identity),
            )
            row = {"time": now, "event": "decision", "source": source, "snapshot": step_index, **trace}
            decisions.append(row)
            if source == "watcher":
                first_decisions.setdefault(step_index, row)
            if trace["generation_action"] == "GENERATE":
                if source == "refresh" and current not in running:
                    attempts[current] = 0
                attempt = attempts.get(current, 0) + 1
                blocked = (current in running or now < retry_after.get(current, 0) or attempt > timing["max_attempts_per_key"])
                if not blocked:
                    attempts[current] = attempt
                    running[current] = {"due": now + profile["completion_latency_seconds"], "attempt": attempt, "fail": attempt == 1 and step_index in profile["fail_first_at_steps"], "packet": copy.deepcopy(packet), "identity": copy.deepcopy(identity)}
                    rows.append({"time": now, "event": "generation_started", "source": source, "snapshot": step_index, "fingerprint": current, "attempt": attempt, "retry": source == "watcher" and current in retry_after})
                else:
                    row["execution_guard"] = "in_flight_backoff_or_attempt_limit"
        if now in queries:
            query_rows.append({"time": now, "snapshot": step_index, "gold": step["gold"], "event": "query", "fingerprint": current, "simulated_hit": current in stored})
    critical = [first_decisions[i] for i, (_, _, s, _) in enumerate(snapshots) if s["gold"] == "PREGENERATE"]
    return {
        "scenario": snapshots[0][0], "snapshot_count": len(snapshots),
        "critical_count": len(critical),
        "critical_generation_requested": sum(r["generation_action"] == "GENERATE" for r in critical),
        "false_reuse_count": sum(r["reuse_eligibility"] == "EXACT_VALIDATED" for r in critical),
        "events": rows, "decisions": decisions, "queries": query_rows,
    }


def aggregate(runs):
    events = [e for r in runs for e in r["events"]]
    queries = [q for r in runs for q in r["queries"]]
    critical_queries = [q for q in queries if q["gold"] == "PREGENERATE"]
    starts = [e for e in events if e["event"] == "generation_started"]
    critical = sum(r["critical_count"] for r in runs)
    requested = sum(r["critical_generation_requested"] for r in runs)
    return {
        "snapshot_count": sum(r["snapshot_count"] for r in runs),
        "critical_count": critical, "critical_generation_requested": requested,
        "scoped_fixture_critical_request_coverage": requested / critical,
        "false_reuse_count": sum(r["false_reuse_count"] for r in runs),
        "simulated_background_generations": sum(e["source"] == "watcher" for e in starts),
        "simulated_refresh_generations": sum(e["source"] == "refresh" for e in starts),
        "simulated_retries": sum(e["retry"] for e in starts),
        "simulated_failures": sum(e["event"] == "failure" for e in events),
        "simulated_stale_completions_discarded": sum(e["event"] == "stale_completion_discarded" for e in events),
        "simulated_query_count": len(queries),
        "simulated_query_hits": sum(q["simulated_hit"] for q in queries),
        "simulated_availability": sum(q["simulated_hit"] for q in queries) / len(queries),
        "simulated_critical_query_hits": sum(q["simulated_hit"] for q in critical_queries),
        "simulated_critical_query_count": len(critical_queries),
    }


def evaluate():
    fixture_bytes = (ROOT / "tests/fixtures/agent_review_packets/temporal_policy.json").read_bytes()
    fixture = json.loads(fixture_bytes)
    snapshots = list(temporal_snapshots())
    policies = {}
    for policy in ("click", "always", "hybrid"):
        runs = [simulate_scenario(policy, [s for s in snapshots if s[0] == scenario], fixture["timing"], fixture["profiles"][scenario]) for scenario in fixture["scenarios"]]
        policies[policy] = {
            **aggregate(runs),
            "splits": {name: aggregate([r for r in runs if r["scenario"] in ids]) for name, ids in fixture["splits"].items()},
            "runs": runs,
        }
    policies["hybrid"]["simulated_background_reduction_vs_always"] = 1 - policies["hybrid"]["simulated_background_generations"] / policies["always"]["simulated_background_generations"]
    return {
        "evidence_level": "measured_policy_simulation",
        "fixture_snapshots": len(snapshots), "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "seed_packet_sha256": {scenario: hashlib.sha256((ROOT / "tests/fixtures/agent_review_packets" / f"{scenario}.json").read_bytes()).hexdigest() for scenario in fixture["scenarios"]},
        "timeline": fixture["timing"], "profiles": fixture["profiles"], "splits": fixture["splits"],
        "simulation_assumption": "exact-key candidate validation modeled as success unless injected failure; fixed delays; stale completion rejected; no provider invoked",
        "runtime_briefing_availability": "not_measured", "provider_call_savings": "not_measured", "tokens_cost_latency": "not_measured",
        "policies": policies,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({p: {k: v for k, v in r.items() if k != "runs"} for p, r in report["policies"].items()}))
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))

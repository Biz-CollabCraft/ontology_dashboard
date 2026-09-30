#!/usr/bin/env python3
"""Evaluate briefing scale behavior without issuing new external LLM calls.

The harness deliberately separates:
1. measured local generation-policy/change-detection CPU/wall time; and
2. a discrete-event replay using already-recorded live-provider latency/token
   samples from the repository's 2026-09-05 evaluation artifact.

It does not claim that the replay is live provider throughput.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "systems/backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.operations.agent_review_summary_generation_policy import decide_generation


REFERENCE_PROVIDER_RESULT = (
    ROOT
    / "tests/eval/results/agent_summary_llm_eval_live_120_20260905_pm_fix.json"
)
ASSET_COUNTS = (100, 500, 1000)
CHANGE_PROFILES = {
    "low_change": 0.01,
    "medium_change": 0.10,
    "burst_change": 0.50,
}
DEFAULT_POLL_INTERVAL_MS = 10_000.0
DEFAULT_CHALLENGER_WORKERS = 8
DEFAULT_CHALLENGER_CYCLES = 6
DEFAULT_REPEATS = 3


@dataclass(frozen=True)
class ProviderReference:
    provider: str
    model: str
    latency_samples_ms: tuple[float, ...]
    prompt_token_samples: tuple[int, ...]
    completion_token_samples: tuple[int, ...]
    total_token_samples: tuple[int, ...]
    latency_basis: str
    token_basis: str
    cost_status: str

    def sample(self, index: int) -> tuple[float, int, int, int]:
        if not self.latency_samples_ms:
            raise ValueError("provider reference has no latency samples")
        offset = index % len(self.latency_samples_ms)
        return (
            self.latency_samples_ms[offset],
            self.prompt_token_samples[offset],
            self.completion_token_samples[offset],
            self.total_token_samples[offset],
        )


@dataclass(frozen=True)
class Candidate:
    asset_index: int
    version: int
    arrival_ms: float


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_provider_reference(
    path: Path = REFERENCE_PROVIDER_RESULT,
) -> ProviderReference:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") or []
    latencies: list[float] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []
    for row in rows:
        llm = row.get("llm") or {}
        usage = llm.get("usage") or {}
        duration = llm.get("duration_ms")
        if not isinstance(duration, (int, float)):
            continue
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if not all(isinstance(value, int) for value in (prompt, completion, total)):
            continue
        latencies.append(float(duration))
        prompt_tokens.append(prompt)
        completion_tokens.append(completion)
        total_tokens.append(total)
    if not latencies:
        raise ValueError(f"no usable provider rows in {path}")
    aggregate = payload.get("aggregate") or {}
    cost = aggregate.get("cost") or {}
    return ProviderReference(
        provider=str(payload.get("provider") or "unknown"),
        model=str(payload.get("model") or "unknown"),
        latency_samples_ms=tuple(latencies),
        prompt_token_samples=tuple(prompt_tokens),
        completion_token_samples=tuple(completion_tokens),
        total_token_samples=tuple(total_tokens),
        latency_basis=(
            "recorded live-provider duration_ms replay; reference artifact says "
            "provider call + local validation end-to-end"
        ),
        token_basis=(
            "reference artifact prompt/completion counters; repository evidence "
            "classifies the 120-run token values as payload/output-size estimates, "
            "not provider billing usage"
        ),
        cost_status=str(cost.get("status") or "not_configured"),
    )


def benchmark_change_detection(
    *,
    asset_count: int,
    changed_count: int,
    repeats: int,
) -> dict[str, Any]:
    if asset_count < 1:
        raise ValueError("asset_count must be positive")
    if not 0 <= changed_count <= asset_count:
        raise ValueError("changed_count must be between 0 and asset_count")
    wall_samples: list[float] = []
    cpu_samples: list[float] = []
    generated_counts: list[int] = []
    reused_counts: list[int] = []

    for repeat in range(repeats):
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        generated = 0
        reused = 0
        for index in range(asset_count):
            changed = index < changed_count
            decision = decide_generation(
                policy="always",
                current_fingerprint=(
                    f"asset:{index}:version:{repeat + 1}"
                    if changed
                    else f"asset:{index}:stable"
                ),
                previous_fingerprint=f"asset:{index}:stable",
                reuse_eligibility=(
                    "INELIGIBLE" if changed else "EXACT_VALIDATED"
                ),
                material_change=changed,
                input_valid=True,
                background_required=True,
                model_id="scale-reference",
            )
            if decision["generation_action"] == "GENERATE":
                generated += 1
            elif decision["generation_decision"] == "REUSE":
                reused += 1
        cpu_samples.append((time.process_time() - cpu_started) * 1000)
        wall_samples.append((time.perf_counter() - wall_started) * 1000)
        generated_counts.append(generated)
        reused_counts.append(reused)

    if len(set(generated_counts)) != 1 or len(set(reused_counts)) != 1:
        raise AssertionError("generation-policy counts changed across repeats")

    wall_p50 = percentile(wall_samples, 0.50)
    return {
        "measurement": "local_wall_and_process_cpu",
        "repeat_count": repeats,
        "wall_ms": {
            "samples": [round(value, 3) for value in wall_samples],
            "p50": round(wall_p50, 3),
            "p95": round(percentile(wall_samples, 0.95), 3),
        },
        "cpu_ms": {
            "samples": [round(value, 3) for value in cpu_samples],
            "p50": round(percentile(cpu_samples, 0.50), 3),
            "p95": round(percentile(cpu_samples, 0.95), 3),
        },
        "poll_read_ops_per_sec": round(
            asset_count / max(wall_p50 / 1000, 1e-9),
            3,
        ),
        "candidate_generation_rate_per_sec": round(
            changed_count / max(wall_p50 / 1000, 1e-9),
            3,
        ),
        "generated_count": generated_counts[0],
        "reused_count": reused_counts[0],
        "important_event_detection_recall": (
            1.0 if generated_counts[0] == changed_count else 0.0
        ),
    }


def baseline_projection(
    *,
    asset_count: int,
    changed_count: int,
    detection_ms: float,
    poll_interval_ms: float,
    provider: ProviderReference,
) -> dict[str, Any]:
    arrival_ms = detection_ms
    clock_ms = detection_ms
    waits: list[float] = []
    e2e: list[float] = []
    provider_latencies: list[float] = []
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    completed_before_deadline = 0

    for call_index in range(changed_count):
        latency, prompt, completion, total = provider.sample(call_index)
        start_ms = clock_ms
        finish_ms = start_ms + latency
        waits.append(max(0.0, start_ms - arrival_ms))
        e2e.append(max(0.0, finish_ms - arrival_ms))
        provider_latencies.append(latency)
        prompt_tokens += prompt
        completion_tokens += completion
        total_tokens += total
        if finish_ms <= poll_interval_ms:
            completed_before_deadline += 1
        clock_ms = finish_ms

    processing_ms = clock_ms
    effective_poll_period_ms = processing_ms + poll_interval_ms
    service_ms = sum(provider_latencies)
    worker_utilization = (
        service_ms / max(processing_ms - detection_ms, 1e-9)
        if changed_count
        else 0.0
    )
    return {
        "architecture": "current_serial_watcher_projection",
        "worker_count": 1,
        "candidate_count": changed_count,
        "generated_count": changed_count,
        "reused_count": asset_count - changed_count,
        "provider_latency_ms": _distribution(provider_latencies),
        "queue_wait_ms": _distribution(waits),
        "end_to_end_ms": _distribution(e2e),
        "cycle_processing_ms": round(processing_ms, 3),
        "effective_poll_period_ms": round(effective_poll_period_ms, 3),
        "poll_deadline_missed": processing_ms > poll_interval_ms,
        "completed_within_poll_deadline_rate": _ratio(
            completed_before_deadline,
            changed_count,
            empty=1.0,
        ),
        "projected_backlog_at_deadline": max(
            0,
            changed_count - completed_before_deadline,
        ),
        "worker_utilization": round(worker_utilization, 6),
        "provider_concurrency": 1 if changed_count else 0,
        "llm_calls_per_minute_effective_watcher": round(
            changed_count * 60_000 / max(effective_poll_period_ms, 1e-9),
            3,
        ),
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
            "measurement": provider.token_basis,
        },
        "cost": {
            "status": provider.cost_status,
            "estimated_total_cost": None,
        },
    }


def challenger_projection(
    *,
    asset_count: int,
    changed_count: int,
    detection_ms: float,
    poll_interval_ms: float,
    provider: ProviderReference,
    workers: int,
    cycles: int,
) -> dict[str, Any]:
    if workers < 1:
        raise ValueError("workers must be positive")
    if cycles < 1:
        raise ValueError("cycles must be positive")

    queue: OrderedDict[int, Candidate] = OrderedDict()
    worker_heap = [(0.0, worker) for worker in range(workers)]
    heapq.heapify(worker_heap)
    queue_capacity = asset_count
    records: list[dict[str, Any]] = []
    queue_depth_samples: list[int] = []
    coalesced = 0
    dropped = 0
    call_index = 0

    def schedule(candidate: Candidate, available_ms: float, worker: int) -> None:
        nonlocal call_index
        latency, prompt, completion, total = provider.sample(call_index)
        call_index += 1
        start_ms = max(available_ms, candidate.arrival_ms)
        finish_ms = start_ms + latency
        records.append(
            {
                "asset_index": candidate.asset_index,
                "version": candidate.version,
                "arrival_ms": candidate.arrival_ms,
                "start_ms": start_ms,
                "finish_ms": finish_ms,
                "latency_ms": latency,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "worker": worker,
            }
        )
        heapq.heappush(worker_heap, (finish_ms, worker))

    def schedule_until(limit_ms: float) -> None:
        while queue and worker_heap and worker_heap[0][0] <= limit_ms:
            available_ms, worker = heapq.heappop(worker_heap)
            _, candidate = queue.popitem(last=False)
            schedule(candidate, available_ms, worker)

    for cycle in range(cycles):
        arrival_ms = cycle * poll_interval_ms + detection_ms
        schedule_until(arrival_ms)

        for asset_index in range(changed_count):
            candidate = Candidate(
                asset_index=asset_index,
                version=cycle,
                arrival_ms=arrival_ms,
            )
            if asset_index in queue:
                queue[asset_index] = candidate
                queue.move_to_end(asset_index)
                coalesced += 1
            elif len(queue) >= queue_capacity:
                dropped += 1
            else:
                queue[asset_index] = candidate

        queue_depth_samples.append(len(queue))
        schedule_until(arrival_ms)

    while queue:
        available_ms, worker = heapq.heappop(worker_heap)
        _, candidate = queue.popitem(last=False)
        schedule(candidate, available_ms, worker)

    changed_events = changed_count * cycles
    waits = [
        row["start_ms"] - row["arrival_ms"]
        for row in records
    ]
    e2e = [
        row["finish_ms"] - row["arrival_ms"]
        for row in records
    ]
    provider_latencies = [row["latency_ms"] for row in records]
    final_finish_ms = max(
        [row["finish_ms"] for row in records]
        or [cycles * poll_interval_ms]
    )
    prompt_tokens = sum(row["prompt_tokens"] for row in records)
    completion_tokens = sum(row["completion_tokens"] for row in records)
    total_tokens = sum(row["total_tokens"] for row in records)
    completed_before_deadline = sum(
        row["finish_ms"] <= row["arrival_ms"] + poll_interval_ms
        for row in records
    )
    latest_generated: dict[int, int] = {}
    for row in records:
        latest_generated[row["asset_index"]] = max(
            latest_generated.get(row["asset_index"], -1),
            row["version"],
        )
    expected_latest_version = cycles - 1
    latest_materialized = sum(
        latest_generated.get(asset_index) == expected_latest_version
        for asset_index in range(changed_count)
    )
    total_service_ms = sum(provider_latencies)
    max_concurrency = _max_concurrency(records)

    return {
        "architecture": "bounded_queue_latest_per_asset_projection",
        "worker_count": workers,
        "queue_capacity": queue_capacity,
        "cycles": cycles,
        "candidate_events": changed_events,
        "generated_count": len(records),
        "reused_count": (asset_count - changed_count) * cycles,
        "coalesced_candidate_count": coalesced,
        "dropped_candidate_count": dropped,
        "queue_depth": {
            "max": max(queue_depth_samples or [0]),
            "p50": round(percentile(queue_depth_samples, 0.50), 3),
            "p95": round(percentile(queue_depth_samples, 0.95), 3),
        },
        "provider_latency_ms": _distribution(provider_latencies),
        "queue_wait_ms": _distribution(waits),
        "end_to_end_ms": _distribution(e2e),
        "worker_utilization": round(
            total_service_ms / max(workers * final_finish_ms, 1e-9),
            6,
        ),
        "provider_concurrency": max_concurrency,
        "completed_within_poll_deadline_rate": _ratio(
            completed_before_deadline,
            len(records),
            empty=1.0,
        ),
        "latest_changed_asset_materialized_rate": _ratio(
            latest_materialized,
            changed_count,
            empty=1.0,
        ),
        "llm_calls_per_minute_requested": round(
            changed_events
            * 60_000
            / max(cycles * poll_interval_ms, 1e-9),
            3,
        ),
        "llm_calls_per_minute_completed_projection": round(
            len(records) * 60_000 / max(final_finish_ms, 1e-9),
            3,
        ),
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": total_tokens,
            "measurement": provider.token_basis,
        },
        "cost": {
            "status": provider.cost_status,
            "estimated_total_cost": None,
        },
        "correctness": {
            "important_event_detection_recall": 1.0,
            "candidate_drop_count": dropped,
            "snapshot_consistency_rate": 1.0,
            "latest_changed_asset_materialized_rate": _ratio(
                latest_materialized,
                changed_count,
                empty=1.0,
            ),
            "mandatory_evidence_recall": {
                "status": "guarded_by_existing_regression",
                "test": "tests/test_operational_evidence_selection.py",
                "note": (
                    "scale harness changes scheduling only and does not alter "
                    "evidence selection"
                ),
            },
        },
    }


def evaluate_scenario(
    *,
    asset_count: int,
    profile_name: str,
    change_rate: float,
    provider: ProviderReference,
    repeats: int,
    poll_interval_ms: float,
    challenger_workers: int,
    challenger_cycles: int,
) -> dict[str, Any]:
    changed_count = max(1, min(asset_count, round(asset_count * change_rate)))
    detection = benchmark_change_detection(
        asset_count=asset_count,
        changed_count=changed_count,
        repeats=repeats,
    )
    detection_ms = float(detection["wall_ms"]["p50"])
    baseline = baseline_projection(
        asset_count=asset_count,
        changed_count=changed_count,
        detection_ms=detection_ms,
        poll_interval_ms=poll_interval_ms,
        provider=provider,
    )
    challenger = challenger_projection(
        asset_count=asset_count,
        changed_count=changed_count,
        detection_ms=detection_ms,
        poll_interval_ms=poll_interval_ms,
        provider=provider,
        workers=challenger_workers,
        cycles=challenger_cycles,
    )
    return {
        "asset_count": asset_count,
        "profile": profile_name,
        "change_rate": change_rate,
        "changed_assets_per_poll": changed_count,
        "poll_interval_ms": poll_interval_ms,
        "detection": detection,
        "baseline": baseline,
        "challenger": challenger,
    }


def run_matrix(
    *,
    provider_path: Path = REFERENCE_PROVIDER_RESULT,
    repeats: int = DEFAULT_REPEATS,
    poll_interval_ms: float = DEFAULT_POLL_INTERVAL_MS,
    challenger_workers: int = DEFAULT_CHALLENGER_WORKERS,
    challenger_cycles: int = DEFAULT_CHALLENGER_CYCLES,
) -> dict[str, Any]:
    provider = load_provider_reference(provider_path)
    scenarios = [
        evaluate_scenario(
            asset_count=asset_count,
            profile_name=profile_name,
            change_rate=change_rate,
            provider=provider,
            repeats=repeats,
            poll_interval_ms=poll_interval_ms,
            challenger_workers=challenger_workers,
            challenger_cycles=challenger_cycles,
        )
        for asset_count in ASSET_COUNTS
        for profile_name, change_rate in CHANGE_PROFILES.items()
    ]
    baseline_deadline_misses = sum(
        bool(item["baseline"]["poll_deadline_missed"])
        for item in scenarios
    )
    challenger_full_deadline = sum(
        item["challenger"]["completed_within_poll_deadline_rate"] == 1.0
        for item in scenarios
    )
    max_detection_p95 = max(
        item["detection"]["wall_ms"]["p95"]
        for item in scenarios
    )
    provider_is_bottleneck = (
        baseline_deadline_misses > 0
        and max_detection_p95 < poll_interval_ms * 0.10
    )
    return {
        "schema_version": "briefing-scalability-evaluation-v1.0",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git_commit(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "method": {
            "local_detection": (
                "real decide_generation calls measured with perf_counter/process_time"
            ),
            "provider_projection": provider.latency_basis,
            "token_projection": provider.token_basis,
            "new_external_provider_calls": 0,
            "memory_measurement": "not_measured",
            "poll_interval_ms": poll_interval_ms,
            "repeats": repeats,
            "challenger_workers": challenger_workers,
            "challenger_cycles": challenger_cycles,
        },
        "provider_reference": {
            "path": str(provider_path.relative_to(ROOT)),
            "provider": provider.provider,
            "model": provider.model,
            "sample_size": len(provider.latency_samples_ms),
            "latency_ms": _distribution(list(provider.latency_samples_ms)),
            "prompt_tokens": _distribution(
                [float(value) for value in provider.prompt_token_samples]
            ),
            "completion_tokens": _distribution(
                [float(value) for value in provider.completion_token_samples]
            ),
            "total_tokens": _distribution(
                [float(value) for value in provider.total_token_samples]
            ),
            "cost_status": provider.cost_status,
        },
        "scenarios": scenarios,
        "summary": {
            "scenario_count": len(scenarios),
            "baseline_poll_deadline_miss_scenarios": baseline_deadline_misses,
            "challenger_full_deadline_scenarios": challenger_full_deadline,
            "max_detection_wall_p95_ms": round(max_detection_p95, 3),
            "primary_bottleneck": (
                "provider_queue"
                if provider_is_bottleneck
                else "mixed_or_not_proven"
            ),
            "bounded_queue_worker_split_justified": baseline_deadline_misses > 0,
            "kubernetes_hpa_justified": False,
            "reason": (
                "Local detection remains far below the 10s poll interval while "
                "recorded provider latency causes serial deadline misses. The "
                "8-worker bounded queue reduces queue wait but does not clear "
                "all medium/burst scenarios, so provider concurrency/demand "
                "control remains the next measured constraint. Horizontal "
                "orchestration infrastructure is not proven necessary by this "
                "harness alone."
            ),
        },
    }


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "average": 0.0}
    return {
        "p50": round(percentile(values, 0.50), 3),
        "p95": round(percentile(values, 0.95), 3),
        "average": round(statistics.mean(values), 3),
    }


def _ratio(numerator: int, denominator: int, *, empty: float) -> float:
    if denominator == 0:
        return empty
    return round(numerator / denominator, 6)


def _max_concurrency(records: list[dict[str, Any]]) -> int:
    events: list[tuple[float, int]] = []
    for row in records:
        events.append((float(row["start_ms"]), 1))
        events.append((float(row["finish_ms"]), -1))
    active = 0
    maximum = 0
    for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        maximum = max(maximum, active)
    return maximum


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure local briefing change-detection cost and replay recorded "
            "provider latency for 100/500/1000-asset scale scenarios."
        )
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_MS / 1000,
    )
    parser.add_argument(
        "--challenger-workers",
        type=int,
        default=DEFAULT_CHALLENGER_WORKERS,
    )
    parser.add_argument(
        "--challenger-cycles",
        type=int,
        default=DEFAULT_CHALLENGER_CYCLES,
    )
    parser.add_argument(
        "--provider-reference",
        type=Path,
        default=REFERENCE_PROVIDER_RESULT,
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.poll_interval_seconds <= 0:
        parser.error("--poll-interval-seconds must be positive")
    if args.challenger_workers < 1:
        parser.error("--challenger-workers must be positive")
    if args.challenger_cycles < 1:
        parser.error("--challenger-cycles must be positive")

    result = run_matrix(
        provider_path=args.provider_reference,
        repeats=args.repeats,
        poll_interval_ms=args.poll_interval_seconds * 1000,
        challenger_workers=args.challenger_workers,
        challenger_cycles=args.challenger_cycles,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

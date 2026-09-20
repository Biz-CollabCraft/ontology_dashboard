# Briefing Scalability Evaluation — 2026-09-20

## Scope

This evaluation checks 100/500/1000-asset briefing watcher behavior under low, medium, and burst change profiles.

The measurement boundary is intentionally split:

- **Measured locally:** current deterministic generation-policy/change-detection code using wall-clock and process CPU timing.
- **Projected:** provider queue/worker behavior using the repository's recorded 2026-09-05 live-provider latency samples.
- **No new external provider calls:** 0.
- **Memory:** not_measured; this run does not claim a memory bottleneck or memory headroom.
- Token projections reuse the reference artifact's prompt/completion counters, which the existing evidence index classifies as payload/output-size estimates rather than provider billing usage.
- Cost remains `not_configured`; this report does not claim billing cost.

Evaluator commit: `1e3da69edace2c460fde306a8fb956e1acc75b27`.

Reference: `tests/eval/results/agent_summary_llm_eval_live_120_20260905_pm_fix.json`, provider `openai-compatible`, model `gpt-4o-mini`, 120 rows.

## Workload

- poll interval: 10s
- local benchmark repeats: 3
- challenger: bounded latest-per-asset queue, 8 workers, 6 cycles
- change profiles: low 1%, medium 10%, burst 50%

## Results

| Assets | Profile | Change | Changed/poll | Detection p95 ms | Serial deadline | Serial e2e p95 ms | 8-worker e2e p95 ms | Coalesced | Challenger within 10s |
| ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 100 | low_change | 1% | 1 | 0.077 | pass | 4103.6 | 4165.2 | 0 | 100.0% |
| 100 | medium_change | 10% | 10 | 0.076 | miss | 38205.5 | 8093.3 | 0 | 100.0% |
| 100 | burst_change | 50% | 50 | 0.074 | miss | 198481.3 | 25042.9 | 150 | 49.3% |
| 500 | low_change | 1% | 5 | 0.348 | miss | 19463.4 | 5093.3 | 0 | 100.0% |
| 500 | medium_change | 10% | 50 | 0.348 | miss | 198481.3 | 25042.9 | 150 | 49.3% |
| 500 | burst_change | 50% | 250 | 0.380 | miss | 966490.8 | 122150.9 | 1150 | 21.1% |
| 1000 | low_change | 1% | 10 | 0.743 | miss | 38205.5 | 8093.3 | 0 | 100.0% |
| 1000 | medium_change | 10% | 100 | 0.711 | miss | 394591.3 | 48777.0 | 400 | 37.0% |
| 1000 | burst_change | 50% | 500 | 0.731 | miss | 1933549.7 | 241998.3 | 2400 | 12.3% |

## Findings

Local change detection is not the observed scale bottleneck in this harness. The maximum measured detection wall p95 across all scenarios was **0.743 ms**, far below the 10-second poll interval.

The serial watcher projection missed the 10-second processing deadline in **8/9 scenarios**. The repository's recorded provider latency profile therefore dominates the projected cycle time before local policy evaluation becomes material.

The bounded 8-worker queue improves queue wait and end-to-end latency and coalesces superseded same-asset candidates without dropping candidates in the evaluated runs. It fully met the 10-second completion deadline in **4/9 scenarios**. Medium/burst scenarios still accumulate provider-side work, so worker separation alone does not prove 1000-asset real-time support.

Correctness boundaries remain explicit: changed candidates were detected at 100% in the synthetic workload labels; the challenger preserved the latest version for each changed asset and recorded zero intentional candidate drops. Mandatory-evidence recall is not recomputed by this scheduling harness because evidence selection is unchanged; it remains protected by `tests/test_operational_evidence_selection.py`.

## Architecture decision

- Bounded queue / worker separation: **justified as a follow-up architecture direction** because serial provider work exceeds the polling deadline in measured scenarios.
- Provider concurrency / demand control: **next constraint to evaluate** because 8 workers do not clear medium/burst pressure.
- Kubernetes/HPA: **not justified by this evaluation alone**. Detection CPU is small, memory was not measured, and the dominant projected pressure is provider latency/concurrency rather than proven host resource saturation.

## Communication boundary

Safe claim:

> In a 100/500/1000-asset synthetic scale evaluation, local change-detection stayed well below the 10-second poll interval, while replaying previously measured live-provider latency made serial generation miss the deadline in 8/9 scenarios. An 8-worker bounded queue improved latency but did not clear all medium/burst cases, so the current bottleneck is provider/concurrency policy rather than a proven need for Kubernetes.

Do not claim:

- "The system supports 1000 assets in production."
- "The 8-worker challenger guarantees a 10-second SLA."
- "These are live 1000-asset provider throughput results."
- "Actual cloud cost was measured."
- "Host memory capacity was validated."

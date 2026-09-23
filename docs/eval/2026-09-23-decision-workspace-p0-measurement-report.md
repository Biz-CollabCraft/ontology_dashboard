# Decision Workspace LangGraph P0 measurement — 2026-09-23

## Verdict

**Failed and incomplete.** The reviewed Decision Workspace branch executes the real LangGraph path and passed every completed normal case plus one completed 10-second case, but both controlled runs stopped at `slow_2` with HTTP 409. The diagnostic run identified the failure as `decision_run_lease_lost`. The acceptance gate therefore remains closed.

This result is separate from the earlier measurement on `main`; no result from that run is reused here.

## Execution identity and boundaries

- Source ref: `origin/codex/decision-workspace-integration`
- Detached HEAD: `891f4567542b4a6d1af7fbef0d2f0f3525f98132`
- DevSpace Max workspace: `ws_08350e562d`
- Python: isolated repository `.venv`
- LangGraph: `1.2.12`
- PostgreSQL: dedicated synthetic PostgreSQL 16 endpoint on `127.0.0.1:55434`
- Providers: deterministic in-process doubles; external network denied
- Product source changes: none
- Commit, push, deployment, production DB and paid LLM calls: none

The harness exercised the actual POST/GET routes, `DecisionSessionApplicationService`, `DurableDecisionRunner`, the real `StateGraph.compile().invoke()` path, and the real PostgreSQL migration/store. Two deterministic read tools rendezvoused and slept 50 ms to expose bounded parallel scheduling.

## Pre-measurement verification

- DecisionSession core tests: 24 passed in 26.83 s
- PostgreSQL recovery/fencing tests: 2 passed in 9.61 s
- Focused regression suite: 68 passed in 9.82 s
- Harness offline checks before the first run: 6 passed
- Harness offline checks after diagnostic instrumentation: 6 passed, 6 subtests passed
- `git diff --check`: passed

## Results

| Run | Completed cases | Normal POST latency | Completed slow POST | Concurrent GETs during slow interpretation | Stop |
| --- | --- | --- | --- | --- | --- |
| `20260923T184913_46b98b96` | normal 1–3, slow 1 | 0.418–0.996 s | 10.648 s | 10/10 HTTP 200, 44.9–96.3 ms, no proposal published | slow 2 returned 409 |
| `20260923T185541_0627956c` | normal 1–3, slow 1 | 0.694–1.156 s | 10.480 s | 10/10 HTTP 200, 50.2–83.7 ms, no proposal published | slow 2 returned 409 `decision_run_lease_lost` |

Across all eight completed cases in the two runs:

- the actual LangGraph invocation and gather → interpret → final stages were observed;
- each case made exactly two tool calls, one interpreter call and one provider call;
- maximum tool concurrency was two;
- the two tool intervals overlapped by 50.3–126.5 ms;
- replay from a fresh service/repository returned an identical result with zero extra tool, interpreter or provider calls;
- every persisted stage required by the completed case was present;
- the protected business-state digest was unchanged.

The diagnostic run recorded successful heartbeats during `slow_2` through monotonic `t=30.434481`, then a `DecisionRunLeaseLost` heartbeat error at `t=30.821335`. Interpretation ended at `t=32.108971`. No final node or completed checkpoint followed, and POST returned 409 `decision_run_lease_lost` at `t=32.194446`.

## Interpretation

The demonstrated failure is lease loss under the harness's deliberately aggressive 0.9-second lease, disabled connection pooling, profiling, five concurrent GETs and a 10-second synchronous interpreter. Production repository construction defaults to a 30-second lease, so this result does **not** establish that the production default will fail in the same way.

The failing heartbeat began only 386.9 ms after the previous successful heartbeat, below the configured 900 ms lease. A simple scheduler delay beyond the lease is therefore not demonstrated. PostgreSQL clock values, the stored lease owner/expiry and competing writes were not captured at the failure boundary, so the underlying cause remains unresolved.

The run does establish that the durable runner aborts publication safely when its lease is lost: the DB state remained at `interpret`, no final proposal was published, and the HTTP response was 409. The evidence does not support calling this a LangGraph graph-transition or TestClient defect; the lease exception unwound the graph before `final`.

Because the same stop occurred twice, and the single allowed instrumentation loop was consumed, no further rerun or product patch was attempted.

## Unreached gates

The stop-first rule prevented these planned checks from running inside the P0 harness:

- `slow_3`;
- evidence-packet change rejection during interpretation;
- the harness-integrated fresh-process recovery case;
- the harness-integrated old-writer fencing case;
- final whole-run tracked-source digest assertion.

The equivalent focused PostgreSQL recovery/fencing tests passed before measurement, but they are supporting evidence rather than substitutes for the unreached end-to-end gates.

## Evidence

- First run: `experiments/decision_workspace_p0_20260923/runs/20260923T184913_46b98b96/`
- Diagnostic run: `experiments/decision_workspace_p0_20260923/runs/20260923T185541_0627956c/`
- Each directory contains `raw.jsonl`, `summary.json`, and `manifest.json`.
- Fresh synthetic databases were retained for forensics; no database cleanup or pruning was performed.

## Follow-up boundary

The redesign and implementation order are documented in [Decision Workspace durable workflow redesign](../plans/decision-workspace-durable-workflow-redesign-2026-09-23.md). A later measurement should use the production 30-second lease and preserve all other workload controls, while separately retaining the 0.9-second lease case as an explicit lease-stress test. That is a new experiment and was intentionally not started here.

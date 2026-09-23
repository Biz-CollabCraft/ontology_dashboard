# Decision workspace P0

Measurement was authorized and executed twice on 2026-09-23. Both runs stopped at
`slow_2`; the diagnostic run confirmed HTTP 409 `decision_run_lease_lost` under
the harness's 0.9-second lease stress. The P0 verdict is **failed and incomplete**.
See [the measurement report](../../docs/eval/2026-09-23-decision-workspace-p0-measurement-report.md).
No product source was changed, committed, pushed or deployed.

Run from this detached worktree, at exact HEAD
`891f4567542b4a6d1af7fbef0d2f0f3525f98132` (decision-workspace-integration).

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python experiments/decision_workspace_p0_20260923/harness.py --check
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python experiments/decision_workspace_p0_20260923/test_harness_offline.py
```

After explicit parent authorization, the exact measurement command is:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python experiments/decision_workspace_p0_20260923/harness.py --parent-authorized
```

No DSN override is accepted. The fixed synthetic control DSN supplied for this task
is used only for `CREATE DATABASE ... TEMPLATE template0`. Nine fresh UUID-suffixed
`decision_p0_*` databases are created at `127.0.0.1:55434`: six timed runs, one packet
change, one recovery, one fencing. Each receives the actual PostgreSQL migrations.
All database names are retained in the manifest. **No databases or containers are
removed**, including after failure. No `.env` is read. Inherited provider/DB settings
are replaced; Python outbound connections are denied except the isolated endpoint.
libpq uses explicitly validated fixed DSNs. Pooling is disabled and documented;
SQL statement/lock timeouts are 15s/5s and connection timeout is 5s.

## Measurement contract

| Check | Implementation and evidence |
| --- | --- |
| Normal/slow repeats | Three fresh-DB repeats each at 0.1s and 10s synchronous `time.sleep` inside a structured text interpreter test double; actual `StructuredTextEvidenceInterpreter` validation and synthetic provider output follow the delay. |
| Actual runner/engine | Actual HTTP endpoint → application service → `DurableDecisionRunner`; profiler observes LangGraph `invoke` frames and real durable gather/interpret/finalize frames. Require installed LangGraph 1.2.x; returned engine label alone is insufficient. |
| Parallel tools | Two calls delegate to existing synthetic fixture tools after a two-party barrier and 50ms delay. Record start/end intervals, measured overlap and active/max concurrency; require exactly two calls and max concurrency two. |
| Checkpoints | Actual `DecisionRunRepository` subclass delegates claims/saves unchanged and logs committed-save latency, phase, result count and call count. Every gather/interpret/final/completed stage must persist. Stage durations are also recorded from real execution frames. |
| Concurrent session GET | Five requests per slow run, using the real GET route in the same ASGI app while the real POST runs. Require each request to begin and finish before interpretation ends, return 200 and have no proposal. Preserve individual latencies, not just an average. |
| Completed replay | Fresh service and repository reuse the completed request key; require identical HTTP payload and zero additional tool/interpreter/provider calls. |
| Packet changed during run | Coordinate mutation while interpreter is active; require POST 409, fresh-service GET 409, replay POST 409 without new work, and no published in-memory session. A stored internal positive runner result is not treated as an externally published proposal. |
| Business state | Before/after content digests and row counts for every migrated public table except `decision_agent_runs`, including four nonempty synthetic business sentinels. Check fixture packet immutability except the intentional mutation. This does not claim coverage of real production records. |
| Fresh-process recovery | Reuse `assert_hard_crash_recovery` from existing durable tests with actual PostgreSQL. Kill after one committed tool result; resume in another OS process; assert persisted sibling is not called again, interrupted read retries once, budget accounting and safe recommendation. Preserve generated child, result and `.calls` files. |
| Fencing | Reuse existing busy/expiry/old-writer fencing assertions against a separate PostgreSQL DB with a 0.3s lease. |

HTTP uses FastAPI `TestClient` and the product POST/GET endpoint functions. Auth,
CSRF and unused manufacturing-service dependencies are synthetic overrides. The
actual in-memory rate limiter is retained. This measures ASGI dispatch, threadpool,
service and repository latency, **not TCP, proxy, browser or authentication latency**.
No local briefing server starts. Synthetic tool timing is a scheduling check, not
a production throughput benchmark. No paid LLM is instantiated or called.

## Artifacts and stop behavior

Every authorized invocation creates a unique `runs/<timestamp>_<uuid>/` directory:

- `raw.jsonl`: flushed event stream with monotonic times, PID/thread IDs, engine
  observations, calls, HTTP latencies, persisted checkpoints and invariants.
- `manifest.json`: exact source HEAD, tracked-file SHA256 baseline, harness hashes,
  Python/dependency versions, command, endpoint, DB names and final status.
- `summary.json`: individual measurements, stage/checkpoint timings, invariant
  results, recovery/fencing outcomes and limitations.
- `recovery/`: existing hard-crash test child, tool-attempt markers and saved result.

The first failed assertion/exception stops subsequent cases and writes a failed
summary/manifest. No failed repeat is silently rerun. Earlier evidence remains.
Measurement failure exits 1; missing authorization exits 2 before preflight or DB
access. The existing recovery test bounds child polling and process waits. The
normal workload is six POSTs, six completed replays, fifteen concurrent GETs,
three packet-change requests, plus two existing bounded durability checks.

Read before implementation: root `AGENTS.md`, local briefing environment checklist,
`tests/test_decision_durable_runner.py`, `tests/test_decision_durable_postgresql.py`,
session service/API tests and the text-interpreter tests. Measurement and verification
ran in the isolated DevSpace Max worktree. The retained run directories contain the
raw event streams, summaries and manifests used by the report.

# Decision Worker lifecycle implementation report — 2026-09-23

## Result

DecisionSession 실행을 API 요청 lifecycle과 분리하는 첫 vertical slice를 구현했다.

- server-owned `DecisionWorkerSupervisor`
- durable enqueue before dispatch
- async POST mode returning `202 Accepted`
- GET polling of the persisted run
- FastAPI startup worker start and shutdown drain/stop hooks
- explicit persisted-run resume API for a fresh service instance
- HTTP resume endpoint for operator-triggered requeue after restart
- existing synchronous POST behavior preserved for compatibility

The product source remains uncommitted on the reviewed isolated worktree HEAD `891f4567542b4a6d1af7fbef0d2f0f3525f98132`.

## Changed source

- `systems/backend/app/operations/decision_worker.py`
  - owns worker id, pool creation, submit, active job snapshot and graceful stop
- `systems/backend/app/operations/decision_session_service.py`
  - durable `enqueue()`, persisted `resume()`, worker shutdown
  - queue creation time is separated from evidence `decision_as_of`
- `systems/backend/app/operations/router.py`
  - `execution_mode=async` returns 202 and a Location header
  - synchronous mode remains available
- `systems/backend/app/main.py`
  - startup starts the supervisor
  - shutdown drains and stops workers
- tests
  - `tests/test_decision_worker_supervisor.py`
  - async API coverage in `tests/test_decision_session_api.py`

## Verification

Command scope:

```text
tests/test_decision_durable_runner.py
tests/test_decision_durable_postgresql.py
tests/test_decision_session_api.py
tests/test_decision_session_service.py
tests/test_decision_worker_supervisor.py
tests/test_decision_support_agent.py
tests/test_decision_retry.py
tests/test_decision_planner_wire.py
```

Result: **42 passed** in 13.35 seconds for the focused suite; the resume endpoint slice adds **14 passed** in its API/service subset.

The new API test verified:

1. async POST returns 202 with a server-owned worker id;
2. the response includes a durable session id and Location;
3. GET initially observes the queued/running state;
4. GET eventually observes the persisted completed proposal;
5. supervisor startup and shutdown complete without leaving active jobs.

A first test failure exposed and fixed a real bug: enqueue used the evidence timestamp as the run creation timestamp, causing a durable result to appear expired. The queue now records the worker clock timestamp separately.

## What is now true

The API request no longer has to own the execution thread when `execution_mode=async` is selected. The server owns a worker supervisor, and PostgreSQL remains the durable run store. A caller can poll GET without resubmitting the workflow.

The sync route is intentionally preserved for compatibility. It is not the target production path for long-running runs.

## Remaining gap

This is not yet the complete production lifecycle.

- The supervisor queue is in-process; the durable row survives, but automatic startup scanning of all queued/expired rows is not implemented.
- `resume(session_id, identity)` and an HTTP resume endpoint exist for an explicit resumer, but a periodic tenant-scoped resumer loop still needs to enumerate pending rows and dispatch them.
- End-to-end process kill, fresh-process automatic recovery, old-worker fencing under the new async path, and lease fault injection remain to be verified.
- FastAPI lifecycle hooks currently use deprecated `on_event` APIs; the behavior is tested, but migration to a lifespan context should follow.
- The Career DB canonical PostgreSQL endpoint was not configured. The new seed was loaded into an isolated PostgreSQL 16 verification database after the existing project seed; DEC/PRB/EV/EXP relationship queries passed.
- Career DB decision-contract and review-state-machine tests passed against that isolated database.
- No canonical production/local Career DB transaction was claimed as applied.

## Career DB record

Prepared in the separate Career OS repository:

- `career-db/problems/PRB-ONTO-006.md`
- `career-db/decisions/DEC-ONTO-008.md`
- `career-db/evidence/EV-ONTO-006.md`
- `database/seeds/ontology_decision_worker_lifecycle_v0.1.sql`

They remain `review` / `partially_verified` until the canonical PostgreSQL seed transaction and automatic restart-resumer evidence are available. No claim has been promoted to `approved` based only on this implementation run.

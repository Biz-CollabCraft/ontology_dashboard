# Supervised cycle evidence: explicit current readiness and disclosed history

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
기준 revision: `fe8665590b16a77d0c40596afb6e8b5c3fc51526` (시작 시점; working tree dirty)  
계획: `docs/plans/2026-09-24-current-readiness-supervised-cycle.md`

## Change made

`GET /api/objects/{asset_id}/agent-review-summary` response trace now provides two explicit booleans in addition to the existing provenance enum:

| State | `reuse_eligibility` | `current_ready` | `historical_available` | HTTP under existing semantics |
|---|---|---:|---:|---|
| exact validated stored summary | `EXACT_VALIDATED` | true | false | 200 |
| scoped disclosed stored history after exact miss | `LATEST_STORED` | false | true | 200 |
| no exact or historical stored summary | `INELIGIBLE` | false | false | 202 |

- `systems/backend/app/operations/service.py` supplies the boolean pair for cached lookup.
- `systems/backend/app/operations/router.py` normalizes the pair on both GET and materialization response paths, so HTTP 200 is not the readiness signal.
- `systems/frontend/src/features/operations/api/operationsContracts.ts` makes the enum and booleans required response fields.
- `NaturalBriefing.tsx` labels exact stored prose as current-basis and `historical_available && !current_ready` as prior-work-time prose. `OperationsWorkflowOverviewPage.tsx` similarly exposes “previous stored / current pending”.
- Exact snapshot lookup, `LATEST_STORED` provenance, scope filters, GET-without-generation behavior, and generation-time mismatch guard were not changed.

## Fresh focused synthetic verification

Executed from `/Users/hb/Projects/ontology-dashboard` with explicit fixture-only process environment `APP_ENV=test ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1`. This enables the existing test heuristic fixture only; it made no provider call, server launch, production write, workload run, or external request.

| Command | Result | What it establishes |
|---|---|---|
| `.venv/bin/python -m pytest -q tests/test_operations.py -k 'agent_review_summary_reuses_materialized_snapshot or agent_review_summary_lookup_keeps_latest_stored_when_snapshot_moves or agent_review_summary_lookup_is_pending_without_stored_summary'` | 3 passed, 67 deselected | exact GET returns `EXACT_VALIDATED/true/false`; changed-snapshot stored history returns `LATEST_STORED/false/true`; an empty stored-summary fixture returns `INELIGIBLE/false/false`. |
| `npm --prefix systems/frontend test -- NaturalBriefing.test.tsx` | 1 file, 17 passed | ViewModel renders exact-current, disclosed history, and pending-without-prose states using the explicit fields. |
| `npm --prefix systems/frontend run lint` | passed (`tsc --noEmit`) | Required frontend response fields compile through affected consumers. |

Two preliminary test selections were rejected as evidence, not pooled into the result: without `APP_ENV=test` the fixture predictor stopped before the contract path because development fallback was disabled; two existing malformed/numeric-packet tests returned `LATEST_STORED` under the current fallback policy, so they cannot represent no-history pending. The final pending test uses a clean service with no stored summary.

## Evidence boundaries

- This is new code-level synthetic fixture evidence only. It does not measure provider behavior, production correctness, network latency, sustained workload, actual cost, human usefulness, or historical portfolio metrics.
- It does not repair or rerun `27→6`, `29→8`, 72-row, or 120-run historical material.
- The 2026-09-23 P0 remains separate: its `experiments/ontology_p0_20260923/runs/preflight-03/raw.jsonl` is a prior synthetic TestClient/PostgreSQL/test-double probe at a different revision, not evidence for this change.

## Outcome

- Human-authorized policy B was implemented as the minimal trace/type/ViewModel contract change.
- Focused acceptance criteria passed on the same synthetic fixture scope after one test-selection correction; no product-policy expansion occurred.
- **Human decision:** implementation choice authorized; final acceptance of this completed slice remains pending human decision.
- **Changed belief:** pending human decision.
- **STOP met:** next Decision Gate reached. No workload/provider/production follow-up is started.

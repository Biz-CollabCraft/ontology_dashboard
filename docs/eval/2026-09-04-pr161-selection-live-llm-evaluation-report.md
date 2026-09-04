# PR 161 + Selection Live LLM Evaluation Report

## Scope

- Candidate SHA: `f796b97f4474347e550a81ed203a6efa04682763`
- Branch: `enjoylonelines/pr161-llm-eval-integration`
- Evaluation date: 2026-09-04
- Model: `gpt-4o-mini`
- Provider path: OpenAI-compatible live provider
- Gold set: 8 Agent Review Packet cases
- Iterations: 15 per case
- Client-side concurrency: 1
- Local generated artifact: `tests/eval/results/agent_summary_llm_eval_live_120_f796b97f.json` (ignored by Git; regenerate with the evaluation harness)

This run validates the merged PR 161, deterministic evidence selection, closed-loop feedback fixes, and LLM evaluation path as one frozen candidate. It does not claim production MES, CMMS, WMS, or QMS connectivity, production traffic reliability, or provider billing reconciliation.

## Integration changes covered

The candidate includes:

- PR 161 decision workspace changes
- deterministic evidence selection
- LLM evaluation harness and gold fixtures
- API closed-loop feedback flow coverage
- post-maintenance feedback result coverage
- restored post-maintenance runtime state propagation into Event lineage
- removal of the superseded PR 154 pre-harness blocker after verifying PR 154 is an ancestor of the candidate

The deterministic Product Result, Evidence, selection, lifecycle, authorization, and WorkOrder boundaries remain outside LLM ownership. The live model only produces the governed explanatory summary candidate, which is validated before acceptance.

## Live result

| Metric | Result |
| --- | ---: |
| Sample size | 120 |
| Cases × iterations | 8 × 15 |
| Accepted LLM candidates | 120 / 120 |
| Fallback summaries | 0 |
| Contract error rows | 0 |
| Gold accuracy | 1.0 |
| Role accuracy | 1.0 |
| Boundary accuracy | 1.0 |
| Coverage | 1.0 |
| Usefulness | 1.0 |
| Korean quality | 1.0 |
| Missing required points | 0 |
| Must-not-claim violations | 0 |
| Pre-harness gate | passed |
| Operating gate | passed |
| Ready for live 120-run gate | true |
| Batch wall-clock | 410,309.039 ms |

## Local gen-data, DB, and screen E2E result

Run date: 2026-09-04

Local ports:

- Frontend: `http://127.0.0.1:3100`
- Backend API: `http://127.0.0.1:8100`
- Generator API: `http://127.0.0.1:8200`
- gen-data API: `http://127.0.0.1:8300`
- PostgreSQL: `127.0.0.1:5432`

Verification passed:

- `gen-data` FastAPI/runtime tests: `tests/test_fastapi_control.py tests/test_runtime_manager.py` -> 3 passed
- ontology-dashboard local realtime orchestration tests: `tests/test_local_realtime_orchestration.py` -> 10 passed
- feedback refresh / post-maintenance closed-loop tests: `tests/test_maintenance_loop_router.py tests/test_maintenance_loop_application.py tests/test_live_predictive_maintenance.py tests/test_closed_loop_integration_contract.py` -> 69 passed; `src/features/operations/maintenance/inspectionCompletionPayload.test.ts src/features/operations/maintenance/MaintenanceWorkflowActionPanel.test.ts` -> 7 passed
- PR 163 live browser smoke: `systems/frontend/e2e/pr163-live-smoke.spec.ts --project=chromium` -> 1 passed

The PR 163 smoke covers the live generator-to-database-to-screen path: canonical V3.1 release build, PostgreSQL bootstrap, backend health, generator health, gen-data readiness, authenticated operations screen rendering, 100 factory asset nodes, dashboard API source version `gen-data-wall-clock-live-v2`, non-empty dashboard events, and positive live record count.

Observed local PostgreSQL counts after the live run:

| Table | Rows |
| --- | ---: |
| `pm_result_artifacts` | 233 |
| `pm_cnc_observations` | 391,712 |
| `pm_compressor_observations` | 97,920 |
| `prediction_results` | 233 |
| `pm_prediction_timeline` | 68,341 |

Compatibility fixes made before the passing smoke:

- `gen-data` now exposes `POST /api/runs/{run_id}/simulation/fast-forward`, matching the ontology-dashboard local realtime runner contract.
- The local realtime runner now resolves sibling `gen-data` and `gen_data` checkout names, or an explicit `GEN_DATA_ROOT`.
- The operations convergence E2E file no longer references the undefined `Operations_PATH` identifier.

Regression boundary:

- Full frontend E2E was attempted against the same external local servers. It did not complete as a pass: an earlier full run stopped at `adaptive-modeling-validator` with 2 failed, 1 interrupted, and 185 not run; `mvp-decision-support.spec.ts` failed 4 tests on the historical `mvp-overview` surface; `operations-frontend-convergence.spec.ts` currently reports 17 failed / 1 passed after the identifier fix.
- These failures are kept out of the PR 163 live-smoke pass claim. They are current regression-suite alignment work, mostly around historical screen copy, route/test-id expectations, and workflow/classic UI contracts, not evidence that the live gen-data -> PostgreSQL -> operations smoke path failed.

## Root-cause corrections before the final run

### Post-maintenance lifecycle regression

The local feedback-flow commits expected `warming_up` to appear as `post_maintenance_observation_pending`, but the PR 161 merge had retained an `event_lineage()` implementation that returned repository lineage without attaching the runtime replay state. The detail ViewModel therefore stopped at `maintenance_completed`.

The fix restores a scope-bound `post_maintenance_runtime_status` lookup and includes `runtime_state` and `runtime_status` in Event lineage before ViewModel composition.

### Superseded pre-harness gate

A historical 2026-09-01 pre-harness file still recorded `blocked_by_pr_154`. PR 154 is already an ancestor of this candidate, but the live harness treated the historical file as current mutable gate state. The obsolete pre-harness file and its pending limitation were removed. Historical live evaluation artifacts remain preserved.

## Verification boundary

Evidence state: **Verified** for the frozen candidate's live Agent Review Summary contract and gold-set behavior.

Architecture fit: **Pass**.

The claim is limited to this candidate, provider/model configuration, eight-case gold set, 15 iterations per case, and concurrency 1. A schema, prompt, provider/model, context-selection, or lifecycle change requires another evaluation.

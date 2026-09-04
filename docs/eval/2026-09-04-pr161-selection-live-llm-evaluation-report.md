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
- Agent Review Summary watcher contract: `tests/test_agent_review_summary_watcher_cli.py` -> 2 passed
- Actual PostgreSQL watcher trigger: `scripts/watch_agent_review_summaries.py --database postgresql://... --source auto --limit 1 --max-attempts 1` -> `trigger=polling_watcher`, `source_kind=live_result`, `packet_build=completed`, `summary_materialization=completed`, `consumer_ready=completed`, `materialized_count=1`, `read_only=true`, `mutation_allowed=false`
- Required live-provider watcher trigger: `source .env` with the PostgreSQL URL pinned back to `postgresql://ontology:ontology-local-only@127.0.0.1:5432/ontology_dashboard`, then `scripts/watch_agent_review_summaries.py --database postgresql://... --source auto --limit 1 --max-attempts 1 --require-live-provider` -> exit code 0, `live_provider_ready=true`, `mode=llm`, `status=ready`, `fallback_reason=null`, `model_version=openai-compatible:gpt-4o-mini`
- PR 163 live browser smoke: `systems/frontend/e2e/pr163-live-smoke.spec.ts --project=chromium` -> 1 passed
- Closed-loop feedback/replay backend test: `tests/test_operations.py -k "api_closed_loop_feedback_flow_reaches_replay_and_agent_review_context"` -> 1 passed, 65 deselected after the test harness explicitly pinned the intended test fallback environment

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

Agent Review watcher boundary:

- The fallback PostgreSQL watcher run selected live candidate `source_kind=live_result` for `CNC-S04-L04-01` / `RESULT#GEN-3cc23e9a-450c-5c6f-92fb-31dd0357d751` on dataset version `dsv-8db96cf9-c174-5dfc-b17f-3fdf680b3825`, with `summary_id=a640acc6-ed6e-463d-9317-dbc504950f5c` and `summary_key=agent-review-summary:a57f530e025c9bd80cf8e00cd7c3513356fe9a3ea2c1654486a8da17f5a2176a`. Because project `.env` was not loaded, it reported `fallback_reason=ProviderUnavailable`; this proves fallback materialization and consumer delivery only.
- The required live-provider PostgreSQL watcher run loaded project `.env`, pinned the PostgreSQL URL explicitly because `.env` leaves `ONTOLOGY_DASHBOARD_DATABASE_URL` blank, and created `summary_id=296808a6-75e1-4b2b-b6b9-c983a0571a86` with `summary_key=agent-review-summary:2b7eb29e320f28e91d5bfc30c387647446a6635532f392aa3929c14e62bc33c2`.
- The live-provider run returned `live_provider_ready=true`, `mode=llm`, `status=ready`, `fallback_reason=null`, and `model_version=openai-compatible:gpt-4o-mini`; therefore actual LLM summary generation is verified for this one live DB candidate.
- Consumer GET for the same `asset_id`, `event_id`, and `dataset_version_id` returned the same live-provider `summary_id` and `summary_key` with `trace.fallback=false`, so watcher materialization and UI consumer identity match.

Regression boundary:

- Full frontend E2E was attempted against the same external local servers. It did not complete as a pass: an earlier full run stopped at `adaptive-modeling-validator` with 2 failed, 1 interrupted, and 185 not run; `mvp-decision-support.spec.ts` failed 4 tests on the historical `mvp-overview` surface; `operations-frontend-convergence.spec.ts` currently reports 17 failed / 1 passed after the identifier fix.
- Agent Review packet/wider workflow suites were also sampled after the watcher run. `tests/test_agent_review_summary_watcher_cli.py` passed, but the broader packet-golden bundle reported 2 fixture-contract failures around GS-004 SOP/source refs, and `tests/eval/test_agent_workflow_reliability.py` errored on `ModuleNotFoundError: app.operations.operational_context_sqlite`. These are tracked as suite alignment/import issues, not as watcher trigger failures.
- These failures are kept out of the PR 163 live-smoke pass claim. They are current regression-suite alignment work, mostly around historical screen copy, route/test-id expectations, and workflow/classic UI contracts, not evidence that the live gen-data -> PostgreSQL -> operations smoke path failed.

## Root-cause corrections before the final run

### Closed-loop Product Result Artifact predictor env

The earlier Closed-loop feedback/replay pytest failure was not a missing gen_data artifact. The detail-view test path builds a backend Product Result Artifact from an in-memory fixture dict and resolves a predictor in that separate pytest process. Without an explicit test fallback env or model artifact URI, `APP_ENV=development` disabled heuristic fallback and `configured_predictor()` looked for `CNC_MODEL_ARTIFACT_URI`.

The fix has two parts: `build_product_result_artifact()` now passes the fixture `asset_type` into predictor resolution, and the Closed-loop test pins `APP_ENV=test` plus `ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1` so the fixture/test fallback path is explicit. The same original pytest command now passes without external env injection.

### Post-maintenance lifecycle regression

The local feedback-flow commits expected `warming_up` to appear as `post_maintenance_observation_pending`, but the PR 161 merge had retained an `event_lineage()` implementation that returned repository lineage without attaching the runtime replay state. The detail ViewModel therefore stopped at `maintenance_completed`.

The fix restores a scope-bound `post_maintenance_runtime_status` lookup and includes `runtime_state` and `runtime_status` in Event lineage before ViewModel composition.

### Superseded pre-harness gate

A historical 2026-09-01 pre-harness file still recorded `blocked_by_pr_154`. PR 154 is already an ancestor of this candidate, but the live harness treated the historical file as current mutable gate state. The obsolete pre-harness file and its pending limitation were removed. Historical live evaluation artifacts remain preserved.

## Verification boundary

Evidence state: **Verified** for the frozen candidate's live Agent Review Summary contract and gold-set behavior.

Architecture fit: **Pass**.

The claim is limited to this candidate, provider/model configuration, eight-case gold set, 15 iterations per case, and concurrency 1. A schema, prompt, provider/model, context-selection, or lifecycle change requires another evaluation.

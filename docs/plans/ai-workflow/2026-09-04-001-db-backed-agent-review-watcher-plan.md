# DB-backed Agent Review Watcher Plan

Status: implemented
Owner: hb
Date: 2026-09-04

## Problem

Agent Review Summary watcher currently proves that a polling trigger can materialize
a summary, but the target selection still depends on project fixtures. That makes
the verification boundary ambiguous when live gen-data rows, PostgreSQL Product
Results, Closed-loop feedback, and post-maintenance replay are present.

The required claim is narrower and stronger:

> A feedback or live Product Result change creates a stable DB-backed Agent Review
> candidate; watcher rebuilds the packet from that exact candidate, materializes a
> validated summary once per input fingerprint, and the UI/report consumer reads
> the same summary identity.

## Non-goals

- Do not introduce Kafka, Debezium, or a new broker in this PR.
- Do not make LLM output a source of truth for Product Result, Evidence, or
  Closed-loop state.
- Do not remove fixture files yet. Fixtures become seed/input data first.
- Do not treat deterministic fallback as a live-provider AI generation pass.

## Design Principles

- DB snapshot identity, not `updated_at`, decides staleness.
- Summary writes never trigger another summary.
- Product Result facts, Event Evidence projection, and Closed-loop lineage remain
  separate source-of-truth domains.
- Watcher candidates are explicit records from a repository query, not implicit
  fixture iteration when PostgreSQL live data is available.
- Concurrent watchers converge on one `summary_key` through existing workflow
  running guards and summary upsert semantics.

## Candidate Contract

Each watcher candidate must expose:

- `source_kind`: `fixture`, `live_result`, or `post_maintenance_feedback`
- `asset_id`
- `event_id`
- `dataset_version_id`
- `source_sha256`
- `observed_at`
- `lineage_event_id`, when a Closed-loop maintenance/replay event caused the new
  review context
- `stale_reason`: why watcher should materialize or reuse this summary

The summary key must continue to include Product Result snapshot identity,
packet/context hash, prompt version, model version, schema version, tenant scope,
and history window.

## Implementation Units

### U1. DB-backed live candidate read path

Add a PostgreSQL-backed candidate query for latest Product Result artifacts. Keep
the fixture path as an explicit fallback for local SQLite/dev use only.

Files:

- `systems/backend/app/infra/db/asset_detail_read_adapter.py`
- `systems/backend/app/operations/asset_detail_view_model.py`
- `systems/backend/app/operations/service.py`
- `systems/backend/app/dependencies.py`

Verification:

- Unit test proves watcher uses runtime candidates when a runtime detail service
  is supplied.
- Existing fixture watcher tests still pass.

### U2. Feedback-aware watcher materialization

Extend watcher materialization so the candidate source is explicit:

- `fixture`: current behavior
- `live`: DB latest Product Result candidates
- `auto`: live candidates when available, otherwise fixtures
- `post-maintenance`: candidates tied to Closed-loop maintenance/replay lineage

Files:

- `scripts/watch_agent_review_summaries.py`
- `systems/backend/app/operations/service.py`
- `tests/test_agent_review_summary_watcher_cli.py`
- `tests/test_operations.py`

Verification:

- Test covers feedback completion -> watcher -> rebuilt packet -> new summary.
- Test proves repeated watcher run reuses the same `summary_key` when inputs do
  not change.

### U3. Live-provider and consumer delivery proof

Add validation mode for claims:

- `--require-live-provider` fails if materialization falls back.
- Consumer verification checks that cached consumer read returns the same
  `summary_id` and `summary_key` produced by watcher.

Files:

- `scripts/watch_agent_review_summaries.py`
- `systems/backend/app/operations/service.py`
- `tests/test_agent_review_summary_watcher_cli.py`
- `tests/test_operations.py`

Verification:

- Fallback watcher remains allowed by default.
- Required-live-provider watcher exits non-zero on fallback.
- Consumer verification test confirms same summary identity.

## Realtime Safety Review

The design is safe while live data is arriving only if these invariants hold:

- Candidate scan returns exact immutable keys. Later live rows do not alter the
  packet being built for the already selected candidate.
- Staleness is based on `source_sha256` and context hash, never summary
  `updated_at`.
- Multiple watcher processes can race, but only one running workflow is allowed
  per `summary_key`; the other process observes in-progress or reuses the stored
  summary.
- Provider failures can produce deterministic fallback in normal watcher mode,
  but claim/evaluation mode must fail on fallback when live AI generation is
  required.
- Consumer verification is an observation step. It must not trigger
  materialization.

## Communication Boundary

Safe after U1-U3 pass:

- "Watcher can rebuild and deliver Agent Review Summary from DB-backed live or
  feedback candidates."
- "The same summary identity is visible to consumer reads."

Not safe unless live-provider verification passes:

- "The live AI provider generated the refreshed summary."

## Implementation Result

Implemented on PR 163 branch:

- DB-backed watcher candidate source modes: `fixture`, `live`, `auto`,
  `post-maintenance`
- PostgreSQL AssetDetail candidate discovery from latest Product Result
  artifacts
- watcher CLI `--source` and `--require-live-provider`
- local live launcher env controls:
  `AGENT_SUMMARY_WATCHER_SOURCE`,
  `AGENT_SUMMARY_WATCHER_REQUIRE_LIVE_PROVIDER`
- runtime `event_id` consumer lookup using the same DB AssetDetail packet path
  as watcher
- stable fallback reuse for `ProviderUnavailable` so repeated polling does not
  rewrite the same unavailable-provider fallback

Verified on 2026-09-04:

- Target: PR #163 head `d34c51025fc811f1252785ca6acbd4cc3dcfb78f`
  on head branch `enjoylonelines/pr161-llm-eval-integration`, base
  `feat/predictive-maintenance-decision-workspace`; working tree was clean
  before verification.
- Runtime topology command:
  `GEN_DATA_ROOT=/private/tmp/gen_data .venv/bin/python scripts/run_local_realtime.py --api-port 8100 --web-port 3100 --generator-port 8200 --gen-data-port 8300 --postgres-port 5432 --simulation-hours 169 --history-hours 168`.
  Existing listeners on `3100`, `8100`, `8200`, `8300`, and `5432` were cleared
  first; PostgreSQL used
  `postgresql://ontology:ontology-local-only@127.0.0.1:5432/ontology_dashboard`.
- Health checks: Backend `http://127.0.0.1:8100/health` -> 200 OK,
  Frontend `http://127.0.0.1:3100/` -> 200 OK, Generator
  `http://127.0.0.1:8200/health` -> 200 OK. The gen_data service was reachable
  at the run URL printed by the launcher; `/health` on `8300` is not implemented
  and returned 404.
- gen_data source boundary: bootstrap/reference source version
  `canonical-ai4i-physics-v3.1`; selected live dashboard source version
  `gen-data-wall-clock-live-v2`; live `dataset_version_id`
  `dsv-8db96cf9-c174-5dfc-b17f-3fdf680b3825`; dashboard API source kind
  `postgresql_result_artifact`.
- UI smoke E2E:
  `PLAYWRIGHT_EXTERNAL_SERVERS=1 PLAYWRIGHT_API_URL=http://127.0.0.1:8100 PLAYWRIGHT_BASE_URL=http://127.0.0.1:3100 npm --prefix systems/frontend run test:e2e -- pr163-live-smoke.spec.ts --project=chromium`
  -> 1 passed.
- Closed-loop feedback/replay backend test:
  `.venv/bin/python -m pytest -q tests/test_operations.py -k "api_closed_loop_feedback_flow_reaches_replay_and_agent_review_context"`
  -> 1 passed, 65 deselected after making the test harness explicitly use the
  intended test/heuristic fallback path.
- Root-cause fix for the earlier Closed-loop test failure: the Product Result
  Artifact builder now passes the fixture `asset_type` into predictor resolution,
  and the Closed-loop test pins `APP_ENV=test` plus
  `ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1`. The earlier failure was
  an env/test-harness contract issue, not missing gen_data output.
- watcher live DB trigger:
  `.venv/bin/python scripts/watch_agent_review_summaries.py --database postgresql://ontology:ontology-local-only@127.0.0.1:5432/ontology_dashboard --source auto --limit 1 --max-attempts 1`
  selected `source_kind=live_result`, `event_id=RESULT#GEN-3cc23e9a-450c-5c6f-92fb-31dd0357d751`,
  `asset_id=CNC-S04-L04-01`, `dataset_version_id=dsv-8db96cf9-c174-5dfc-b17f-3fdf680b3825`.
- Fallback run boundary: without loading project `.env`, watcher returned
  `mode=deterministic_fallback`, `fallback_reason=ProviderUnavailable`,
  `summary_id=a640acc6-ed6e-463d-9317-dbc504950f5c`,
  `summary_key=agent-review-summary:a57f530e025c9bd80cf8e00cd7c3513356fe9a3ea2c1654486a8da17f5a2176a`.
  This proves fallback materialization and consumer delivery only.
- Live-provider run:
  `set -a; source .env; ONTOLOGY_DASHBOARD_DATABASE_URL=postgresql://ontology:ontology-local-only@127.0.0.1:5432/ontology_dashboard; LLM_BASE_URL=https://api.openai.com/v1; set +a; .venv/bin/python scripts/watch_agent_review_summaries.py --database postgresql://ontology:ontology-local-only@127.0.0.1:5432/ontology_dashboard --source auto --limit 1 --max-attempts 1 --require-live-provider`
  -> exit code 0, `live_provider_ready=true`, `mode=llm`, `status=ready`,
  `fallback_reason=null`, `source_kind=live_result`, `summary_id=296808a6-75e1-4b2b-b6b9-c983a0571a86`,
  `summary_key=agent-review-summary:2b7eb29e320f28e91d5bfc30c387647446a6635532f392aa3929c14e62bc33c2`,
  `model_version=openai-compatible:gpt-4o-mini`.
- consumer GET for the same `asset_id`, `event_id`, and `dataset_version_id`
  returned the same live-provider `summary_id` and `summary_key` with
  `trace.fallback=false`.
- Confirmed: live gen_data -> PostgreSQL Product Result -> Agent Review Summary
  watcher -> live LLM summary materialization -> UI consumer API; UI smoke E2E;
  Closed-loop feedback/replay backend test under the explicit test fallback
  harness.
- Not claimed: the Closed-loop pytest is not a live PostgreSQL browser-to-replay
  proof; it verifies the backend feedback/replay test harness path. The fallback
  watcher run remains separate from the live-provider run and must not be used as
  live AI quality evidence.
- Cleanup: local runtime processes and the PostgreSQL container were stopped;
  ports `3100`, `8100`, `8200`, `8300`, and `5432` were empty after verification.

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

- `pytest -q tests/test_agent_review_summary_watcher_cli.py tests/test_operations.py`
  -> 69 passed
- PR 163 live smoke E2E on backend `8100` and frontend `3100`:
  `pr163-live-smoke.spec.ts --project=chromium` -> 1 passed
- local realtime topology started PostgreSQL, Backend, Generator Runtime,
  gen_data, live ingestor, maintenance dispatcher, and Frontend
- watcher live DB trigger:
  `source=auto`, candidate `source_kind=live_result`,
  `event_id=RESULT#GEN-3cc23e9a-450c-5c6f-92fb-31dd0357d751`,
  `summary_id=a640acc6-ed6e-463d-9317-dbc504950f5c`
- consumer GET for the same runtime `event_id` returned the same
  `summary_id` and `summary_key`
- `--require-live-provider` failed with exit code `2` because the current local
  environment returned `ProviderUnavailable`; therefore live DB packet delivery
  is verified, but actual LLM generation is not claimed for this run

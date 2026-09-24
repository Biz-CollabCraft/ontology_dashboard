# Evidence: agent-review readiness response compatibility

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
기준 revision: `d91f3119` with uncommitted compatibility-slice changes  
계획: `docs/plans/2026-09-24-readiness-response-compatibility.md`

## Change made

`systems/frontend/src/api.ts` now normalizes the GET and POST agent-review-summary response at the frontend API boundary.

- Explicit valid `reuse_eligibility` remains authoritative.
- A legacy response with `latest_stored=true` becomes `LATEST_STORED`, `current_ready=false`, and `historical_available=true`.
- A legacy ready, non-fallback summary with no history marker becomes `EXACT_VALIDATED`, `current_ready=true`, and `historical_available=false`.
- Missing, fallback, or otherwise unclassifiable legacy traces fail closed to `INELIGIBLE` with both booleans false.

No backend endpoint, schema migration, snapshot lookup, generation, provider call, queue, worker, or deployment behavior changed.

## Focused verification

Executed from `systems/frontend`:

```text
npm test -- api.briefing.test.ts NaturalBriefing.test.tsx && npm run lint
```

Result:

- Vitest: 2 files and 20 tests passed.
  - New `api.briefing.test.ts` fixture verifies legacy GET history is not current-ready and legacy POST exact ready remains current-ready.
  - Existing `NaturalBriefing.test.tsx` verifies explicit exact, historical, and pending ViewModel disclosure.
- `tsc --noEmit`: passed.

## Evidence boundary

This verifies only mocked frontend consumption of retained legacy trace shapes and the current ViewModel contract. It does not establish a real mixed-version deployment, external-consumer compatibility, server/OpenAPI version negotiation, provider readiness, database migration behavior, multi-worker behavior, rollback, latency, throughput, or production correctness.

## Outcome

The bounded adoption gate passed: both frontend endpoint consumers preserve the policy-B distinction, and the legacy history marker cannot produce a current-ready label. Final acceptance and whether to perform a real rolling-deployment check remain human decisions. The planned test budget is exhausted; no additional operational experiment was started.

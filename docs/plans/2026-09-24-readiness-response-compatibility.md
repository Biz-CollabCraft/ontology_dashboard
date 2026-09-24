# Supervised cycle: agent-review readiness response compatibility

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
기준 revision: `d91f3119` (시작 시점)

## Problem framing

- **Observed problem:** Policy B made `current_ready` and `historical_available` required frontend fields, while the retained legacy trace still exposes `latest_stored`. During a staggered old-server/new-frontend rollout, an older valid response can lack the new booleans at runtime.
- **Human hypothesis / Prediction:** unrecorded.
- **Human-authorized scope:** continue the recommended policy-B direction with one bounded old/new response consumer compatibility slice.
- **AI/challenger hypothesis:** normalize only at the frontend API boundary. A legacy `latest_stored=true` response becomes `LATEST_STORED/current_ready=false/historical_available=true`; a ready, non-fallback legacy summary without that marker becomes `EXACT_VALIDATED/true/false`.
- **Falsification condition:** if the adapter can label legacy stored history current-ready, changes an already explicit valid trace, or fails focused GET/POST consumer tests/type checking, reject the adapter and leave the server contract as the only supported shape.
- **Stop condition / budget:** change the frontend response adapter and focused tests plus this plan/evidence/decision record. Run one focused test command and TypeScript check. Do not run provider, server, deploy, database migration, workload, or multi-worker work.
- **Decision required:** final acceptance of the compatibility window and whether a real rolling-deployment test is worth opening later.
- **Unknowns:** actual deployed version skew, external consumers, API versioning policy, provider behavior, multi-worker behavior, and rollback compatibility.

## Alternatives

- **Baseline:** require all consumers to receive the post-policy-B trace; older payloads have no explicit UI compatibility path.
- **Chosen challenger:** derive the explicit pair from retained provenance or `latest_stored` only at the frontend API boundary.
- **Deferred:** API-version negotiation, backend migration/schema changes, or a deployment compatibility matrix.
- **Invariant:** legacy `latest_stored=true` is never current-ready; explicit valid provenance remains authoritative; fallback remains non-current; no generation, snapshot, scope, or materialization behavior changes.

## Discriminating experiment

- **Fixture/workload:** mocked legacy GET and POST JSON responses plus existing NaturalBriefing ViewModel tests.
- **Metrics:** derived enum and boolean pair for legacy historical and exact-ready response shapes; focused test and type-check exit status.
- **Adoption gate:** both endpoint consumers must derive history as `false/true` and exact ready as `true/false`, and the existing ViewModel tests must still pass.
- **Expected downside:** this is a browser-client contract test, not evidence of a deployed mixed-version rollout.

## Outcome

Recorded after execution in `docs/evidence/2026-09-24-readiness-response-compatibility.md`. Human final acceptance remains pending.

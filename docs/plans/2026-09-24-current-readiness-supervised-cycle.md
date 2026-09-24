# Supervised cycle: explicit current readiness and disclosed history

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
기준 revision: `fe8665590b16a77d0c40596afb6e8b5c3fc51526` (시작 시점)

## Problem framing

- **Problem:** 현재 GET은 exact validated summary와 `LATEST_STORED` history를 모두 HTTP 200/non-null summary로 반환한다. consumer가 trace를 해석하지 않으면 current readiness와 historical availability를 혼동할 수 있다.
- **Human hypothesis:** unrecorded.
- **Human Prediction:** unrecorded.
- **AI prediction:** `current_ready`를 `EXACT_VALIDATED`일 때만 true로, `historical_available`을 disclosed `LATEST_STORED`일 때만 true로 명시하면 HTTP status와 독립된 소비 계약을 제공하면서 기존 scope/key/mismatch guard를 바꾸지 않을 수 있다.
- **Falsification condition:** focused synthetic fixture에서 exact, disclosed historical, pending 중 하나라도 해당 boolean pair 또는 existing provenance를 잘못 보고하거나, 기존 snapshot/scope/mismatch safeguard에 영향을 주면 AI prediction을 기각하고 변경을 되돌릴 후보로 검토한다.
- **Experiment budget:** 직접 영향 backend service/router, frontend type/ViewModel, focused synthetic fixture/tests, 그리고 새 cycle plan/evidence/decision 문서만 변경한다. baseline과 한 번의 최소 보강 후 동일 fixture 재검증까지 허용한다. provider, server, harness workload, DB/HTTP integration, historical-metric repair는 실행하지 않는다.
- **STOP / Decision required:** three-state focused test evidence를 기록한 뒤 중단한다. 사람은 exposed names/semantics와 UX disclosure가 product policy를 만족하는지 최종 수용·보류·기각한다. AI는 이를 대신 결정하지 않는다.
- **Unknowns:** explicit booleans의 외부 consumer rollout, no-summary HTTP status의 long-term API policy, provider/production behavior, sustained workload, historical P0 and portfolio claims.

## Alternatives

- **Baseline:** `reuse_eligibility`만 제공하고 consumer가 HTTP 200/non-null summary와 provenance를 조합해 readiness를 추론한다.
- **Chosen challenger (human-authorized policy B):** trace에 `current_ready`와 `historical_available`을 명시하고 ViewModel이 current readiness와 historical disclosure를 별개로 표시한다.
- **Deferred alternatives:** exact-only response semantics; current behavior unchanged. 이 cycle에서 선택·구현하지 않는다.
- **Invariants:** exact key/provenance (`EXACT_VALIDATED`/`LATEST_STORED`), scope binding, mismatch write-block, GET generation separation, fallback semantics, and existing materialization trace remain intact.

## Discriminating experiment

- **Fixture/workload:** existing synthetic service/router or ViewModel fixture only; three states: exact ready, `LATEST_STORED` available but not current-ready, no summary pending.
- **Metrics:** boolean pair, provenance enum, summary presence, HTTP status where existing test covers it, and ViewModel disclosure text/state.
- **Acceptance gate:**
  - exact: `current_ready=true`, `historical_available=false`, `EXACT_VALIDATED`;
  - historical: `current_ready=false`, `historical_available=true`, `LATEST_STORED`;
  - pending: both false, `INELIGIBLE`, no summary;
  - no provider call or broader runtime/harness is introduced by these tests.
- **Expected downside:** this is a synthetic contract test, not a live provider, production, human-usability, latency, or capacity result.

## Outcome

- **Evidence:** `docs/evidence/2026-09-24-current-readiness-supervised-cycle.md`.
- **Result:** policy B adds explicit `current_ready` and `historical_available` while retaining provenance. The focused exact/historical/pending fixture and ViewModel tests passed; no provider or workload was executed.
- **Human decision:** implementation choice authorized; final acceptance pending human decision.
- **Changed belief:** pending human decision.
- **Stop condition:** met. Next Decision Gate reached after same-fixture revalidation.

# Decision Gate: exact/current/historical briefing contract

작성일: 2026-09-24  
근거: [supervised-cycle evidence](../evidence/2026-09-24-supervised-cycle.md)  
상태: **pending human decision — no option selected**

## Decision required

현재 API는 exact validated summary가 없더라도 scope-bound stored summary를 `LATEST_STORED`로 200 반환하고, ViewModel은 이를 “이전 업무 시점 기준”으로 표시한다. 제품은 어떤 consumer contract를 채택할지 사람의 결정을 요구한다.

| Human policy option | consumer contract | gain | cost / mandatory follow-up before claim |
|---|---|---|---|
| A. Exact-only | exact key’s `EXACT_VALIDATED` summary only is ready; otherwise pending/202. Historical material is not a successful summary for the current request. | The strongest exact-current interpretation; HTTP-ready and current-ready align. | Loses immediate historical briefing availability. Revalidate exact/pending/no-GET-generation and UI behavior on the same fixture before claiming it.
| B. Split current-ready and disclosed history | Surface an explicit current-ready state separate from historical availability; historical content remains explicitly identified and does not satisfy current readiness. | Preserves useful history without treating it as current. Metrics can report exact-ready and historical availability separately. | Requires an API/ViewModel/eval terminology change and same-fixture revalidation. The current trace label alone is not a dedicated `current_ready` field.
| C. Retain disclosed historical fallback | Keep the present `LATEST_STORED` behavior and UI disclosure. | No policy/UX disruption; preserved P0 shows provenance remains distinct in its bounded probe. | Do not state that HTTP 200, non-null summary, or `LATEST_STORED` is exact/current-ready. Strict exact-only gate remains unmet.

## Non-negotiable invariants under every option

- exact identity includes the validated packet/key path; historical provenance must not be silently rebound as the requested exact identity;
- scope binding (organization/project/workspace/asset/event/history) remains enforced;
- context change during generation blocks invalid publication;
- GET must not itself cause provider generation;
- synthetic/reference fixtures, automatic gold scoring, and historical documents are not human-gold or production evidence;
- 72-row workflow, 120-run quality, selection candidate counts, and P0 probe observations remain separate evidence streams.

## Metric-policy guard

- Do not retain the unsourced `27→6`, 100% recall, or “about 29% token” claim.
- If retaining historical `29→8`, name it as a synthetic selection fixture: candidate count 29 to 8, 72.41% count reduction, annotated-required-evidence recall 1.0, and no implied token/cost/human-quality result.
- If retaining historical 72-row token deltas, name the B1/B2/B3 × 8-case × 3-iteration denominator and the invalid/unscored plus fallback/reuse caveats; label token values as estimates, not provider billing or P0 measurements.

## Human-owned outcome

- **Human decision:** pending human decision.
- **Adopt / defer / reject:** pending human decision.
- **Changed belief:** pending human decision.
- **Next step after a choice:** at most one chosen-contract implementation/reinforcement, then identical-fixture revalidation. No workload expansion is authorized by this review.

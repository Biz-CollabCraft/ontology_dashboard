# Supervised cycle evidence: ontology contract and metric provenance review

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
검토 시작 기준 revision: `fe8665590b16a77d0c40596afb6e8b5c3fc51526`  
방법: 읽기 전용 source/document/artifact reference 검토. 서버·provider·harness·workload를 실행하지 않았다.

## Executed inspection record

- `git status --short`, `git rev-parse HEAD`: 시작 시 pre-existing dirty/untracked 경로는 `AGENTS.md`, `docs/plans/ai-workflow/README.md`, `docs/engineering/`, `docs/eval/2026-09-23-ontology-p0-contract-boundary-report.md`, `docs/plans/2026-09-24-scope-depth-closure-review.md`, `experiments/ontology_p0_20260923/`였다. 이 cycle은 아래 3개 새 문서만 작성했다.
- `rg`/`sed`로 backend service/router, frontend contract/ViewModel, P0 raw-report/oracle, historical evaluation/presentation documents와 `tests/eval/results`의 존재 여부를 조회했다.
- 테스트, lint, build, provider call, DB/HTTP request, server/harness 실행: **0회**. 따라서 아래는 fresh execution evidence가 아니라 current-source와 preserved/historical documentation의 provenance review다.

## Current contract: exact, historical, and pending

| Layer | observed current behavior | exact/current-ready meaning | limitation |
|---|---|---|---|
| Service | `systems/backend/app/operations/service.py::cached_agent_review_summary_for_packet` constructs a materialization key and performs validated exact lookup first. A hit is `reuse_eligibility=EXACT_VALIDATED`. | The returned stored summary has passed the cache-validity path for the requested packet/key. | The response does not expose a separate boolean named `current_ready`.
| Service fallback | On exact miss, the same function queries `latest_agent_review_summary` bound to organization/project/workspace/asset/event/history. If found, it returns that stored summary with `latest_stored=true` and `reuse_eligibility=LATEST_STORED`. | It is scoped stored history, not an exact-key validation for the requested packet. | A non-null summary/HTTP 200 must not be counted as exact-current readiness.
| API | `systems/backend/app/operations/router.py` returns 200 whenever summary is non-null and 202 only when it is null; it returns `{summary, trace}`. | `trace.reuse_eligibility` is the discriminator available to consumers. | HTTP status alone collapses exact and `LATEST_STORED` into 200.
| Type contract | `systems/frontend/src/features/operations/api/operationsContracts.ts` types `EXACT_VALIDATED`, `LATEST_STORED`, and `INELIGIBLE`, plus optional `latest_stored`; materialization also carries key/status/source/context hashes and decision time. | Consumers can distinguish reuse provenance if they inspect trace. | Optional/string-extended type and no explicit `current_ready` field mean a client can still ignore the distinction.
| ViewModel | `NaturalBriefing.tsx` accepts a non-fallback stored summary with status `ready`/`fallback`/`stale`. For `LATEST_STORED`, it renders “저장된 브리핑 · 이전 업무 시점 기준”; a no-summary response says current-evidence briefing is not available. | Historical reuse is disclosed in the UI, not silently rebound as the current exact summary. | The ViewModel displays historical prose as a usable stored summary; it does not separately render a machine-readable current-ready state.

### P0 relation to the current contract — separate evidence stream

`docs/eval/2026-09-23-ontology-p0-contract-boundary-report.md` records a different revision (`71337cddd755eaa8cdb762af4598e21b2f7d085f`) and a synthetic single-process FastAPI TestClient/PostgreSQL test-double probe. Its valid `preflight-03` evidence has 179 JSONL rows: five GETs (pending 1, exact validated 1, disclosed historical 3), 11 provider-boundary calls, and GET-attributed provider calls 0. A context mutation changed the key; the three subsequent GETs returned `LATEST_STORED`; the snapshot guard blocked publication with `agent_review_context_changed_during_generation`.

That supports provenance disclosure and the bounded write-block observation, but it is not proof of current-revision readiness, sustained workload, production/provider behavior, real network/multi-worker behavior, provider quality/cost, or human usefulness. It also explicitly STOPped because strict exact-only interpretation was unmet. P0 must not be pooled with the historical 72-row workflow comparison.

## Historical evaluation and portfolio-number provenance

| claim/source | numerator / denominator and measurement basis | provenance status | retainable wording and limitation |
|---|---|---|---|
| Latest workflow comparison: 72 rows | `docs/eval/2026-09-05-final-presentation-evidence-index.md` defines 72 as B1/B2/B3 × 8 cases × 3 iterations. Reported B3-vs-B1 token delta is -27,918 and vs B2 -43,273. | Historical 2026-09-05 PM-validator artifact reference: `tests/eval/results/agent_workflow_baseline_live_20260905_pm_validator_fix.json`; that raw ignored result is not present in this checkout, so row-level denominators/usage cannot be independently recomputed here. No current-HEAD rerun occurred. | If kept, call it a historical fixture workflow comparison with serialized payload/output **estimated** total-token deltas. B1/B2 have invalid/unscored rows and B3 has fallback/reuse, so it is not a clean 72-valid-row quality comparison, actual billing/cost result, latency comparison, P0 result, or current readiness metric.
| Earlier 72-row report | `docs/eval/2026-09-03-agent-workflow-final-evaluation-report-960f4713.md` reports 24 runs per arm and B3 tokens 22,187, with stated raw path `agent_workflow_baseline_live_72_20260903_960f4713.json`. | Candidate SHA `960f4713`; report says raw JSON is local generated/ignored. It is a distinct historical candidate, not the 2026-09-05 PM-validator artifact. | Do not substitute these totals or score values for later 72-row claims.
| Selection `29→8` | `docs/eval/2026-09-03-selection-live-llm-model-comparison-brief.md` gives required evidence recall 1.0, limitation preservation 1.0, context reduction 0.7241, candidates `29 → 8`. Count reduction is `(29 - 8) / 29 = 72.41%`. | Historical selection candidate `d8d357f357983988e6fe915ff64af4ac420e4c50`; selection plan defines recall as selected gold-required evidence / gold-required evidence, and token reduction as `1 - S1 prompt tokens / S0 prompt tokens`. | It is a synthetic/gold-fixture selection result. Recall 1.0 means all **annotated required** evidence in that fixture, not human-gold semantic quality, all context facts, live retrieval recall, or operational correctness. The 72.4% is candidate-count reduction, not token/cost reduction.
| Requested `27→6`, “about 29% token” | Searched current docs, plans, presentations, fixtures, and available result paths for a matching definition, revision, fixture, raw result, numerator/denominator, and token basis. None was found. The current scope-closure plan states `27→6`, while the historical selection brief reports `29→8`; this discrepancy was identified during this review, not already resolved in the plan. | No inspectable raw artifact or source-supported matching claim in this checkout. | **Do not retain** `27→6`, a 100% recall denominator, or ~29% token reduction as an evaluation/portfolio number until a source revision, fixture, gold-required set, S0/S1 token totals/measurement basis, and raw artifact are supplied and revalidated.
| Portfolio/presentation text | `docs/presentations/ontology-dashboard-v4/ontology-dashboard-v4-5min-script.md` currently says 32/32 contract checks and calls `29→8` a historical example. Historical presentation notes explicitly state the 72.4% is synthetic candidate-count reduction, not token/cost/user usefulness. | Presentation document, not a new run. The 32/32 denominator is contract checks, separate from both selection candidates and workflow rows. | Keep denominator labels beside every number; do not merge 32/32, 29→8, 72 rows, 120 rows, or P0 GETs into one metric.

## Metric contract findings

1. **Required evidence recall denominator:** the selection plan defines it as the gold-annotated required evidence set, not all eligible candidates, not all source facts, and not human review. A claim of 1.0 must name the fixture/gold annotation.
2. **Candidate reduction denominator:** `29→8` is full eligible candidate count to selected candidate count in the specified selection fixture. It is not a token metric. The historical 72.4% calculation is reproducible from those two counts only.
3. **Prompt token reduction denominator:** S1 prompt-token count divided by S0 prompt-token count; the plan permits prompt bytes only as an explicitly labeled proxy. No matching `27→6`/29% raw S0/S1 token totals were located.
4. **72-row token deltas:** reported totals are serialized payload/output estimates rather than provider usage metadata. The 1/1 provider-usage smoke documented elsewhere validates collection capability only; it does not convert the earlier 72-row totals into provider-billed usage.
5. **P0 denominator:** five GET observations and 11 test-double provider calls in one probe; its HTTP 200 cases include historical reuse. It must remain separate from 72-row or 120-row historical evaluation denominators.

## Outcome and stop condition

- The documentation-review budget was used once; no reinforcement is applicable because no code/contract change was authorized or made.
- Exact/current/historical terminology, metric denominators, raw-path provenance, and known limitations are now recorded in this evidence document.
- **Human decision:** pending human decision.
- **Changed belief:** pending human decision.
- **STOP met:** this worker stops at the policy Decision Gate; no product, policy, portfolio, or evaluation artifact change is selected here.

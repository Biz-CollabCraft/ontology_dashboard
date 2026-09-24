# Supervised cycle: ontology contract and metric provenance review

작성일: 2026-09-24  
저장소: `/Users/hb/Projects/ontology-dashboard`  
기준 revision: `fe8665590b16a77d0c40596afb6e8b5c3fc51526` (검토 시작 시점)

## Problem framing

- **Problem:** 현재 코드와 기존 문서에서 exact/current/historical API·ViewModel·evaluation 계약, 그리고 72-run 및 27→6 recall/token 표현의 분모·provenance·한계가 같은 의미로 설명되는지 확인해야 한다.
- **Human hypothesis:** unrecorded.
- **Human Prediction:** unrecorded.
- **AI prediction:** exact lookup 뒤 `LATEST_STORED` historical fallback을 명시적으로 표시하는 P0 계약과, 72-run 안정성 자료 및 27→6 selection 평가는 목적·fixture·분모가 달라 하나의 current-readiness 또는 운영 성능 주장으로 결합할 수 없을 가능성이 높다.
- **Falsification condition:** 현재 코드/API/ViewModel이 historical reuse를 exact/current-ready로 표시하거나, 원시 evaluation artifact에서 72-run 또는 27→6 claim의 분모·revision·fixture를 확인할 수 없어 문서가 그것을 확정된 수치로 유지한다면 위 AI prediction은 기각 또는 수정한다.
- **Experiment budget:** 읽기 전용 문서·소스·기존 evidence artifact 추적 1회. 서버, provider, harness, workload, 신규 인프라는 실행하지 않는다. 구현 또는 정책 결정을 하지 않는다.
- **STOP / Decision required:** evidence·decision 문서에 확인 가능한 계약과 한계를 기록한 후 중단한다. 사람은 다음 중 하나를 선택해야 한다: (1) exact-only, (2) exact current-ready와 disclosed historical fallback의 분리, (3) disclosed historical fallback 유지. AI는 선택하지 않는다.
- **Unknowns:** 실제 사용자 UX에서 historical fallback의 허용 범위, exact materialization 보장 목표, 72-run 자료가 현재 revision에 재현되는지, 27→6 claim의 human-gold 여부.

## Alternatives

- **Baseline:** historical fallback을 current-ready와 구분하지 않거나, 서로 다른 evaluation 자료를 하나의 readiness/portfolio 수치로 서술한다.
- **Challenger A:** exact-only. exact key의 validated summary가 없으면 pending/not-ready로 표시한다.
- **Challenger B:** exact current-ready와 scope-bound disclosed historical fallback을 별도 상태·문구·평가로 유지한다.
- **Challenger C:** 현재의 disclosed historical fallback을 유지하되 exact-current readiness claim을 하지 않는다.
- **Invariant:** 어떤 선택도 exact snapshot identity, tenant/scope binding, mismatch 시 write block, 그리고 historical provenance disclosure를 제거하지 않는다. synthetic/reference fixture를 human gold나 live/provider evidence로 승격하지 않는다.

## Discriminating documentation review

- **Fixture/workload:** 현 checkout의 API/service/ViewModel source, `docs/eval/`, `docs/evidence/`, `experiments/` 내 기존 artifact만 사용한다.
- **Metrics:** 각 claim의 numerator/denominator, fixture population, selection 기준, token 산정법, raw artifact path, revision/provenance, 검증 레벨과 limitation.
- **Adoption/rejection gate:** 사람이 policy를 선택하기 전에, exact/current/historical terminology와 historical 72-run·27→6 수치가 출처·분모·한계와 함께 분리되어 기록되어야 한다.
- **Expected downside:** 문서 검토만으로 current provider behavior, production readiness, sustained load, human-quality를 확인할 수 없다.

## Outcome

- **Evidence:** `docs/evidence/2026-09-24-supervised-cycle.md`; documentation inspection completed with no execution.
- **Result:** current source exposes exact validation versus disclosed `LATEST_STORED` history through trace/UI, but no explicit current-ready field. Historical 72-row and `29→8` evidence have separate denominators/provenance. The requested `27→6`/~29% token claim was not source-supported in this checkout and is not retained.
- **Human decision:** pending human decision.
- **Changed belief:** pending human decision.
- **Stop condition:** met. Decision Gate reached; no implementation or execution is authorized in this cycle.

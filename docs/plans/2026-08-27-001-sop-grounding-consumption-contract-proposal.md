# SOP Grounding 소비 계약 보강 제안

Status: proposal
Date: 2026-08-27
Base: `main` at `9500fedcb32984f968748ab580b93ccd724a3702`
Related:

- PR #130 `fix(mvp): SOP fixture로 점검 안내 grounding 분리`
- `docs/closed-loop-product-consumption-contract.md`
- `docs/closed-loop-domain-contract.md`
- `docs/plans/2026-08-24-001-feat-asset-detail-ui-agent-flow-plan.md`

## 1. 제안 목적

PR #130은 Frontend가 점검 위치와 방법을 문자열로 추정하지 않고, Backend가 제공하는
`inspection_guidance`를 통해 SOP 기반 참고 안내를 표시하는 방향을 제안한다. 이 방향은
Product Evidence와 작업 절차 참고 정보를 분리한다는 점에서 타당하다.

다만 현재 저장소의 Closed-loop 계약은 WorkOrder, MaintenanceAction, RecommendationDecision,
`available_actions`의 lifecycle과 소비 경계를 정의하지만, SOP 문서 자체의 lifecycle과 사용자-facing
노출 가능 조건은 아직 별도 계약으로 닫혀 있지 않다. 이 문서는 SOP Grounding을 Product Evidence,
Operations manual Recommendation, WorkOrder 생성과 혼동하지 않도록 소비 규칙을 보강하자는
제안이다.

## 2. 현재 근거

### 2.1 이미 존재하는 경계

`docs/closed-loop-product-consumption-contract.md`는 Frontend가 role, permission, Domain transition을
조합해 가능한 버튼을 자체 계산하지 않고, Backend가 반환한 `available_actions`를 presentation과
사용자 입력 진입점에만 사용한다고 정의한다. 또한 mutation 요청 시 Backend가 동일한
authorization/state 검증을 다시 수행해야 한다고 명시한다.

`docs/closed-loop-domain-contract.md`는 점검 후 실제 정비가 필요하다는 사람의 판단을
`recommendation_origin=operations_manual` 객체로 만들며, 이 수동 추천 자체도 정비 승인이 아니고
별도 `RecommendationDecision(disposition=accept)` 이후에만 maintenance WorkOrder를 만들 수 있다고
정의한다.

`docs/plans/2026-08-24-001-feat-asset-detail-ui-agent-flow-plan.md`는 agent가 WorkOrder를 생성하거나
수정하지 않고, 점검 질문과 handoff 초안을 준비하는 읽기 보조자로 남아야 한다는 방향을 둔다.

### 2.2 아직 없는 경계

위 문서들은 운영 객체와 사용자 Action의 lifecycle을 닫고 있지만, 다음 질문에는 답하지 않는다.

- SOP 또는 공장 매뉴얼 문서가 어떤 lifecycle 상태를 가질 수 있는가?
- 어떤 상태의 SOP만 UI guidance, checklist draft, agent handoff 초안에 사용할 수 있는가?
- `draft` 또는 `retired` SOP가 검색에는 잡히더라도 사용자-facing 점검 안내로 노출되어도 되는가?
- SOP guidance가 WorkOrder 생성, 정비 승인, 교체 확정과 어떤 관계를 갖는가?
- SOP version과 source reference를 점검 결과나 agent handoff lineage에 어떻게 보존할 것인가?

따라서 PR #130처럼 SOP Grounding을 UI에 붙이는 작업은 최소한의 소비 계약을 함께 요구한다.

## 3. 용어

SOP(Standard Operating Procedure)는 표준작업절차서다. 이 프로젝트에서는 설비 위험 판단 이후
사람이 어떤 순서와 질문으로 점검해야 하는지 안내하는 공장 매뉴얼 또는 현장 절차 문서로 취급한다.

SOP Grounding은 Product Evidence가 아니다. Product Evidence는 왜 위험하다고 판단했는지에 대한
모델, 센서, 근거, policy lineage를 설명한다. SOP Grounding은 그 판단을 보고 사람이 어떤 절차로
확인할지 돕는 참고 문서 연결이다.

## 4. 제안하는 SOP lifecycle

| 상태 | 의미 | 사용자-facing guidance |
|---|---|---|
| `fixture` | 데모 또는 테스트용 로컬 참고 자료 | `demo_sop_fixture`일 때만 허용 |
| `draft` | 작성 중이거나 검토 전인 절차 | 금지 |
| `approved` | 운영 승인된 현장 SOP | `site_sop`일 때 허용 |
| `retired` | 폐기 또는 대체된 과거 절차 | 신규 guidance 금지, 감사/이력 조회만 허용 |

이 lifecycle은 WorkOrder나 MaintenanceAction의 상태 전이를 대체하지 않는다. SOP 문서 상태는
문서 신뢰도와 노출 가능성을 나타내며, 작업 실행 상태는 기존 Closed-loop Domain 계약을 따른다.

## 5. 소비 가능 조건

Backend consumer는 SOP를 UI guidance 또는 agent handoff 초안으로 승격하기 전에 `source_kind`와
`maturity`를 함께 검사해야 한다.

| `source_kind` | `maturity` | 소비 정책 |
|---|---|---|
| `demo_sop_fixture` | `fixture` | MVP demo guidance 허용 |
| `site_sop` | `approved` | 현장 SOP guidance 허용 |
| `site_sop` | `draft` | 검색 후보로만 보존, UI guidance 금지 |
| `site_sop` | `retired` | 이력/감사 조회 외 신규 guidance 금지 |
| `industry_standard_reference` | any | 별도 정책 전까지 직접 작업 안내 금지 |

이 gate를 통과한 뒤에도 asset type, failure mode, component, factor, risk grade, criticality,
production impact 같은 applicability 조건을 만족해야 한다. 반대로 applicability가 맞더라도
maturity gate를 통과하지 못하면 사용자-facing guidance로 노출하지 않는다.

## 6. Product/Closed-loop 경계

SOP Grounding은 다음을 할 수 있다.

- 점검 질문 초안 제공
- checklist draft 제공
- agent handoff 초안에 `sop_id`, `version`, `source_ref`, `maturity` lineage 제공
- 현장 담당자가 확인할 참고 절차와 human review question 제공

SOP Grounding은 다음을 해서는 안 된다.

- Product Result status, failure probability, top factor, recommended action을 대체
- Product Evidence 또는 Event Evidence Projection을 생성
- WorkOrder, MaintenanceAction, MaintenanceEvent를 자동 생성
- 교체 필요, 수리 지시, 정비 승인, 작업 완료를 확정
- retired 또는 draft 절차를 현재 작업 안내로 노출

WorkOrder 생성과 승인은 계속 `docs/closed-loop-domain-contract.md`와
`docs/closed-loop-product-consumption-contract.md`의 role, permission, state, scope, lineage,
`available_actions` 계약을 따른다.

## 7. PR #130에 대한 최소 반영 제안

PR #130이 SOP fixture를 `inspection_guidance`로 노출하려면 다음 최소 gate를 추가하는 것이 적절하다.

```text
demo_sop_fixture + fixture -> guidance 허용
site_sop + approved        -> guidance 허용
draft / retired            -> guidance 금지
industry_standard_reference -> 별도 정책 전까지 직접 guidance 금지
```

권장 테스트:

- `demo_sop_fixture + fixture`는 기존 CNC guidance를 노출한다.
- `site_sop + approved`는 applicability가 맞으면 guidance를 노출한다.
- `site_sop + draft`는 applicability가 맞아도 guidance를 노출하지 않는다.
- `site_sop + retired`는 applicability가 맞아도 guidance를 노출하지 않는다.
- guidance가 없으면 기존 gap 또는 unavailable 표현을 유지한다.

## 8. 후속 문서화 위치

이 제안이 합의되면 다음 중 하나로 canonical 계약을 승격한다.

1. `docs/closed-loop-product-consumption-contract.md`에 `SOP Grounding 소비 계약` 섹션 추가
2. 별도 `docs/sop-grounding-consumption-contract.md`를 만들고 Product 소비 계약에서 참조

SOP가 실제 문서관리 시스템, RAG, site manual repository와 연결되는 시점에는 이 계약을 확장해
승인자, effective date, retired replacement, version pinning, inspection result lineage 보존 규칙을
추가한다. MVP 단계에서는 위 maturity gate와 금지 경계만으로 충분하다.

## 9. 커뮤니케이션 경계

안전하게 말할 수 있는 것:

- SOP Grounding은 Product Evidence가 아니라 점검 참고 절차다.
- 사용자-facing guidance는 `fixture` demo SOP 또는 `approved` site SOP만 사용할 수 있다.
- WorkOrder와 MaintenanceAction은 SOP 노출만으로 생성되지 않는다.

아직 말하면 안 되는 것:

- 실제 공장 SOP 관리 시스템이 구현되었다.
- draft/retired 문서의 전체 검색/감사 lifecycle이 구현되었다.
- SOP가 교체 필요나 정비 승인을 자동 결정한다.
- agent가 SOP를 근거로 WorkOrder를 직접 생성한다.

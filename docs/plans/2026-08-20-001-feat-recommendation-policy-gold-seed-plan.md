---
title: "Recommendation Policy v1 and Gold Seed Plan"
type: feat
status: active
date: 2026-08-20
---

# Recommendation Policy v1 and Gold Seed Plan

## Summary

Product Result/Evidence에서 운영 추천 후보를 결정론적으로 만들고, 고정 Gold 시나리오를
`proposed` 상태의 개발용 추천 데이터로 멱등하게 materialize한다. 추천은 실행 명령이
아니며, 사람의 판단·승인 전에는 WorkOrder나 MaintenanceAction을 만들지 않는다.

이 계획은 기존 Closed-loop 상태 머신을 다시 만들지 않고, 호범의 producer
recommendation과 광우의 Operational RecommendedAction 경계를 연결하는 범위만 다룬다.

## Problem Frame

저장소에는 ProducerRecommendation, OperationalRecommendedAction, RecommendationDecision,
WorkOrder의 타입·상태·lineage·멱등성 계약이 이미 있다. 그러나 다음 두 연결이 별도
계획으로 고정되어 있지 않다.

- `status`, `criticality`, `data_quality_hold`를 어떤 우선순위 규칙으로 추천 후보에
  매핑할지
- `evaluation/gold_scenarios.yml`을 이용해 추천을 미리 쌓되, 현장 정비 데이터나
  실제 WorkOrder로 오인하지 않도록 어떻게 격리할지

현재 Gold 8개는 정상·경고·심각·저신뢰·데이터 품질 보류·LLM 장애를 다루는 내부 회귀
기준이다. 이는 현장 정답이나 비즈니스 효과의 증거가 아니므로, 계획 산출물에는 Gold의
권한·출처·사용 범위를 명시한다.

## Requirements

### Policy and lineage

- R1. 추천 정책은 `recommendation-policy-v1`로 버전 고정하고, `status`와
  `data_quality_hold`를 우선 평가한 뒤 필요한 경우 `equipment.criticality`를 사용한다.
  데이터셋에 없는 확률·RPN·검출도 점수를 새로 발명하지 않는다.
- R2. 정책 결과는 기존 `ProducerRecommendation`과
  `OperationalRecommendedAction` 계약을 재사용하며, `source_action_id`,
  `source_product_result_id`, `source_evidence_id`, schema/policy version, 원본 basis를
  보존한다.
- R3. `data_quality_hold`, 필수 identity 누락, unresolved basis가 있으면 실행성 추천을
  만들지 않고 `hold_for_data_check` 또는 unavailable 상태로 fail-closed한다.
- R4. LLM은 추천 결정·status·approval·WorkOrder 상태를 생성하거나 변경하지 않는다.
  LLM은 이후 자연어 요약과 화면 배치 후보에만 제한적으로 사용한다.

### Gold seed and persistence

- R5. Gold fixture는 실행 시 재생성하지 않고 버전과 checksum이 고정된 입력·기대 결과로
  사용한다. 기존 Gold 8개를 `Gold v1` 기준셋으로 유지한다.
- R6. pre-seed는 추천을 `status=proposed`로만 저장하고, `gold_fixture` 출처와
  `do_not_operationalize=true` 의미를 audit/provenance에 남긴다.
- R7. 동일 `source_product_result_id + source_action_id` 재처리는 no-op 또는 동일
  결과 replay가 되어야 하며, 새 artifact revision은 새 recommendation lineage를 만든다.
- R8. Gold seed 경로에서는 RecommendationDecision, WorkOrder, MaintenanceAction,
  MaintenanceEvent를 생성하지 않는다.

### Evaluation and claims

- R9. Gold runner는 상태·결정·근거·정책 버전·추천 상태·중복 여부·WorkOrder 부작용을
  별도로 기록한다. 단순 `8/8` pass rate만 보고하지 않는다.
- R10. 기존 8개 외에 정책 경계용 3~4개를 추가하거나 parameterized contract test로
  검증한다: critical+중간 criticality, data-quality-hold+high criticality,
  criticality 누락, 동일 이벤트 replay/new artifact revision.
- R11. 입력 변형(event/asset/evidence ID 변경, quality hold 삽입, unknown basis,
  policy version mismatch)은 reject/hold되어야 하며 실행성 추천으로 통과하면 안 된다.
- R12. 결과 문서와 발표에서는 `engineering acceptance set` 또는
  `synthetic evaluation set`으로 표현한다. 현장 정확도, 정비 시간 절감, 고장률 개선은
  실제 정비 이력·도메인 검토 없이는 주장하지 않는다.

## Key Technical Decisions

- KTD1. **기존 Domain 객체 재사용:** 새 `Recommendation` aggregate나 새 상태 머신을
  만들지 않고 기존 `ProducerRecommendation` → `OperationalRecommendedAction` 변환과
  `ClosedLoopRepository.save_recommendation`을 사용한다. 기존 계약과 중복 저장소를
  만들지 않기 위한 결정이다.
- KTD2. **정책 순서 고정:** `data_quality_hold/identity failure`를 가장 먼저 차단하고,
  그 다음 `critical`/`warning`/`attention`/`normal`을 처리한다. criticality는 위험도를
  재계산하는 값이 아니라 추천 우선순위를 보조하는 운영 맥락으로만 사용한다.
- KTD3. **추천과 실행 분리:** `request_inspection`과 `review_shutdown`은 사람이 검토할
  후보이며 자동 shutdown이나 maintenance 승인이 아니다. 기존 Domain 계약의
  `RecommendationDecision`과 WorkOrder 승인 경계를 그대로 따른다.
- KTD4. **Gold 고정, seed는 provenance:** 정적 Gold fixture에는 실행 seed를 요구하지
  않는다. 합성 데이터 생성에 seed가 사용된 경우에는 생성 metadata와 checksum에만
  기록하고, Gold 기대 결과를 현재 모델 출력으로 재생성하지 않는다.
- KTD5. **개발용 seed 격리:** Gold pre-seed는 local/test/demo fixture 경로에서만 허용하고
  production 환경의 operational recommendation seed와 분리한다. pre-seed 레코드는
  사람이 승인하지 않은 제안으로만 남는다.
- KTD6. **결정론적 ID와 revision:** recommendation ID는 source result/action/policy
  lineage에서 재현 가능해야 한다. random UUID를 deduplication 기준으로 사용하지 않는다.

## High-Level Technical Design

```mermaid
flowchart LR
  A[Product Result / Event Evidence] --> B{Quality and identity gate}
  B -->|hold or invalid| C[Unavailable / hold_for_data_check]
  B -->|valid| D[Recommendation Policy v1]
  D --> E[ProducerRecommendation]
  E --> F[OperationalRecommendedAction proposed]
  F --> G[Gold evaluator and seed manifest]
  G --> H[(Closed-loop repository)]
  H --> I[Human RecommendationDecision]
  I --> J[Existing WorkOrder boundary]
  J -. excluded from this plan .-> K[Maintenance execution]
```

정책 판단은 구조화된 evidence의 기존 필드만 읽는다. Gold seed는 `F`까지의 경로를
검증하지만, `I` 이후의 승인·작업·정비 상태는 기존 Closed-loop 계획과 담당자의
구현 범위로 남긴다.

## Scope Boundaries

### In scope

- Recommendation Policy v1 규칙·버전·basis 계약
- Product Result/Evidence에서 ProducerRecommendation으로의 결정론적 매핑
- Gold v1 평가 확장과 정책 경계 테스트
- `proposed` 추천 pre-seed, provenance, 멱등성, replay 검증
- 발표용 평가 artifact와 제한된 주장 문구

### Deferred to Follow-Up Work

- 실제 PostgreSQL Runtime Artifact에서 자동 consumer를 거쳐 recommendation을
  materialize하는 production E2E
- RecommendationDecision UI와 WorkOrder 승인 흐름의 확장
- 정비 완료 이후 Runtime Overlay와 treatment-effect 평가
- 비용·downtime·작업시간을 포함한 RPN 또는 기대비용 최적화
- 도메인 전문가의 현장 라벨 검토와 business impact 실험

### Outside this product's identity

- 자동 설비 정지·제어
- 자동 정비 실행 또는 승인 없는 WorkOrder 생성
- Gold 통과율을 근거로 한 현장 고장률·비용 절감 보증

## Implementation Units

### U1. Recommendation policy contract and deterministic evaluator

- **Goal:** 기존 producer action과 evidence field를 사용해 정책 버전과 우선순위 규칙을
  결정론적으로 평가한다.
- **Requirements:** R1, R2, R3, R4, KTD1, KTD2, KTD3
- **Dependencies:** 없음
- **Files:**
  - `systems/backend/app/diagnosis/recommendation_policy.json`
  - `systems/backend/ontology_dashboard/closed_loop/recommendation_policy.py`
  - `systems/backend/ontology_dashboard/closed_loop/models.py`
  - `systems/backend/app/diagnosis/evidence_enrichment.py`
  - `tests/test_recommendation_policy.py`
  - `tests/test_evidence_enrichment.py`
- **Approach:** 정책 파일은 version, input fields, ordered rules, output action kind,
  approval requirement, basis field IDs를 선언한다. evaluator는 evidence validation을
  통과한 projection만 받고, existing `ProducerRecommendation`으로 반환한다. 기존
  `_ACTION_BY_STATUS`와 중복되는 의미가 발견되면 새 규칙을 병렬로 두지 않고 adapter로
  통합한다.
- **Patterns to follow:** `systems/backend/app/diagnosis/threshold_policy.json`,
  `systems/backend/app/diagnosis/evidence.py`,
  `systems/backend/ontology_dashboard/closed_loop/domain.py`.
- **Test scenarios:**
  - normal/medium은 `continue_monitoring` 후보와 monitor basis를 반환한다.
  - warning/high와 warning/medium은 inspection 후보를 반환하되 approval requirement를
    보존한다.
  - critical/high는 shutdown review 후보를 반환하고 자동 shutdown 명령을 만들지 않는다.
  - data-quality-hold/high는 실행성 추천이 아니라 data check hold로 끝난다.
  - criticality 또는 source basis가 누락되면 unavailable/reject로 끝난다.
  - LLM/provider가 비활성화되어도 policy output은 동일하다.
- **Verification:** 같은 evidence snapshot과 policy version에서 동일한 action ID,
  kind, basis, approval 값이 반복해서 나온다.

### U2. Gold v1 evaluation and boundary coverage

- **Goal:** 기존 Gold 8개를 추천 정책의 회귀 기준으로 확장하고 경계 케이스를 보강한다.
- **Requirements:** R5, R9, R10, R11, R12, KTD4
- **Dependencies:** U1
- **Files:**
  - `evaluation/gold_scenarios.yml`
  - `evaluation/README.md`
  - `scripts/evaluate_gold.py`
  - `tests/test_recommendation_gold.py`
  - `tests/test_evidence_report_layout_workflow.py`
- **Approach:** Gold v1 fixture와 expected block/decision을 수정 없이 유지한다. 추천
  policy 결과, source lineage, quality hold, forbidden side effect를 별도 결과 필드로
  추가한다. 경계 테스트는 새 fixture로 만들거나 parameterized contract fixture로
  두되, 기존 Gold expected value를 모델 실행 결과로 덮어쓰지 않는다.
- **Patterns to follow:** `evaluation/gold_scenarios.yml`, `evaluation/README.md`,
  `scripts/evaluate_gold.py`, `tests/test_closed_loop_domain_contract.py`.
- **Test scenarios:**
  - GS-001~GS-008의 expected decision과 policy output이 일치한다.
  - Gold runner가 각 추천의 source product/evidence/action ID를 확인한다.
  - critical+medium, data-quality-hold+high, missing-criticality, replay/revision 경계를
    각각 검증한다.
  - event/asset/evidence ID 변형과 unknown basis는 reject/hold된다.
  - Gold 평가 중 WorkOrder·MaintenanceAction·MaintenanceEvent 생성 수가 0이다.
- **Verification:** Gold v1 pass artifact에 scenario count, policy version, seed source,
  rejected mutation count, side-effect count가 기록된다.

### U3. Deterministic Gold pre-seed and idempotent persistence

- **Goal:** Gold 입력으로부터 개발용 `proposed` recommendation을 미리 쌓고 재실행·revision
  규칙을 입증한다.
- **Requirements:** R5, R6, R7, R8, KTD5, KTD6
- **Dependencies:** U1, U2
- **Files:**
  - `scripts/seed_gold_recommendations.py`
  - `systems/backend/ontology_dashboard/closed_loop/repository.py`
  - `systems/backend/ontology_dashboard/closed_loop/models.py`
  - `tests/test_gold_recommendation_seed.py`
  - `tests/test_closed_loop_persistence.py`
- **Approach:** seed 입력은 Gold scenario ID와 고정 fixture revision을 사용한다. 저장 시
  recommendation origin, policy/schema version, fixture checksum, `proposed` status를
  기록한다. 같은 source result/action은 기존 row를 replay하고, 새 result revision은
  새 lineage로 저장한다. seed 경로는 decision/work-order API를 호출하지 않는다.
- **Patterns to follow:** `ClosedLoopRepository.save_recommendation`,
  `tests/test_closed_loop_persistence.py`, demo seed의 production guard 패턴.
- **Test scenarios:**
  - 빈 DB에 Gold seed를 실행하면 expected count의 proposed recommendation만 저장된다.
  - 동일 seed를 두 번 실행해도 recommendation row와 audit/outbox side effect가 중복되지
    않는다.
  - 동일 event의 새 artifact revision은 기존 추천을 덮지 않고 새 source lineage를 만든다.
  - Gold seed에서 WorkOrder, Decision, MaintenanceAction row가 생성되지 않는다.
  - 다른 workspace scope의 Gold source는 저장되지 않거나 권한 오류가 난다.
- **Verification:** seed 결과 manifest와 DB count가 일치하고, repeat run delta가 0이며,
  모든 row가 `proposed`·`gold_fixture` provenance를 가진다.

### U4. Evaluation artifact, documentation, and handoff boundary

- **Goal:** Gold 결과를 현장 효과로 과장하지 않고 발표·리뷰에서 재현 가능한 artifact로
  남긴다.
- **Requirements:** R9, R12, KTD4, KTD5
- **Dependencies:** U2, U3
- **Files:**
  - `evaluation/results/README.md`
  - `evaluation/results/recommendation-policy-v1.json`
  - `docs/closed-loop-implementation-plan.md`
  - `docs/closed-loop-domain-contract.md`
  - `docs/mvp/pdm-evidence-report-ui-integration-plan.md`
- **Approach:** 결과 artifact에 Gold version, fixture checksum, policy/schema/model
  version, evaluator version, run timestamp, scenario count, pass/fail, mutation rejection,
  side-effect count, known limitations를 기록한다. 기존 Closed-loop 문서에는 새 정책의
  ownership과 seed 경계만 연결하고 상태 머신 설명을 복제하지 않는다.
- **Patterns to follow:** `evaluation/results/README.md`, `docs/closed-loop-*`,
  `docs/mvp/report-specification.md`의 claim/limitation 원칙.
- **Test scenarios:**
  - 결과 JSON이 schema와 required provenance를 만족한다.
  - Gold 8/8 통과와 field/business validation 미실시가 동시에 표현된다.
  - policy version 또는 fixture checksum이 바뀌면 결과가 다른 run으로 분리된다.
- **Verification:** reviewer가 결과 artifact만 보고 Gold acceptance와 현장 효과 주장을
  구분할 수 있다.

## Acceptance Examples

- AE1. **정상 설비**
  - **Given:** GS-001, valid evidence, medium criticality
  - **When:** policy v1 evaluates the snapshot
  - **Then:** `continue_monitoring` proposed recommendation이 생성되고 WorkOrder는 0개다.

- AE2. **데이터 품질 보류**
  - **Given:** GS-007, invalid sensor data, any criticality
  - **When:** seed 또는 policy evaluation을 수행한다.
  - **Then:** `hold_for_data_check` 또는 unavailable만 허용되고 inspection/shutdown
    WorkOrder는 생성되지 않는다.

- AE3. **재처리 멱등성**
  - **Given:** 동일 event/product-result/action을 이미 seed했다.
  - **When:** 같은 Gold seed를 다시 실행한다.
  - **Then:** 기존 recommendation을 replay하고 새 row나 side effect를 만들지 않는다.

- AE4. **새 결과 revision**
  - **Given:** 같은 asset/event에 새 product result revision이 도착했다.
  - **When:** policy v1과 seed를 재실행한다.
  - **Then:** 구 revision을 덮지 않고 새 source lineage의 proposed recommendation을 만든다.

## System-Wide Impact

- **호범 / Diagnosis:** Product Result/Evidence에서 판단 후보와 basis를 제공한다. risk,
  probability, failure type을 Closed-loop가 재계산하지 않는다.
- **광우 / Closed-loop:** ProducerRecommendation을 OperationalRecommendedAction으로
  materialize하고, 이후 사람의 Decision·WorkOrder 상태를 소유한다.
- **우수 / Product API/UI:** 추천을 read-only proposed 상태로 표시하고 Backend의
  `available_actions`를 소비한다. Frontend가 추천 규칙이나 ID를 합성하지 않는다.
- **Evaluation:** Gold runner와 seed manifest는 개발·CI·demo fixture에 한정한다.
  PostgreSQL Runtime consumer 연결은 별도 E2E로 검증될 때까지 미입증으로 표시한다.

## Risks and Dependencies

| Risk / dependency | Mitigation |
| --- | --- |
| Gold expected action이 현재 fixture와 불일치 | U2에서 fixture expected와 policy output을 분리 비교하고 변경 시 Gold version을 올린다. |
| criticality를 실제 확률처럼 해석 | policy 문서에서 criticality는 운영 우선순위 맥락으로만 명시한다. |
| pre-seed가 실제 업무로 오인 | `gold_fixture`, `proposed`, `do_not_operationalize` provenance와 production guard를 강제한다. |
| source policy/evidence ID 누락 | 기존 Domain 계약처럼 unknown 기본값을 만들지 않고 fail-fast한다. |
| seed replay 중 중복 audit/outbox | source lineage 기반 idempotency와 repeat-run count 테스트를 둔다. |
| 8개 Gold를 현장 대표성으로 과장 | acceptance artifact에 synthetic/internal authority와 external validation 미실시를 기록한다. |

## Sources and Research

### Repository sources

- `docs/closed-loop-implementation-plan.md`: Producer recommendation materialization,
  담당 경계, PR 순서, 자동 실행 제외 범위
- `docs/closed-loop-domain-contract.md`: 추천·Decision·WorkOrder 경계, 상태 전이,
  `source_product_result_id + source_action_id` 멱등성 키
- `docs/closed-loop-product-consumption-contract.md`: 역할별 추천 소비,
  `available_actions`, Backend 권한 검증
- `docs/mvp/pdm-evidence-report-ui-integration-plan.md`: producer action/basis grounding,
  recommendation과 WorkOrder 분리
- `evaluation/gold_scenarios.yml`: Gold v1 8개 시나리오, 안전·fallback·역할별 기대값
- `scripts/evaluate_gold.py`: 현재 Gold runner가 검증하는 상태·결정·신뢰도·보고서·layout 범위
- `tests/test_closed_loop_domain_contract.py` and `tests/test_closed_loop_persistence.py`:
  typed recommendation과 persistence/idempotency의 기존 패턴

### External references

- [NIST AI RMF Core — Measure 2](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/)
  는 test set, metric, 도구·조건의 문서화, 배포 조건과 유사한 환경에서의 검증, 일반화
  한계 공개를 요구한다. 이 계획의 Gold manifest와 `not for` 주장 경계의 근거다.
- [NIST AI TEVV](https://www.nist.gov/ai-test-evaluation-validation-and-verification-tevv)
  는 AI 제품의 신뢰성을 위해 반복 가능한 측정·평가·검증·확인 체계를 사용하도록 안내한다.
  Gold runner를 단발성 demo가 아닌 repeatable evaluation artifact로 두는 근거다.
- [Google ML Test Score](https://research.google/pubs/whats-your-ml-test-score-a-rubric-for-ml-production-systems/)
  는 모델 정확도 외에 데이터·검증·모니터링·운영 준비 테스트를 함께 평가한다. 추천
  policy, data-quality hold, fallback, side-effect zero를 함께 보는 근거다.
- [Testing and Validating Machine Learning Classifiers by Metamorphic Testing](https://pmc.ncbi.nlm.nih.gov/articles/PMC3082144/)
  는 명확한 test oracle이 부족한 ML 시스템에서 입력-출력 관계를 불변 조건으로 검사하는
  접근을 제시한다. unknown citation, identity 변경, quality-hold 변형 테스트의 근거다.
- [Datasheets for Datasets](https://arxiv.org/abs/1803.09010)
  는 데이터셋의 목적·구성·수집·권장 사용을 문서화하도록 제안한다. Gold를 현장 정답이
  아닌 내부 engineering acceptance set으로 표시하는 근거다.
- [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993)
  는 평가 조건·의도된 사용·성능 특성·제한을 함께 공개하도록 제안한다. Gold 결과와
  실제 field/business validation을 분리하는 근거다.

## Success Metrics

- Gold v1 8개 + 경계 3~4개에서 정책 결과·근거 lineage 불일치 0건
- invalid/unknown basis·cross-scope 입력의 실행성 추천 통과 0건
- data-quality-hold에서 inspection/shutdown WorkOrder 생성 0건
- 동일 seed replay의 신규 recommendation·Decision·WorkOrder side effect 0건
- 새 artifact revision이 구 revision을 덮어쓴 사례 0건
- 모든 seeded recommendation이 `proposed`와 `gold_fixture` provenance를 보유
- 결과 artifact에 scenario count, policy/schema version, checksum, evaluator version,
  limitation이 기록됨

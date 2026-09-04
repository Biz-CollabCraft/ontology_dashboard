# Backend Runtime / Evidence Delivery Contribution

상태: 기여 근거 문서
최종 갱신: 2026-09-03
범위: Backend Runtime Diagnosis, Product Result 승격, Evidence 전달 계약, ViewModel 소비 경로

이 문서는 `ontology-dashboard` MVP에서 Backend Runtime Diagnosis와 Evidence 전달 경계를 정리한
기여 범위를 기록한다. 설명은 병합된 PR, 계약 문서, Schema, 테스트 근거에 연결된 항목으로 제한한다.

## 1. 기여 요약

Generator가 만든 raw prediction을 화면이나 조치 흐름에 바로 노출하지 않고, Backend에서 검증된
Product Result와 Evidence로 승격하는 경계를 정리했다.
문제정의는 예측 결과를 조직이 빠르게 판단할 수 있는 근거 단위로 바꾸는 것이며, 중점 기준은 시간
정합성, 책임분리, 확장성이다.

핵심 흐름은 다음과 같다.

```text
Generator raw output
  -> Backend Runtime Diagnosis validation / promotion
  -> Product Result Artifact
  -> Evidence Package / Event Evidence Projection
  -> AssetDetailViewModel
  -> UI / Report / read-only Agent Review consumer
```

이 흐름에서 중점적으로 다룬 기준은 다음이다.

- Prediction Batch 수신부는 accepted, duplicate, conflict, rejected 상태를 구분한다.
- Backend는 source hash, producer, runtime context, evidence lineage를 보존한다.
- Product Result Artifact는 product-facing 판단 단위로 승격된 결과를 담는다.
- Evidence Package와 Event Evidence Projection은 판단 근거와 한계를 소비 가능한 형태로 투영한다.
- UI는 raw payload를 직접 join하지 않고 `AssetDetailViewModel`을 소비한다.
- 누락되거나 오래된 근거는 정상값으로 보정하지 않고 gap, limitation, warning으로 드러낸다.
- Agent Review는 이 흐름 위의 read-only 소비자이며, 상태 변경 권한을 갖지 않는다.

## 2. 주요 설계 축

| 축 | 정리한 내용 | 대표 근거 |
| --- | --- | --- |
| Prediction Batch 수신 / 검증 | Generator가 게시한 prediction batch를 Backend Runtime Diagnosis 경계에서 검증하고 수신 상태를 분리한다. | [`runtime_router.py`](../../systems/backend/app/diagnosis/runtime_router.py), [`runtime_service.py`](../../systems/backend/app/diagnosis/runtime_service.py), [`prediction-result-batch.schema.json`](../../contracts/schemas/prediction-result-batch.schema.json) |
| Product Result 승격 | raw prediction item을 Product Result Artifact와 PredictionResult로 승격하고 source identity를 보존한다. | [`product-result-artifact.schema.json`](../../contracts/schemas/product-result-artifact.schema.json), [`diagnosis_schema.py`](../../systems/backend/app/diagnosis/diagnosis_schema.py), [`evidence.py`](../../systems/backend/app/diagnosis/evidence.py) |
| Evidence Package / Projection | 판단 근거, provenance, limitation을 UI와 Report가 읽을 수 있는 evidence projection으로 분리한다. | [`evidence-package.schema.json`](../../contracts/schemas/evidence-package.schema.json), [`event-evidence-projection.schema.json`](../../contracts/schemas/event-evidence-projection.schema.json), [PdM Evidence/Report UI 통합 계획](../mvp/pdm-evidence-report-ui-integration-plan.md) |
| AssetDetailViewModel | Frontend가 raw source를 재계산하지 않고 화면용 read model을 소비하도록 계약을 둔다. | [`asset-detail-view-model.schema.json`](../../contracts/schemas/asset-detail-view-model.schema.json), [AssetDetailViewModel API MVP Slice](../plans/2026-08-23-001-feat-asset-detail-viewmodel-api-plan.md), [MVP 공통 스키마 정의](../mvp/schema-definition.md) |
| 공유 Schema / test vector | Producer와 Consumer가 같은 기계 판독 계약을 기준으로 검증하도록 Schema와 예시 payload를 둔다. | [`contracts/README.md`](../../contracts/README.md), [`contracts/schemas/README.md`](../../contracts/schemas/README.md), [`prediction-result-batch-v1.json`](../../contracts/examples/prediction-result-batch/prediction-result-batch-v1.json) |
| Runtime ingest / refresh visibility | Runtime overlay와 batch ingest 상태를 API와 화면 소비 경로에서 확인할 수 있게 한다. | [`runtime_schema.py`](../../systems/backend/app/diagnosis/runtime_schema.py), [`sample_prediction_stream.py`](../../systems/generator/app/runtime_pipeline/sample_prediction_stream.py), [`smoke_runtime_overlay_local_bridge.py`](../../scripts/smoke_runtime_overlay_local_bridge.py) |
| AI 운영 판단 확장 | Evidence Snapshot에 생산/정비/품질/납기 context를 read-only로 붙이고, 조건부 impact와 역할별 brief를 만들되 추천·작업 생성·상태 변경은 Closed-loop로 분리한다. | [Operational Domain Extension Plan](../plans/ai-workflow/2026-09-02-002-operational-domain-extension-plan.md), [Operational Domain Extension Implementation Report](../eval/2026-09-02-operational-domain-extension-implementation-report.md), [`operational_decision_agent.py`](../../systems/backend/app/mvp/operational_decision_agent.py) |
| 임계값 / 판단 단계 합리화 | 오탐 점검 비용과 미탐 조기 발견 손실을 손익분기로 비교해, 현장 조치가 성립하지 않는 관찰 등급을 줄이고 빠른 판단용 알람/정상 경계를 유지한다. | `/Users/hb/Documents/final/reference-repos/pdm-mvp/docs/WEEK3_WATCH_GRADE_DECISION.md`, `/Users/hb/Documents/final/reference-repos/pdm-mvp/scripts/measure_grades_and_threshold_curve.py`, `/Users/hb/Documents/final/reference-repos/pdm-mvp/out/watch_band_breakeven_v3_1.csv` |
| Canonical V3.1 local runtime pinning | 원본 모델과 재구성 artifact 버전을 분리하고, lineage가 맞는 재구성 모델만 local real-time active model set에 pinning한다. | [`prepare_local_realtime_models.py`](../../scripts/prepare_local_realtime_models.py), [`legacy_v31_training.py`](../../systems/generator/model/legacy_v31_training.py), [`test_legacy_v31_model_reconstruction.py`](../../tests/test_legacy_v31_model_reconstruction.py) |
| DB / runtime persistence | SQLite와 PostgreSQL 검증 경로에서 runtime diagnosis 저장 계약을 분리해 확인한다. | [`diagnosis_runtime_repository.py`](../../systems/backend/app/infra/db/diagnosis_runtime_repository.py), [`test_prediction_result_inbox.py`](../../tests/test_prediction_result_inbox.py), [`test_predictive_maintenance_postgresql.py`](../../tests/test_predictive_maintenance_postgresql.py) |
| Closed-loop snapshot guard | 화면에서 본 evidence basis와 mutation 시점 서버 projection이 어긋나면 side effect 없이 거부한다. | [Evidence Snapshot Consistency Guard 계획](../plans/ai-workflow/2026-08-29-003-evidence-snapshot-consistency-guard-plan.md), [`maintenance/service.py`](../../systems/backend/app/maintenance/service.py), [`test_maintenance_loop_application.py`](../../tests/test_maintenance_loop_application.py) |

## 3. Merged PR 근거

### PR #140

- PR: [#140 백엔드 Prediction Batch 수신부를 Product Result 승격까지 연결](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/140)
- 확인 상태: merged
- Merge commit: `a601517173a15c83be58227f12d46ace568f390b`

PR #140은 Backend Runtime Diagnosis와 Product Result 전달 경계를 구현 근거로 연결한 중심 PR이다.
주요 변경 축은 다음과 같다.

- Prediction Batch 수신부와 validation status 응답 경로 추가
- accepted, duplicate, conflict, rejected 수신 상태 분리
- Product Result Artifact 승격 흐름 추가
- model threshold와 source identity 보존
- PostgreSQL verification path와 runtime repository 검증
- live batch ingest status와 runtime overlay local bridge smoke 검증
- frontend runtime overlay / evidence preview 소비 경로 연결

대표 파일과 테스트:

- [`systems/backend/app/diagnosis/runtime_router.py`](../../systems/backend/app/diagnosis/runtime_router.py)
- [`systems/backend/app/diagnosis/runtime_schema.py`](../../systems/backend/app/diagnosis/runtime_schema.py)
- [`systems/backend/app/diagnosis/runtime_service.py`](../../systems/backend/app/diagnosis/runtime_service.py)
- [`systems/backend/app/infra/db/diagnosis_runtime_repository.py`](../../systems/backend/app/infra/db/diagnosis_runtime_repository.py)
- [`contracts/schemas/prediction-result-batch.schema.json`](../../contracts/schemas/prediction-result-batch.schema.json)
- [`contracts/examples/prediction-result-batch/prediction-result-batch-v1.json`](../../contracts/examples/prediction-result-batch/prediction-result-batch-v1.json)
- [`systems/generator/app/runtime_pipeline/sample_prediction_stream.py`](../../systems/generator/app/runtime_pipeline/sample_prediction_stream.py)
- [`tests/test_prediction_result_inbox.py`](../../tests/test_prediction_result_inbox.py)
- [`tests/test_predictive_maintenance_postgresql.py`](../../tests/test_predictive_maintenance_postgresql.py)
- [`scripts/smoke_runtime_overlay_local_bridge.py`](../../scripts/smoke_runtime_overlay_local_bridge.py)

### PR #150

- PR: [#150 feat(mvp): 근거 패킷 기반 AI 검토 워크플로우 추가](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/150)
- 확인 상태: merged
- Merge commit: `3065ca502742e0a069f87e05ad305d74f5a97770`

PR #150은 Backend Runtime / Evidence 경계 위에 read-only Agent Review 소비자를 얹은 후속 근거다.
AI Review가 Product Result와 Evidence를 대신 판단하거나 상태를 변경하지 않고, 검증된 근거 패킷을 읽는
설명 계층으로 제한된 점을 연결 근거로 둔다.

이 PR의 상세 기여는 [AI Review / Evidence Boundary Contribution](./hb-ai-review-evidence.md)에 분리한다.

## 4. 현재 로컬 구현 보강 후보

- AI 운영 판단 확장: Evidence Snapshot에 Production/WIP, Maintenance Window, Part/Technician readiness, Quality/Lot/Delivery context를 붙이고, `ready`, `part_blocked`, `quality_hold` 3개 synthetic scenario로 시간 정합성·책임분리·확장성을 검증했다.
- 사용 가능한 수치: candidate `5633f914`, targeted/compatibility regression `154 passed, 0 failed`, deterministic smoke passed, scenario 3개, temporal validation 3/3, mutation attempts 0, generated recommendations 0, external API fallback isolation pass.
- 아직 쓰면 안 되는 수치: B1/B2/B3 live 비교, 최종 LLM quality, actual MES/CMMS/WMS/QMS 연결, 운영 효과/비용 절감.
- 임계값 합리화: reference repo의 Canonical V3.1 손익분기 계산에서 관찰 조치 1회 3/5/10분 가정의 손익분기는 98.4배/59.0배/29.5배였고, 현재 구현 가능한 알람 경계 0.75 아래 관찰 밴드는 가장 유리한 구간도 252.0배라 3분 기준의 2.6배였다. 그래서 관찰 등급은 빠른 판단에 도움이 되는 단계가 아니라 불필요한 점검을 늘리는 단계로 보고, 0.75 기준 알람/정상 2단계 권고를 근거로 삼는다.
- 임계값 근거: `/Users/hb/Documents/final/reference-repos/pdm-mvp/docs/WEEK3_WATCH_GRADE_DECISION.md`, `/Users/hb/Documents/final/reference-repos/pdm-mvp/out/watch_band_breakeven_v3_1.csv`, `/Users/hb/Documents/final/reference-repos/pdm-mvp/out/threshold_curve_v3_1.csv`
- Canonical V3.1 원본 모델 버전(`independent-logreg-v3.1`)과 재구성 artifact 버전(`independent-logreg-v3.1-reconstructed-v1`)을 분리하고, lineage/threshold가 맞는 재구성 모델만 local real-time active model set에 pinning하도록 보강했다.
- 근거: [`prepare_local_realtime_models.py`](../../scripts/prepare_local_realtime_models.py), [`legacy_v31_training.py`](../../systems/generator/model/legacy_v31_training.py), [`test_legacy_v31_model_reconstruction.py`](../../tests/test_legacy_v31_model_reconstruction.py)
- 외부 API fallback: 운영 context 포트의 timeout/malformed 실패를 정상 데이터로 합성하지 않고 `failed` gap과 `external_api_*` reason으로 남기도록 보강했다. 근거는 [`operational_decision_agent.py`](../../systems/backend/app/mvp/operational_decision_agent.py), [`test_operational_decision_agent.py`](../../tests/test_operational_decision_agent.py), [`evaluate_operational_decision_support.py`](../../scripts/evaluate_operational_decision_support.py).
- 상태: 2026-09-03 현재 로컬 구현. 외부 설명에는 commit/PR/CI/runtime 실행 확인 후 사용한다.

## 5. 관련 문서와 계약

| 문서 / 계약 | 역할 |
| --- | --- |
| [ADR-003: Generator Runtime Prediction Result 및 Backend Decision 소유권 결정](../architecture-decisions/ADR-003-generator-runtime-prediction-result-and-backend-decision-ownership.md) | Generator output과 Backend decision ownership의 경계를 정리한다. |
| [ADR-004: Product Result / Evidence / ViewModel 신뢰 경계](../architecture-decisions/ADR-004-product-result-evidence-viewmodel-trust-boundary.md) | Product Result, Evidence, ViewModel이 서로 다른 소비 계층에서 어떤 신뢰 경계를 갖는지 정리한다. |
| [PdM Evidence/Report UI 통합 계획](../mvp/pdm-evidence-report-ui-integration-plan.md) | Evidence와 Report를 UI 소비 경로에 연결하는 계획과 한계를 정리한다. |
| [AssetDetailViewModel API MVP Slice](../plans/2026-08-23-001-feat-asset-detail-viewmodel-api-plan.md) | 화면이 소비하는 read model의 API slice를 정리한다. |
| [MVP 공통 스키마 정의](../mvp/schema-definition.md) | MVP 데이터 계약과 Schema 위치를 설명한다. |
| [`contracts/README.md`](../../contracts/README.md) | 공유 계약의 정본 위치와 검증 방식을 설명한다. |
| [`prediction-result-batch.schema.json`](../../contracts/schemas/prediction-result-batch.schema.json) | Generator가 Backend로 전달하는 batch 계약이다. |
| [`product-result-artifact.schema.json`](../../contracts/schemas/product-result-artifact.schema.json) | Backend가 승격한 product-facing result artifact 계약이다. |
| [`evidence-package.schema.json`](../../contracts/schemas/evidence-package.schema.json) | 판단 근거 묶음의 공유 계약이다. |
| [`event-evidence-projection.schema.json`](../../contracts/schemas/event-evidence-projection.schema.json) | event evidence의 UI/report projection 계약이다. |
| [`asset-detail-view-model.schema.json`](../../contracts/schemas/asset-detail-view-model.schema.json) | Asset detail 화면이 소비하는 ViewModel 계약이다. |

## 6. 외부 설명 문장

```text
Backend Runtime Diagnosis와 Evidence 전달 경계에서, Generator의 raw prediction을 바로
화면에 노출하지 않고 Backend에서 Product Result Artifact와 Evidence Projection으로
승격하는 흐름을 구현 근거와 계약 문서로 연결했습니다. UI는 raw payload 대신
AssetDetailViewModel을 소비하게 하고, 누락된 근거는 정상값으로 보정하지 않고
gap/limitation으로 드러냈습니다. 이 흐름은 Prediction Batch 수신, Product Result 승격,
Evidence/Schema 계약, PostgreSQL 검증, 화면 소비 경로까지 PR과 테스트로 확인했습니다.
```

## 7. 주장 범위

이 문서는 다음 범위 안에서만 기여를 설명한다.

- 구현 완료 여부는 병합된 PR, 테스트, migration, runtime check가 있는 항목으로 제한한다.
- 문서와 계획은 결정 배경과 설계 근거로 사용하고, 병합된 구현 근거와 구분한다.
- local verification, CI, deployed behavior는 같은 의미로 취급하지 않는다.
- 현재 로컬 구현 보강 후보는 merged PR 근거와 분리하고, commit/PR/CI/runtime 실행 근거가 확인되기 전에는
  `로컬 구현 / 검증 필요`로 설명한다.
- Agent Review는 downstream read-only consumer이며 Backend Runtime Diagnosis의 판단 경계를 대체하지 않는다.
- 모델 성능 개선이나 비즈니스 KPI 개선은 별도 측정 근거 없이는 주장하지 않는다.
- 누락된 evidence는 정상값으로 합성하지 않고 gap, limitation, warning으로 표현한다.

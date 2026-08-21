# AssetDetailReportViewModel — 현재 MVP Frontend 필드 감사

작성일: 2026-08-20
상태: 조사/문서 산출물. 구현 아님.
근거 문서: [`pdm-evidence-report-ui-integration-plan.md` §3.1/§3.2](./pdm-evidence-report-ui-integration-plan.md), [`schema-definition.md` §5.3](./schema-definition.md), [`api-specification.md` §4.6](./api-specification.md)

## 1. 목적과 범위

PR #95는 `AssetDetailReportViewModel` 후보 계약(`GET /objects/{asset_id}/report-detail`)을 문서로 정의했다. 이 문서는 그 계약을 구현하기 전에, §3.2 "구현 순서" 1번 항목("`AssetDetailReportViewModel` 문서 계약과 테스트 fixture를 먼저 추가한다")을 수행하기 위한 선행 감사다.

범위는 다음과 같다.

- 현재 MVP frontend가 실제로 소비하는 detail/view 필드를 조사해 기준선을 확정한다.
- PR #95 계약(§3.1)과 현재 구현 필드의 차이를 표로 정리한다.
- 4가지 시나리오의 fixture 초안을 `tests/fixtures/asset_detail_report_view_model/`에 추가하고, `contracts/schemas/asset-detail-report-view-model.schema.json`으로 고정한다.

이 문서와 fixture는 계약 후보 shape을 고정할 뿐, `GET /objects/{asset_id}/report-detail` 엔드포인트나 Backend adapter, frontend ViewModel builder를 구현하지 않는다. §8.6 항목 23("구현 검증 후 API/schema 문서를 갱신")과 §8.5(frontend ViewModel/UI, 전부 `Deferred`)는 이 문서 이후에도 여전히 시작 전이다.

## 2. 조사한 파일

- `systems/frontend/src/features/mvp/api/mvpContracts.ts`
- `systems/frontend/src/features/mvp/api/mvpAdapters.ts`
- `systems/frontend/src/types.ts` (`Evidence`, `Report` 타입)
- `systems/frontend/src/features/mvp/objects/MvpObjectsPage.tsx` (Objects/Asset Inspector 화면)
- `systems/frontend/src/features/mvp/report/MvpExecutiveReportPage.tsx` (Executive Report 화면)

## 3. 기존 MVP 프론트엔드 기준선

`Mvp*` 타입은 계약 객체명이 아니라 현재 화면이 소비 중인 필드 기준선 조사용 구현명이다(§3.1 명시). 현재 MVP는 다음을 렌더링한다.

| 화면 | 렌더링 필드 |
|---|---|
| Objects · Asset Inspector | 상태 배지, 고장 확률, 신뢰도, 예상 다운타임, 담당자, site/line/cell, 관측 시각, 예측 고장 유형, 권장 조치, 센서 **현재값**(카드형), top factor **flat 목록**(baseline 없음), provenance |
| Executive Report | 위 기준선 + report headline/summary/sections/limitations, 설비 목록 요약, top factor 목록 |

두 화면 모두 다음을 렌더링하지 **않는다**: 센서 시계열 그래프, 위험도 시계열 그래프, baseline 범위 이탈(crossing) 마커, 설비 정비/점검 전체 이력. `map-report-ui-prototype`도 이 저장소에 존재하지 않는다(검색 결과 없음) — 즉 "UI synthetic graph fallback"으로 명시적으로 승격할 기존 코드가 현재는 없다. 이는 향후 그래프 UI를 이식할 때 지켜야 할 금지 사항(§6 "합성 금지")이지, 지금 되돌려야 할 기존 위반이 아니다.

### 3.1 발견한 계약 위반 리스크

현재 `MvpRiskStatus`(`systems/frontend/src/features/mvp/api/mvpContracts.ts:3`)는 다음과 같다.

```ts
export type MvpRiskStatus = "normal" | "attention" | "warning" | "critical" | "data_quality_hold";
```

`data_quality_hold`가 상태 등급 자체에 5번째 값으로 섞여 있고, `mvpAdapters.ts`의 `normalizeRiskStatus`/`STATUS_PRIORITY`/`computeMetrics`/`computeLineRisk`가 모두 이 5값 enum을 기준으로 분기한다. 이는 이번 작업에서 반드시 지켜야 할 계약(`risk.status_grade`는 4등급만 허용, `data_quality_hold`는 `data_status.is_data_quality_hold`로 분리)과 **정면으로 다른 모델**이다.

이 감사에서는 이 사실만 기록하고 `mvpContracts.ts`/`mvpAdapters.ts`를 변경하지 않는다. 이유는 다음과 같다.

- `Mvp*` 타입은 "현재 화면이 소비 중인 필드 기준선을 조사하기 위한 구현명"으로만 사용한다는 것이 §3.1의 명시적 결정이다. 즉 현재 MVP 기준선 자체를 신규 계약에 맞춰 리팩터링하는 작업은 이번 audit의 범위가 아니다.
- `AssetDetailReportViewModel`은 신규 composition endpoint(`/objects/{asset_id}/report-detail`) 전용 계약이며 기존 Event Report API를 대체하지 않는다. 기존 `MvpRiskStatus`/`Evidence`/`Report`를 건드리면 기존 Event 화면과 이번 계약이 아직 연결되지 않은 상태에서 회귀 위험만 커진다.
- §3.2 구현 순서상 이 시점은 "1. 문서 계약과 fixture 추가" 단계이며, "6. 프론트 report UI는 단일 ViewModel을 소비하도록 전환한다"는 아직 순서가 아니다.

**남은 gap으로 명시**: `AssetDetailReportViewModel`을 실제로 소비하는 frontend ViewModel builder(§6.1, §8.5 step 19)를 만들 때, `MvpRiskStatus`를 그대로 재사용하지 말고 새 `risk.status_grade`(4등급) + `data_status.is_data_quality_hold`(boolean) 쌍을 위한 별도 타입을 정의해야 한다. 기존 `MvpRiskStatus`의 5값 모델을 새 계약 타입에 유입시키지 않는다.

## 4. 필드 차이표

| 필드 묶음 | 기존 MVP 기준선 (§3 참고) | 추가 필요한 Asset Detail Report 필드 | 현재 Evidence로 채울 수 있는 필드 | 필요한 추가 source |
|---|---|---|---|---|
| Asset 식별/표시 | `assetId`, `displayName`, `assetType`, `site`, `line`, `cell`, `observedAt` | `asset.asset_id`, `asset.asset_type`(`compressor`\|`cnc`), `asset.site_id`, `asset.cell_id`, `asset.observed_at` | 가능 — 기존 값과 1:1 대응 | 없음 |
| 현재 위험/상태 | `status`(5값), `failureProbability`, `threshold`(Evidence 전용), `recommendedDecision` | `risk.current`, `risk.threshold`, `risk.status_grade`(4값만), `risk.prediction_horizon_hours` | 가능 — Product Result Artifact 값 그대로 사용. 단 `status_grade`는 4값으로 좁히고 `data_quality_hold`는 `data_status`로 분리해야 함(§3.1) | 없음 |
| 위험도 시계열 | 없음 | `risk_series[]` (`observed_at`, `failure_probability`, `status_grade`, `prediction_id`, `source_kind`) | **불가** — 단일 Event Evidence는 현재값 중심 | Backend Diagnosis가 `prediction_results`에서 만들 runtime result/prediction history. `gen_data/canonical/model_outputs/prediction_timeline.jsonl`이나 legacy `precomputed_prediction_timeline` 승격 금지 |
| 센서 현재값 | `MvpSensorValue[]` (카드형 flat 목록, 자산 유형별 하드코딩) | `features[].key/label/unit/current` | 가능 — `observation` 또는 `evidence_payload.sensor_evidence.sensors` | 없음 |
| 센서 baseline | 없음 | `features[].baseline`(`mean/std/lower/upper/reference`) | 부분 가능 — `evidence_payload.sensor_evidence.sensors[*].basis`가 있는 feature만 | 없는 feature는 baseline 없이 현재값만 표시, `evidence.gaps[]`에 기록 |
| 센서 시계열 | 없음 | `features[].series[]` (`observed_at`, `value`, `quality_status`, `source_ref`) | **불가** | Backend branch-aware Observation read contract와 Backend Feature Executor result. Generator는 Feature Schema/History Requirement/transform/Model Artifact owner이며, gen_data Layer 1/Layer 2/`_log.jsonl` 내부 저장 형태는 Product API의 직접 의존 대상이 아니다 |
| Top factor | `MvpFactor[]` (flat 목록, `id/feature/label/value/unit/contribution/direction/explanationMethod`) | `features[].top_factor`(`rank/contribution/direction/explanation_method/evidence_field_id`), feature 단위로 결합 | 가능 — `top_factors`/`ranked_factor_evidence` | 없음 |
| 설비 이력 | `MvpActivityItem[]` (Event activity/note/decision만, 단일 Event 범위) | `equipment_history[]`(`occurred_at/kind/tone/description/source/memo`) | 부분 가능 — 현재 activity 범위만. **전체** 정비/점검 이력은 Event Evidence만으로 합성 금지 | Activity/Decision/Maintenance/WorkOrder source(Operations/Maintenance API, 이번 주 범위 아님) |
| Evidence 상태 | `provenance`, `loadedSources`, `warnings`, `dataQualityWarnings` | `evidence.artifact_id/evidence_payload_reference/model_version/dataset_version/source_kind/gaps[]` | 가능 — Artifact/provenance에서 파생 | 없음 |
| 데이터 상태 | 없음(상태값에 `data_quality_hold`가 섞여 있음) | `data_status.source`(`canonical`\|`fallback`), `is_stale`, `is_data_quality_hold`, `warnings[]` | 가능 — 단 `is_data_quality_hold`는 기존 5값 status에서 **분리 재계산**해야 함 | 없음 |

## 5. Fixture 초안

`tests/fixtures/asset_detail_report_view_model/`에 4개 시나리오를 추가했다. 모두 `contracts/schemas/asset-detail-report-view-model.schema.json`으로 검증하며, `tests/test_asset_detail_report_view_model_contract.py`가 회귀 테스트다.

| 파일 | 시나리오 | 확인하는 것 |
|---|---|---|
| `current-evidence-only.json` | Product Result Artifact + `evidence_payload`만 존재 (Observation/runtime timeline/Maintenance 미연동) | 현재 asset/risk/센서값/top factor/baseline(있는 feature만)은 채워지고, `features[].series`·`risk_series`·`equipment_history`는 빈 값 + `evidence.gaps[]`로 표시 |
| `observation-series-present.json` | 위 + Observation API 연동 | `features[].series`가 채워지고 관련 gap이 사라짐. `risk_series`/`equipment_history` gap은 유지 |
| `risk-timeline-present.json` | 위 + Backend Diagnosis Runtime Prediction History Query 연동 | `risk_series`가 `source_kind=runtime_inference`와 `diagnosis-runtime-history://...` source_ref로 채워지고 관련 gap이 사라짐. `equipment_history` gap만 남음 |
| `baseline-partially-missing.json` | risk/series는 있으나 특정 feature의 baseline만 없음(baseline window 산출 불가) | 현재값·series는 그대로 유지되고 baseline만 `null` + `evidence.gaps[]`에 `features[N].baseline` 기록. 값 자체를 0/정상으로 보정하지 않음 |

`tests/test_asset_detail_report_view_model_contract.py`가 검증하는 계약 규칙:

- `risk.status_grade`는 `normal|attention|warning|critical` 4값만 허용(스키마 enum), `data_quality_hold`는 `data_status.is_data_quality_hold`에만 존재.
- `runtime_inference|compatibility_fallback`은 `evidence.source_kind`와 `risk_series[].source_kind`에만 존재하고 `data_status.source`(`canonical|fallback`)나 `features[].series[].quality_status`(`good|bad|unknown`)에는 섞이지 않는다.
- `risk_series[].source_ref`는 Backend Diagnosis Runtime Prediction History Query의 source reference이며, legacy `precomputed_prediction_timeline`, `/timeline`, `gen_data/canonical/model_outputs`를 직접 가리키지 않는다. 내부 저장 테이블명(`prediction_results`)을 public URI prefix처럼 고정하지 않는다.
- PR #97 이후 `evidence_payload.recommended_actions=[]`는 실행성 추천 부재를 뜻한다. Asset Detail Report composer는 이를 `evidence.gaps[]`로 전달하고 `available_actions`나 synthetic recommendation을 만들지 않는다.
- 스키마 root와 각 하위 객체는 `additionalProperties: false`이므로 `Mvp` 접두어를 포함한 임의 필드를 추가하면 실패한다.
- gap으로 기록된 필드(`risk_series`, `equipment_history`, `features[].series`)는 항상 빈 배열이며 합성값으로 채워지지 않는다.

## 6. 아직 gap으로 남긴 항목

- `GET /objects/{asset_id}/report-detail` 엔드포인트와 Product API 결합(§3.2 step 5)은 구현하지 않았다 — 여전히 `V2 변경 제안` 상태다. 다만 `systems/backend/app/report/asset_detail_report_view_model.py`의 순수 composer가 Product Result Artifact/Evidence, Backend Observation/Feature Executor series, Diagnosis Runtime Prediction History Query result를 병합하는 계약을 고정한다.
- Production Observation ingestion adapter(§3.2 step 2, `node_id` 파싱/pivot/`status_code` 매핑, §3.1 마지막 문단)는 구현하지 않았다. 이번 후속 커밋의 Layer 2 샘플 정규화는 `tests/test_gen_data_layer2_observation_adapter.py` 안의 fixture-only normalizer로만 존재하며, Backend production module이나 Product API dependency가 아니다.
- Backend Diagnosis Runtime Prediction History Query(`risk_series` 공식 소스)는 아직 없다. `risk-timeline-present.json`은 이 소스가 존재한다고 가정한 fixture이며, 실제 producer/query 구현은 후속 작업이다.
- frontend ViewModel builder와 UI 이식(§6, §8.5 step 19~22)은 시작하지 않았다. §3.1에서 지적한 `MvpRiskStatus` 5값 모델과의 충돌(§3.1)은 그 작업에서 반드시 해결해야 한다.
- `equipment_history`의 전체 정비/점검 이력을 위한 Activity/Decision/Maintenance/WorkOrder 결합은 이번 범위에 포함하지 않았다(Operations 도메인 후속 계약).
- `features[].baseline`이 없는 feature에 대해 UI가 범위 이탈(crossing) 마커를 어떻게 표시할지는 아직 정의하지 않았다 — 현재 스키마/fixture는 "표시하지 않음"만 보장한다.

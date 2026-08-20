# ADR-003: Asset Detail Report View 계약과 Evidence Coverage 분리

- **상태**: Proposed (제안 — 목표 계약)
- **날짜**: 2026-08-20
- **결정자**: 팀 공통 (검토 진행 중)

---

## 1. 맥락 (Context)

`map-report-ui-prototype`의 설비 상세 리포트 UI를 현행 MVP 화면에 이식하는 과정에서,
기존 MVP Event detail 필드와 신규 그래프/이력 필드의 source가 섞일 위험이 확인됐다.

현행 MVP 프론트엔드는 `MvpEventDetailModel`, `MvpAsset`, `MvpReportModel` 같은
구현 타입을 사용하지만, 제품 API 계약 객체명까지 구현 네임스페이스인 `Mvp` 접두어를
따를 필요는 없다. 또한 현재 Event Evidence는 현재 판단과 근거 설명에는 충분하지만,
피쳐별 시계열 그래프나 runtime risk history를 단독으로 채우는 source가 아니다.

---

## 2. 의사결정 (Decision)

1. **계약 객체명에서 구현 접두어 제거**:
   Product API/schema 계약명에는 `Mvp` 접두어를 붙이지 않는다. 현행 프론트엔드의
   `Mvp*` 타입은 기존 화면이 소비하는 기준 필드 확인용 구현명으로만 사용한다.
   설비 상세 리포트 후보 계약은 `AssetDetailReportViewModel`로 표기한다.
2. **기존 MVP 상세 필드 기준선 유지**:
   asset, 현재 risk/status/action, 현재 센서값, top factors, report section,
   activity, provenance는 현행 MVP 상세 화면의 기준선으로 유지한다.
3. **Evidence Coverage 명시**:
   단일 Event Evidence만으로 모든 상세 리포트 필드를 채울 수 있다고 가정하지 않는다.
   현재 Evidence는 현재 판단/센서/top factor/report citation/provenance를 채울 수 있지만,
   feature 시계열, risk 시계열, crossing marker, 전체 정비/점검 이력은 추가 source가 필요하다.
4. **그래프 source 분리**:
   `features[].series`는 canonical/overlay Observation series 또는 gen_data Layer 2
   `_log.jsonl`을 정규화한 Observation API shape에서 파생한다. `risk_series`는 Backend
   Diagnosis runtime prediction/result timeline에서 파생한다.
5. **fixture를 runtime truth로 승격 금지**:
   `gen_data/canonical/model_outputs/*`의 `prediction_timeline`, `prediction_snapshot`,
   `result_artifact`는 compatibility/regression/migration fixture이며 제품 runtime 최신
   결과처럼 직접 소비하지 않는다.
6. **근거 추적 필드 보존**:
   시계열 point와 baseline은 화면 표시용 `number[]`만 반환하지 않는다. 최소한
   `observed_at`, source reference, quality/status, prediction/result/artifact reference
   또는 evidence field reference를 보존한다.
7. **누락값 합성 금지**:
   값이 없으면 synthetic graph, 임의 baseline, 정상값 보정으로 채우지 않는다. Backend
   adapter는 null, 빈 배열, `evidence.gaps[]`, `data_status.warnings[]`로 unavailable
   상태를 표현한다.

---

## 3. 결과 및 영향 (Consequences)

- Frontend는 raw JSONL, producer 원본 payload, prototype adapter를 직접 파싱하지 않고
  Product API/View 계약만 소비한다.
- UI 이식 전에 현재 MVP ViewModel 소비 필드를 감사하고, `AssetDetailReportViewModel`에
  유지할 기준선 필드와 추가할 그래프/이력 필드를 분리해야 한다.
- `evidence_payload.sensor_evidence`가 API까지 노출되지 않으면 feature baseline은
  일부 또는 전부 unavailable로 표시해야 한다.
- Observation series API 또는 Layer 2 정규화 adapter가 없으면 feature graph는 빈 배열과
  evidence gap으로 표시한다.
- Backend Diagnosis runtime prediction/result timeline이 없으면 risk graph는 빈 배열과
  evidence gap으로 표시한다.
- Playwright/E2E는 그래프 존재 여부만 검증하지 않고, source kind, evidence gaps, quality
  metadata가 유지되는지 함께 검증해야 한다.

이 결정은 `docs/mvp/api-specification.md`,
`docs/mvp/schema-definition.md`,
`docs/mvp/pdm-evidence-report-ui-integration-plan.md`의
`AssetDetailReportViewModel` 후보 계약과 함께 적용한다.

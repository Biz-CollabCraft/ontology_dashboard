# Week 2 리포트 정의서

## 1. 목적과 상태

이 문서는 Executive Report 화면과 LLM 리포트 생성 API가 사용하는 입력,
출력, 문장 규칙, 근거와 실패 대체 계약을 정의한다.

- 문서 상태: `초안 — 팀원4 계약 검토 필요`
- 기준 Dataset: `canonical-ai4i-physics-v3.1`
- 기준 Model: `independent-logreg-v3.1`
- 기준 Result Artifact: `result-artifact-v1.0`

공통 필드명은 [공통 스키마 정의서](./week2-schema-definition.md)를 따른다.

## 2. 사용자와 목적

### 생산 관리자

- 전체 설비의 위험 분포를 확인한다.
- 우선 확인할 설비와 생산·정비 관련 현황을 파악한다.
- 현장 확인 및 운영 검토의 우선순위를 판단한다.

### 임원 또는 의사결정자

- 상세 센서 전체가 아닌 핵심 수치와 주의사항을 확인한다.
- 보고 기간, 데이터 출처와 예측의 한계를 함께 확인한다.

리포트는 예측 결과를 의사결정 자료로 요약하며 고장 발생, 원인 또는 자동 실행을
확정하지 않는다.

## 3. 생성 흐름

```text
Canonical V3.1
→ Result Artifact
→ 검증된 API 집계
→ ReportInput
→ LLM 또는 deterministic generator
→ ReportOutput 검증
→ Executive Report 화면
```

LLM은 입력 데이터를 수정하지 않고, 검증된 사실을 문장으로 변환하는 역할만
수행한다.

## 4. 보고서 생성 요청

상태: `제안`

```json
{
  "as_of": "2026-08-29T23:00:00+09:00",
  "period": {
    "from": "2026-08-23T00:00:00+09:00",
    "to": "2026-08-29T23:00:00+09:00"
  },
  "filters": {
    "site_id": null,
    "cell_id": null,
    "asset_type": null
  },
  "locale": "ko-KR"
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `as_of` | datetime | Y | Result Artifact snapshot 기준시각 |
| `period.from` | datetime | Y | 생산·정비 집계 시작 |
| `period.to` | datetime | Y | 생산·정비 집계 종료 |
| `filters.site_id` | string/null | N | 사이트 필터 |
| `filters.cell_id` | string/null | N | 셀 필터 |
| `filters.asset_type` | enum/null | N | `compressor`, `cnc` |
| `locale` | string | Y | 현재 `ko-KR` |

`as_of`, 기간과 필터의 최종 기본값은 API 명세에서 확정한다.

## 5. LLM 입력 계약

객체명: `ReportInput` · 상태: `제안`

```json
{
  "report_context": {
    "as_of": "2026-08-29T23:00:00+09:00",
    "period_from": "2026-08-23T00:00:00+09:00",
    "period_to": "2026-08-29T23:00:00+09:00",
    "generated_at": "2026-08-30T09:00:00+09:00",
    "locale": "ko-KR"
  },
  "summary": {
    "total_asset_count": 100,
    "operating_asset_count": 96,
    "non_operating_asset_count": 4,
    "status_counts": {
      "normal": 42,
      "attention": 39,
      "warning": 17,
      "critical": 2
    },
    "production_cycle_count": 0,
    "maintenance_event_count": 0
  },
  "top_risk_assets": [],
  "provenance": {
    "dataset_version": "canonical-ai4i-physics-v3.1",
    "model_version": "independent-logreg-v3.1",
    "artifact_schema_version": "result-artifact-v1.0",
    "source": "canonical",
    "warnings": []
  },
  "limitations": [
    "합성 데이터 기반 예측 결과입니다.",
    "예측 확률은 실제 고장 발생을 확정하지 않습니다."
  ]
}
```

예시의 생산·정비 건수는 실제 요청 기간 집계값으로 대체해야 하며 임의의 값을
입력하면 안 된다.

### 5.1 ReportContext

| 필드 | 타입 | 필수 | 출처 |
|---|---|:---:|---|
| `as_of` | datetime | Y | Artifact snapshot |
| `period_from` | datetime | Y | 요청 |
| `period_to` | datetime | Y | 요청 |
| `generated_at` | datetime | Y | Report API |
| `locale` | string | Y | 요청 |

### 5.2 ReportSummary

| 필드 | 타입 | 필수 | 출처 |
|---|---|:---:|---|
| `total_asset_count` | integer | Y | Asset 집계 |
| `operating_asset_count` | integer | Y | 최신 Observation 집계 |
| `non_operating_asset_count` | integer | Y | 전체-가동 |
| `status_counts.normal` | integer | Y | Artifact 집계 |
| `status_counts.attention` | integer | Y | Artifact 집계 |
| `status_counts.warning` | integer | Y | Artifact 집계 |
| `status_counts.critical` | integer | Y | Artifact 집계 |
| `production_cycle_count` | integer | Y | 기간 내 생산 작업 집계 |
| `maintenance_event_count` | integer | Y | 기간 내 정비 집계 |

다음 불변식을 API에서 먼저 검증한다.

```text
operating_asset_count + non_operating_asset_count = total_asset_count
normal + attention + warning + critical = total_asset_count
```

### 5.3 ReportRiskAsset

`top_risk_assets`의 최대 개수는 팀원1·4 합의 후 확정한다. 권장값은 5개다.

| 필드 | 타입 | 필수 | 출처 |
|---|---|:---:|---|
| `asset_id` | string | Y | Artifact |
| `asset_type` | enum | Y | Artifact |
| `site_id` | string | Y | Asset 결합 |
| `cell_id` | string | Y | Asset 결합 |
| `observed_at` | datetime | Y | Artifact |
| `failure_probability` | number | Y | Artifact |
| `predicted_failure_type` | enum | Y | Artifact |
| `status_grade` | enum | Y | Artifact |
| `confidence` | number | Y | Artifact |
| `top_factors` | TopFactor[3] | Y | Artifact |
| `recommended_action` | RecommendedAction | Y | Artifact |
| `prediction_id` | string | Y | Artifact provenance |

## 6. LLM 출력 계약

객체명: `ReportOutput` · 상태: `제안`

```json
{
  "schema_version": "executive-report-v1.0",
  "report_id": "REPORT#2026-08-29T23:00:00+09:00",
  "generated_at": "2026-08-30T09:00:00+09:00",
  "generation_method": "llm",
  "title": "설비 예지보전 주간 요약",
  "executive_summary": "...",
  "risk_overview": "...",
  "priority_assets": [],
  "operations_summary": "...",
  "recommended_next_steps": [],
  "limitations": [],
  "evidence_references": [],
  "provenance": {}
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `schema_version` | string | Y | 제안값 `executive-report-v1.0` |
| `report_id` | string | Y | 보고서 고유 ID |
| `generated_at` | datetime | Y | 생성 시각 |
| `generation_method` | enum | Y | `llm`, `deterministic`, `template` |
| `title` | string | Y | 보고서 제목 |
| `executive_summary` | string | Y | 전체 핵심 요약 |
| `risk_overview` | string | Y | 위험 분포 설명 |
| `priority_assets` | array | Y | 우선 확인 설비 요약 |
| `operations_summary` | string | Y | 생산·정비 집계 설명 |
| `recommended_next_steps` | string[] | Y | 사람이 검토할 다음 행동 |
| `limitations` | string[] | Y | 데이터·예측 한계 |
| `evidence_references` | array | Y | 문장 근거 참조 |
| `provenance` | object | Y | 입력 데이터와 모델 출처 |

### 6.1 PriorityAssetNarrative

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `asset_id` | string | Y | 근거 설비 ID |
| `status_grade` | enum | Y | 입력값 그대로 사용 |
| `failure_probability` | number | Y | 입력값 그대로 사용 |
| `summary` | string | Y | 위험 요인과 확인 필요 사항 |
| `recommended_action` | string | Y | 정책 action의 사용자용 표현 |
| `evidence_reference_ids` | string[] | Y | 근거 ID 목록 |

### 6.2 EvidenceReference

| 필드 | 타입 | 필수 | 설명 |
|---|---|:---:|---|
| `reference_id` | string | Y | 보고서 내부 근거 ID |
| `asset_id` | string | N | 관련 설비 |
| `prediction_id` | string | N | Artifact provenance의 예측 ID |
| `source_field` | string | Y | 근거가 된 JSON path 또는 집계 필드 |
| `source_value` | string/number | Y | 실제 입력값 |

리포트 문장은 `evidence_reference_ids`를 통해 입력값으로 역추적할 수 있어야 한다.

## 7. 보고서 화면 구조

| 순서 | 섹션 | 필수 내용 |
|---:|---|---|
| 1 | 보고 기준 | 기간, `as_of`, 생성시각, 데이터·모델 버전 |
| 2 | 핵심 현황 | 전체·가동·비가동·위험 설비, 생산·정비 건수 |
| 3 | 위험 분포 | 네 등급의 수와 비율 |
| 4 | 상위 위험 설비 | 설비, 확률, 등급, Top factors, 권고 |
| 5 | 운영 요약 | 확인 가능한 생산·정비 현황 |
| 6 | 다음 단계 | 점검·검토 권고; 자동 실행 아님 |
| 7 | 한계와 출처 | 합성 데이터, 예측 한계, provenance |

## 8. 문장 규칙

### 8.1 필수 원칙

- 입력에 있는 수치와 enum을 변경하지 않는다.
- 확률을 실제 고장 발생으로 표현하지 않는다.
- `predicted_failure_type`을 개별 고장 모드로 확장 해석하지 않는다.
- Top factor를 확정 원인으로 표현하지 않는다.
- 관계 topology를 인과관계로 표현하지 않는다.
- 권고를 자동 정지, 정비 명령 또는 실행 완료로 표현하지 않는다.
- 데이터 누락, stale, fallback과 낮은 confidence를 숨기지 않는다.
- 합성 데이터라는 한계를 항상 포함한다.

### 8.2 권장 표현

- `위험 증가에 영향을 준 주요 요인`
- `점검이 필요한 후보`
- `현재 입력에서 관찰된 근거`
- `현장 확인 후 판단 필요`
- `정지 여부 검토`

### 8.3 금지 표현

- `고장이 확정되었습니다`
- `이 센서가 고장의 원인입니다`
- `즉시 설비를 정지했습니다`
- `정비 지시가 자동 발행되었습니다`
- `비용이 절감되었습니다` — 검증된 비용 입력이 없는 경우
- `생산 손실이 발생합니다` — 검증된 영향 모델이 없는 경우

## 9. 상태별 예시

### normal

> 현재 예측 결과에서 유의한 24시간 내 고장 위험은 확인되지 않았습니다. 최신
> 관측시각과 데이터 신선도를 확인하며 모니터링을 계속합니다.

### attention

> 일부 지표가 위험 증가 방향에 기여해 관심 단계로 분류되었습니다. 확정적인
> 고장 신호는 아니며 대상 요인을 중심으로 진단 점검을 계획할 필요가 있습니다.

### warning

> 현재 교대조 안에 확인이 필요한 경고 단계입니다. 상위 기여 요인은 위험 판단의
> 근거이며 현장 점검 전까지 고장 원인으로 확정하지 않습니다.

### critical

> 우선 점검이 필요한 심각 단계입니다. 설비 상태와 안전 조건을 확인한 뒤 정지
> 검토 여부를 사람이 결정해야 하며 시스템이 자동으로 설비를 정지하지 않습니다.

## 10. 실패 대체 계약

생성 순서:

```text
LLM
→ deterministic summary
→ template fallback
```

| 실패 | 처리 | 사용자 표시 |
|---|---|---|
| LLM timeout/provider 오류 | deterministic 생성 | `자동 요약으로 대체` |
| deterministic 생성 오류 | template 생성 | `기본 보고 형식으로 대체` |
| 입력 계약 오류 | 생성 중단 | 잘못된 필드와 오류 코드 표시 |
| 입력 데이터 없음 | empty report | 임의의 정상 수치 생성 금지 |
| stale/fallback 입력 | 생성 가능 | 경고와 source를 보고서에 포함 |

fallback이 사용돼도 `ReportOutput` 구조를 유지하고 `generation_method`에 생성
방식을 기록한다.

## 11. API 오류 계약 제안

| HTTP | 코드 | 조건 |
|---:|---|---|
| 400 | `invalid_report_period` | 기간 형식 또는 순서 오류 |
| 404 | `report_source_not_found` | 조건에 맞는 데이터 없음 |
| 409 | `snapshot_mismatch` | 요청 기준시각과 집계 snapshot 불일치 |
| 422 | `report_contract_validation_failed` | 입력·출력 schema 검증 실패 |
| 503 | `report_generation_unavailable` | 모든 생성 단계 실패 |

최종 경로와 공통 오류 envelope는 API 명세에서 확정한다.

## 12. 검증 기준

| ID | 테스트 |
|---|---|
| RPT-TC-001 | 보고서 집계가 같은 조건의 Overview와 일치한다. |
| RPT-TC-002 | 모든 우선 설비가 입력 `top_risk_assets`에 존재한다. |
| RPT-TC-003 | 확률, 등급과 버전이 입력과 일치한다. |
| RPT-TC-004 | 모든 주요 문장에 유효한 evidence reference가 있다. |
| RPT-TC-005 | 금지 표현과 입력에 없는 수치가 없다. |
| RPT-TC-006 | LLM 실패 시 deterministic 결과를 반환한다. |
| RPT-TC-007 | 모든 생성 실패 시 template 또는 명시적 오류를 반환한다. |
| RPT-TC-008 | stale/fallback/low confidence 경고가 보존된다. |
| RPT-TC-009 | evaluation truth가 입력·출력에 노출되지 않는다. |
| RPT-TC-010 | `generation_method`와 provenance가 항상 존재한다. |

## 13. 팀원4 확인 사항

| ID | 확인할 결정 |
|---|---|
| RPT-DEC-01 | 실제 보고서 생성 API 경로와 Method |
| RPT-DEC-02 | `ReportInput` 필드와 최대 상위 설비 수 |
| RPT-DEC-03 | `ReportOutput` schema version과 필수 섹션 |
| RPT-DEC-04 | evidence reference 구현 방식 |
| RPT-DEC-05 | deterministic/template fallback 구현 위치 |
| RPT-DEC-06 | provider timeout, retry와 최대 생성시간 |
| RPT-DEC-07 | 추가 금지 표현과 사용자 고지 문구 |


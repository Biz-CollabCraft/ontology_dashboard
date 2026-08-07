# Week 2 API 명세서

## 1. 기준과 상태

이 문서는 목표 REST 계약안이다. 현행 API는
[현행 MVP 구현 계약 기준선](./current-mvp-implementation-baseline.md)을 따르며, 아래
`/overview`, `/objects`, `/operations`와 page/size 계약은 모두 `변경 제안`이다.
JSON key 목표안은 [스키마 정의서](./week2-schema-definition.md)를 따른다.

책임 분리:

- 팀원3: `/overview`, `/objects`, `/operations` 등 조회·집계 API와 ReportInput에
  필요한 원천·집계 필드 제공
- 팀원4: 현행 Event Report 및 V2 `/reports/executive` 리포트 API 계약·구현
- 팀원2: API·스키마·리포트 계약 문서화와 추적성 관리

## 1.1 현행 API 계약

Canonical base path:

```text
/api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance
```

| Method | Path | 상태 |
|---|---|---|
| GET | `/dashboard` | 현행 구현 |
| GET | `/results/latest` | 현행 구현 |
| GET | `/api/events/{event_id}/evidence` | 현행 구현 |
| POST | `/api/events/{event_id}/report` | 현행 구현 |
| POST | `/api/events/{event_id}/decision` | 현행 구현 |
| POST | `/api/events/{event_id}/notes` | 현행 구현 |
| GET | `/api/events/{event_id}/activity` | 현행 구현 |

`/results/latest`는 `offset`, `limit`, `total`을 사용하며 `limit` 기본값은 100,
최대값은 500이다.

변경 제안 base path: `/api`

## 2. 공통 Query

아래 Query는 현행 설명이 아닌 변경 제안이다.

| Parameter | 타입 | 설명 |
|---|---|---|
| `site_id` | string | 사이트 필터 |
| `cell_id` | string | 셀 필터 |
| `asset_type` | enum | `compressor`, `cnc` |
| `status_grade` | enum | 네 위험 등급 |
| `data_quality_hold` | boolean | ViewModel 품질 보류 필터; 위험 enum과 별도 |
| `from` | datetime | 기간 시작 |
| `to` | datetime | 기간 종료 |
| `page` | integer | 기본 1 |
| `size` | integer | 기본 20, 최대값 합의 필요 |

## 3. Endpoint

아래 Endpoint는 현행 경로 대체 또는 호환 계층이 필요한 변경 제안이다.

| Method | Path | 목적 | 화면 |
|---|---|---|---|
| GET | `/overview` | 전체 설비·위험·운영 요약 | Overview |
| GET | `/objects` | 설비 목록 | Objects |
| GET | `/objects/{asset_id}` | 설비 상세 | Objects |
| GET | `/objects/{asset_id}/observations` | 센서 추세 | Objects |
| GET | `/objects/{asset_id}/maintenance` | 정비 이력 | Objects |
| GET | `/operations` | 생산·정비 요약 | Operations |
| GET | `/operations/production` | 생산 작업 목록 | Operations |
| GET | `/operations/maintenance` | 정비 이력 목록 | Operations |
| POST | `/reports/executive` | 보고서 생성 | Executive Report |

채택 전에는 현행 API를 유지한다. 채택 시 호환 계층·호출부·테스트 전환 계획을
함께 정의한다.

## 4. 응답 계약

### 4.1 목록 envelope

```json
{
  "items": [],
  "page": 1,
  "size": 20,
  "total": 100,
  "as_of": "2026-08-29T23:00:00+09:00",
  "data_status": {
    "source": "canonical",
    "is_stale": false,
    "last_updated_at": "2026-08-29T23:00:00+09:00",
    "warnings": []
  }
}
```

### 4.2 `GET /overview`

응답: `OverviewSummary`. 등급 합과 가동 합 불변식을 만족해야 한다.

현행 Overview는 `/dashboard` 응답으로 위험 KPI·Downtime·판단 대기 Event를
구성한다. `/overview`와 가동·생산·정비 집계는 V2 변경 제안이다.

### 4.3 `GET /objects`

응답 items: `AssetPredictionSummary[]`.

기본 정렬: 위험 등급 우선 후 `failure_probability desc`, `asset_id asc`.

현행 Objects는 `/results/latest`의 offset/limit 결과를 검색·라인·상태·담당자로
클라이언트 필터링한다. site/cell/유형/기간 Query는 V2 변경 제안이다.

### 4.4 `GET /objects/{asset_id}`

응답: `AssetDetail`.

```json
{
  "asset": {},
  "latest_observation": null,
  "prediction": null,
  "relations": [],
  "maintenance_events": [],
  "data_status": {}
}
```

없는 값을 임의 객체로 채우지 않는다.

### 4.5 `GET /objects/{asset_id}/observations`

필수 Query: `from`, `to`. 선택 Query: 반복 가능한 `sensor`.

```json
{
  "asset_id": "CNC-S01-L01-01",
  "asset_type": "cnc",
  "from": "2026-08-29T17:00:00+09:00",
  "to": "2026-08-29T23:00:00+09:00",
  "observations": []
}
```

설비 유형에 존재하지 않는 센서 key는 400으로 처리한다.

### 4.6 Operations

`GET /operations`는 같은 필터의 생산·정비 목록 합계와 일치하는 요약을 반환한다.
생산 행의 위험 등급은 `cnc_asset_id`와 동일 snapshot Artifact를 결합한 파생값이다.

### 4.7 `POST /reports/executive`

현행은 `POST /api/events/{event_id}/report`에서
`ReportRequest(role, locale, use_llm)`와 role-aware grounded report를 사용한다.

`POST /reports/executive`는 [리포트 정의서](./week2-report-specification.md)의 V2
`ReportInput`/`ReportOutput` 후보이며 현행 API를 대체하지 않는다. 이번 단계에서는
팀원4가 담당하며, 이번 단계에서는 endpoint를 수정·구현하지 않고 mock 입력과
deterministic 출력 계약부터 검증한다.

## 5. 오류 envelope

```json
{
  "error": {
    "code": "invalid_filter",
    "message": "요청 조건을 확인하십시오.",
    "details": []
  }
}
```

| HTTP | code | 조건 |
|---:|---|---|
| 400 | `invalid_filter` | enum·기간·센서 오류 |
| 404 | `asset_not_found` | 자산 없음 |
| 409 | `snapshot_mismatch` | 기준 snapshot 불일치 |
| 422 | `contract_validation_failed` | 응답·보고서 계약 오류 |
| 503 | `canonical_unavailable` | Canonical 사용 불가, fallback 미허용 |
| 503 | `report_generation_unavailable` | 모든 보고서 생성 방식 실패 |

## 6. 출처·버전 계약

- 목록은 `as_of`, `data_status`를 포함한다.
- 상세은 Result Artifact의 원본 `provenance`를 보존한다.
- `site_id`, `cell_id`는 Asset 결합 필드다.
- fallback 사용 시 `source=fallback`과 warning을 반환한다.
- evaluation truth를 반환하지 않는다.

## 7. 확인 필요

- 현행 API 유지 또는 목표 경로로 전환할지
- offset/limit 유지 또는 page/size로 전환할지
- status grade 임계값 산출 주체
- latest snapshot과 stale 기준
- 인증·권한 포함 여부
- fallback 허용 조건
- 보고서 생성 timeout과 retry


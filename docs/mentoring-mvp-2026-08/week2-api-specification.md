# Week 2 API 명세서

## 1. 기준과 상태

이 문서는 화면과 LLM이 사용하는 REST 계약안이다. 실제 구현 담당자 확인 전 경로와
pagination은 `제안` 상태다. JSON key는 [스키마 정의서](./week2-schema-definition.md)를
따른다.

Base path 제안: `/api`

## 2. 공통 Query

| Parameter | 타입 | 설명 |
|---|---|---|
| `site_id` | string | 사이트 필터 |
| `cell_id` | string | 셀 필터 |
| `asset_type` | enum | `compressor`, `cnc` |
| `status_grade` | enum | 네 위험 등급 |
| `from` | datetime | 기간 시작 |
| `to` | datetime | 기간 종료 |
| `page` | integer | 기본 1 |
| `size` | integer | 기본 20, 최대값 합의 필요 |

## 3. Endpoint

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

기존 구현 API가 있으면 위 경로를 강제하지 않고 동일 책임·응답 계약을 매핑한다.

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

### 4.3 `GET /objects`

응답 items: `AssetPredictionSummary[]`.

기본 정렬: 위험 등급 우선 후 `failure_probability desc`, `asset_id asc`.

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

요청과 응답은 [리포트 정의서](./week2-report-specification.md)의
ReportRequest/ReportOutput을 따른다. LLM 실패 시에도 성공한 fallback 결과는 200과
`generation_method`를 반환한다.

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

- 실제 Base path와 기존 구현 경로 매핑
- page/cursor 방식 및 최대 크기
- status grade 임계값 산출 주체
- latest snapshot과 stale 기준
- 인증·권한 포함 여부
- fallback 허용 조건
- 보고서 생성 timeout과 retry


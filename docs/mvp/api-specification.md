# MVP API 명세서

## 1. 기준과 상태

이 문서는 목표 REST 계약안이다. 현행 API는
[현행 MVP 구현 계약 기준선](./current-mvp-implementation-baseline.md)을 따르며, 아래
`/overview`, `/objects`, `/operations`와 page/size 계약은 모두 `변경 제안`이다.
JSON key 목표안은 [스키마 정의서](./schema-definition.md)를 따른다.

책임 분리:

- 팀원3: `/overview`, `/objects`, `/operations` 등 조회·집계 API와 ReportInput에
  필요한 원천·집계 필드 제공
- 팀원4: 현행 Event Report 및 V2 `/reports/executive` 리포트 API 계약·구현
- 팀원2: API·스키마·리포트 계약 문서화와 추적성 관리

> 이 문서는 Backend 제품 API 계약이다. Generator daemon의 내부 학습 API는 Generator 내부
> 운영 계약을 따른다. Generator 내부 API는 외부 제품
> prediction API가 아니며, `/health`, `/internal/train`, `/internal/retrain`과 같은 학습 운영
> 엔드포인트만 제공한다. 상세 허용/금지 범위는
> `docs/architecture-decisions/ADR-002-training-runtime-prediction-ownership.md`를 따른다.

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

현재 MVP Objects는 검색·라인·상태·담당자 필터와 현행 URL 상태를 유지한다. 아래
site/cell/유형/기간 Query는 Target이며 이번 주 필수 변경이 아니다.

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

### 4.6 `GET /objects/{asset_id}/report-detail`

상태: V2 변경 제안. 현행 Event Report API나 `/objects/{asset_id}`를 대체하지 않는다.

응답: `AssetDetailReportViewModel`.

설비 상세 리포트, 피쳐별 센서 그래프, 위험도 그래프, evidence gap 표시를 위한 composition endpoint 후보이다. Backend adapter가 Product Result Artifact/Evidence, canonical 또는 overlay Observation series, Backend Diagnosis runtime prediction/result series, Activity/Maintenance source를 병합한다.

필수 Query: `from`, `to`. 선택 Query: `dataset_version_id`, `grain=raw|10m|1h`.

```json
{
  "asset": {},
  "risk": {},
  "risk_series": [],
  "features": [],
  "equipment_history": [],
  "evidence": {
    "artifact_id": null,
    "source_kind": "runtime_inference",
    "gaps": []
  },
  "data_status": {}
}
```

`features[].series`는 Observation source에서 파생할 수 있다. `risk_series`는 운영 Result/Prediction runtime source에서 파생해야 하며, `gen_data`의 `model_outputs/prediction_timeline.jsonl`을 최신 운영 결과처럼 직접 읽어 대체하지 않는다.

없는 값은 합성하지 않고 null, 빈 배열, `evidence.gaps[]`, `data_status.warnings[]`로 표현한다.

### 4.7 Operations

`GET /operations`는 같은 필터의 생산·정비 목록 합계와 일치하는 요약을 반환한다.
생산 행의 위험 등급은 `cnc_asset_id`와 동일 snapshot Artifact를 결합한 파생값이다.

### 4.8 `POST /reports/executive`

현행은 `POST /api/events/{event_id}/report`에서
`ReportRequest(role, locale, use_llm)`와 role-aware grounded report를 사용한다.

`POST /reports/executive`는 [리포트 정의서](./report-specification.md)의 V2
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
- 현재 MVP stale은 timezone을 포함한 `observed_at` 기준 프론트 24시간 판정을
  유지한다. 이는 도메인 불변값이 아니라 현재 MVP freshness 정책이다.
- provenance는 구조화해 보존하되 `source_field`는 현행 Evidence 호환 형식을
  사용한다. JSON Pointer는 구현 비교 후 Target으로 검토한다.

## 7. 결정 반영과 후속 확인

### 2026-08 Week 2 결정 기록

- 현행 `/dashboard`, `/results/latest`와 Event API를 유지한다.
- Closed-loop 확장은 기존 Event API key를 삭제·rename하지 않는 additive extension으로 유지하며,
  역할별 Action과 mutation 응답은
  [`../closed-loop-product-consumption-contract.md`](../closed-loop-product-consumption-contract.md)를 따른다.
- 정비 후 Runtime Overlay의 Target 상태는 `equipment_under_maintenance`, `warming_up`,
  `history_insufficient`, `ready`, `predicted`를 사용한다. 기존 Result의 `status_grade`를
  이 준비 상태로 덮어쓰지 않는다.
- Runtime Overlay readiness는 Backend Diagnosis가 현재 Model Artifact의
  `history_requirement.json`으로 결정한다. `gen_data`는 Overlay Observation을 지속
  생성하고 availability를 알릴 뿐 readiness를 판정하지 않는다. 진행률 필드의 구체적인
  shape는 canonical read location과 함께 후속 Backend integration에서 결정한다.
- Runtime Overlay의 이벤트·Observation lineage는
  [`../closed-loop-runtime-overlay-contract.md`](../closed-loop-runtime-overlay-contract.md)를 따른다.
- Observation `source_kind`는 Target 구현에서 `canonical_observation` 또는
  `maintenance_replay_overlay`를 반환한다. Overlay 응답은 `simulation_session_id`,
  `overlay_branch_id`, `maintenance_event_id`, `history_segment_id`를 함께 보존한다.
- 최신 결과 pagination은 `offset`, `limit`, `total`을 유지한다.
- `status_grade`는 runtime inference가 생성하는 Result Artifact 계약에 포함한다.
- stale은 timezone을 포함한 최신 `observed_at` 기준 프론트 24시간 MVP 정책을 유지한다.
- Identity/RBAC는 `process_manager`, `process_engineer`, `maintenance_technician` role code를 사용하고,
  기존 `manager`/`engineer`는 Report/UI compatibility view alias로 유지한다.
- fallback은 로컬 데모 compatibility 경로에서 명시적으로 표시하며, Model Artifact가
  필요한 비로컬 실행 환경은 fail-closed를 따른다.

### 후속 확인

- 보고서 생성 timeout과 retry 정책
- V2 목표 경로와 `page`/`size` 계약 채택 여부 및 전환 계획
- **Deferred:** Product API의 canonical runtime-status read location은 `gen_data` Runtime
  Overlay의 versioned Observation/status handoff 계약 확정 이후 Backend integration
  단계에서 결정한다. 후보는 Event `closed_loop` envelope, Equipment 상태 API 또는 별도
  runtime status endpoint이며, 결정 시 OpenAPI·Frontend adapter·E2E를 함께 갱신한다.
- `warming_up` 진행률 필드와 `history_insufficient` 사유 envelope

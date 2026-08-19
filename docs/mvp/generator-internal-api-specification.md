# Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 제어 API**의 계약이다. [API 명세서](./api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: `generator` 파이프라인(추출/매핑/feature/학습 및 Model Artifact 발행) 구현 담당자

## 2. 책임 경계 (허용 / 금지 범위)

[런타임 소유권 통합 계약](./runtime-ownership-integration.md) 및 ADR-002 Invariant 22·23에 따라 다음 경계를 엄격히 준수한다:

### 허용 범위
- `GET /health` (데몬 상태 확인)
- `POST /extraction` (데이터셋 분석 및 내용 기반 해시 Extraction Plan/Mapping 수립·검증·불변 영속화)
- `POST /feature` (Extraction Plan/Mapping 소비, Feature·Label 생성 및 NPY 불변 발행)
- `POST /train` (다중 모델 학습 및 Model Artifact 발행 - 후속 구현 대상)
- `POST /internal/train` (파이프라인 최초 학습 실행, 단일 프로세스 Lock 하에 실행)
- `POST /internal/retrain` (새 버전 재학습 실행, 기존 모델을 덮어쓰지 않고 새 버전으로 저장)
- 학습 job 상태 또는 Model Artifact publish 상태(`published_artifacts`, `artifact_uri`, `has_any_published_model_artifact`, `run_id`) 조회

### 금지 범위
- `POST /internal/predict`, `POST /internal/predict/file`
- 사용자 요청 기반 runtime inference
- `data_preprocessed/predictions/*.json` 파일 생성
- Product Result Artifact / Evidence 생성
- `PredictionOutput` 등 Backend runtime 응답 형식 노출
- Frontend의 Generator 직접 호출

> **참고**: Runtime inference와 Product Result Artifact/Evidence의 소유자는 `systems/backend/app/diagnosis`이다.

## 3. Endpoint

| Method | Path | 목적 | 상태 |
|---|---|---|---|
| GET | `/health` | 데몬 프로세스 상태 확인 | 완료 |
| POST | `/extraction` | 데이터셋 분석 및 Extraction Plan/Mapping 수립·검증·불변 영속화 (1단계) | 완료 |
| POST | `/feature` | Extraction Plan/Mapping 소비, Feature·Label 생성 및 NPY/메타데이터 불변 발행 (2단계) | 완료 |
| POST | `/train` | 다중 ML 모델 학습 및 Model Artifact 발행 | **후속 PR 대상 (미구현)** |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어) | 완료 |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어) | 완료 |

## 4. 요청/응답 계약

### 4.1 `GET /health`

**성공 응답 본문:**

```json
{
  "status": "ok",
  "system": "generator"
}
```

---

### 4.2 `POST /extraction`

> **단계 범위 및 내용 기반 버전(Content-Addressed) 정책 명시**:
> - `/extraction`은 Extraction Plan 및 Ontology Mapping 수립·검증·영속화 전용 엔드포인트입니다.
> - Plan과 Mapping의 canonical JSON에 대한 SHA-256 fingerprint 앞 16자리를 실제 식별 버전(`extraction-plan-<hash>`, `ontology-mapping-<hash>`)으로 사용합니다.
> - 매핑 생성 실패 시 `/extraction` 요청은 실패 처리됩니다.
> - Plan 및 Mapping은 불변(immutable)으로 저장되며 동일 버전을 덮어쓰지 않습니다.
> - Feature·Label·NPY 생성(`/feature`) 및 모델 학습·Artifact 발행(`/train`)은 후속 단계이며, `/extraction`이 후속 단계를 자동 실행하지 않습니다.

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "source_uri": "data_preprocessed/ai4i/input.csv",
  "force_reanalyze": false,
  "duplicate_policy": "error",
  "aggregation": null
}
```

**성공 응답 본문:**

```json
{
  "request_id": "req-9c8f2a1b",
  "run_id": "extraction-3d4e5f6a",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-a1b2c3d4e5f67890",
  "result": {
    "extraction_type": "tabular_column_as_attribute",
    "id_column": "UDI",
    "time_column": null,
    "attribute_column": null,
    "value_column": null,
    "duplicate_policy": "error",
    "aggregation": null,
    "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
    "mapping_uri": "models_store/cache/mappings/ai4i/canonical-ai4i-physics-v3.1/ontology-mapping-b2c3d4e5f6789012.json"
  }
}
```

---

### 4.3 `POST /feature`

> **단계 범위 및 안전 원칙 명시**:
> - `POST /feature`는 이미 발행된 `ExtractionPlan` 및 `OntologyMapping`을 조회·무결성 검증하여 소비합니다.
> - `feature_schema_version`으로 Feature Schema를 조회하여 선언된 `feature_names` allowlist에 따라 X 행렬을 구성합니다 (알파벳 정렬 금지, 선언 순서 유지, 선언 외 숫자 컬럼 배제).
> - `(dataset_id, dataset_version, extraction_plan_version, mapping_version, feature_schema_version, label_schema_version, prediction_horizon_hours)` 계약에 대한 SHA-256 해시로 `feature-dataset-{fingerprint}` 버전을 결정합니다.
> - 원본 데이터셋의 기존 label 컬럼을 신뢰하지 않고 공식 failure event 데이터셋을 기준으로 `[anchor - horizon, anchor)` 구간을 계산합니다.
> - 고장 데이터 누락 시 `FAILURE_DATA_NOT_READY` (404), Positive 고장 샘플 0건 시 `INSUFFICIENT_POSITIVE_SAMPLES` (422)로 fail-fast합니다.
> - 불변 디렉터리 구조로 원자적 publish를 수행하며 기존 동일 버전 디렉터리를 선삭제하거나 덮어쓰지 않습니다 (계약 불일치 시 409 `FEATURE_DATASET_CONFLICT`).

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-a1b2c3d4e5f67890",
  "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
  "feature_schema_version": "ai4i-feature-v1",
  "label_schema_version": "ai4i-label-v1",
  "prediction_horizon_hours": 24,
  "rebuild_npy": true
}
```

**성공 응답 본문:**

```json
{
  "request_id": "req-9c8f2a1b",
  "run_id": "feature-7b8c9d0e",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-a1b2c3d4e5f67890",
  "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
  "feature_schema_version": "ai4i-feature-v1",
  "label_schema_version": "ai4i-label-v1",
  "outputs": {
    "feature_dataset_version": "feature-dataset-c3d4e5f678901234",
    "row_count": 10000,
    "feature_count": 5,
    "features_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-c3d4e5f678901234/features.npy",
    "labels_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-c3d4e5f678901234/labels.npy",
    "metadata_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-c3d4e5f678901234/feature_metadata.json"
  }
}
```

---

### 4.4 `POST /internal/train` 및 `POST /internal/retrain`

**성공 응답 본문:**

```json
{
  "run_id": "train-run-001",
  "status": "succeeded",
  "published_artifacts": [
    {
      "model_id": "pdm-cnc-tool-wear-lightgbm",
      "model_version": "v1.0",
      "artifact_uri": "models_store/artifacts/pdm-cnc-tool-wear-lightgbm/v1.0"
    }
  ]
}
```

---

### 4.5 공통 표준 오류 응답 (`ErrorEnvelope`)

모든 에러 응답(4xx, 5xx)은 FastAPI 기본 `{"detail": ...}` 구조 대신 일관된 `ErrorEnvelope` 포맷을 반환합니다:

```json
{
  "error": {
    "code": "ONTOLOGY_MAPPING_NOT_READY",
    "message": "요청한 Ontology Mapping이 없습니다 (dataset_id='ai4i', version='canonical-ai4i-physics-v3.1'). 먼저 POST /extraction을 실행해 주세요.",
    "path": "/feature",
    "request_id": "req-9c8f2a1b",
    "error_id": "err-7a8b9c0d",
    "details": []
  }
}
```

#### 도메인 오류 코드 체계

| HTTP 상태 코드 | 도메인 오류 코드 (`code`) | 원인 및 설명 |
|---|---|---|
| 400 / 422 | `REQUEST_VALIDATION_ERROR` | 요청 JSON 스키마 필드 누락 또는 형식 불일치 |
| 404 | `DATASET_NOT_FOUND` | 요청한 dataset_id 또는 source_uri 파일 부재 |
| 404 | `EXTRACTION_PLAN_NOT_READY` | `/feature` 실행 전 필수 `/extraction` 산출물 부재 |
| 404 | `ONTOLOGY_MAPPING_NOT_READY` | `/feature` 실행 전 필수 Ontology Mapping 산출물 부재 |
| 404 | `FAILURE_DATA_NOT_READY` | 학습 라벨링에 필요한 고장 이력 데이터 부재 |
| 405 | `METHOD_NOT_ALLOWED` | 허용되지 않은 HTTP 메서드 호출 |
| 409 | `FEATURE_DATASET_CONFLICT` | 동일 Feature Dataset 버전 디렉터리가 이미 존재하나 계약 내용이 불일치함 |
| 422 | `EXTRACTION_PLAN_INTEGRITY_ERROR` | Extraction Plan의 내용 해시와 요청된 버전 불일치 |
| 422 | `ONTOLOGY_MAPPING_INTEGRITY_ERROR` | Ontology Mapping의 내용 해시와 요청된 버전 불일치 |
| 422 | `EXTRACTION_PLAN_CONTRACT_INVALID` | Extraction Plan 파일 손상 또는 스키마 위반 |
| 422 | `ONTOLOGY_MAPPING_CONTRACT_INVALID` | Ontology Mapping 파일 손상 또는 스키마 위반 |
| 422 | `FEATURE_SCHEMA_MISMATCH` | Feature Schema 미존재, allowlist 컬럼 부재, 누수 컬럼 포함 등 |
| 422 | `LABEL_CONTRACT_INVALID` | 라벨 컬럼 부재 또는 값이 `{0, 1}` 범위를 벗어남 |
| 422 | `LABEL_ANCHOR_NOT_FOUND` | id, time 또는 failure anchor 결정을 할 수 없음 |
| 422 | `INSUFFICIENT_POSITIVE_SAMPLES` | 고장 예측 구간 내 Positive 고장 샘플 0건 |
| 422 | `INSUFFICIENT_TRAINING_DATA` | 유효 데이터 행 수 0건 등 학습 데이터 부족 |
| 422 | `NPY_VALIDATION_ERROR` | NPY 행렬 shape, dtype, NaN/Inf 불일치 |
| 500 | `EXTRACTION_PLAN_PUBLISH_ERROR` | 추출 계획 또는 온톨로지 매핑 파일 저장 실패 |
| 500 | `NPY_PUBLISH_ERROR` | NPY 산출물 디렉터리 저장 실패 |
| 500 | `INTERNAL_SERVER_ERROR` | 처리 중 발생한 예기치 않은 서버 내부 오류 |

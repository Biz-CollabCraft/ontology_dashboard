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
- `POST /feature` (Extraction Plan/Mapping 및 명시적 Failure 데이터셋 소비, Feature·Label 생성 및 NPY 불변 발행)
- `POST /train` (등록된 전체 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행)
- `POST /train/{base_model}` (지정된 단일 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행)
- `POST /internal/train` (기존 legacy 호환 API: 파이프라인 최초 학습 실행, 단일 프로세스 Lock 하에 실행)
- `POST /internal/retrain` (기존 legacy 호환 API: 새 버전 재학습 실행, 기존 모델을 덮어쓰지 않고 새 버전으로 저장)
- 학습 job 상태 또는 Model Artifact publish 상태(`published_artifacts`, `artifact_uri`, `has_any_published_model_artifact`, `run_id`) 조회

> **학습 API 경로 상태 및 전환 원칙**:
> - 신규 호출자는 canonical API인 `POST /train` 및 `POST /train/{base_model}` 계약을 사용해야 합니다.
> - `POST /internal/train` 및 `POST /internal/retrain`은 기존 기능 호환을 위한 레거시 경로이며, canonical 서비스와 동일한 학습 Lock을 공유합니다.
> - 장기적으로 레거시 경로는 후속 리팩터링 PR에서 정리될 예정입니다.

### 금지 범위
- `POST /internal/predict`, `POST /internal/predict/file`
- 사용자 요청 기반 runtime inference
- `data_preprocessed/predictions/*.json` 파일 생성
- Product Result Artifact / Evidence 생성
- `PredictionOutput` 등 Backend runtime 응답 형식 노출
- Frontend의 Generator 직접 호출

---

## 3. Endpoint

| Method | Path | 목적 | 상태 |
|---|---|---|---|
| GET | `/health` | 데몬 프로세스 상태 확인 | 완료 |
| POST | `/extraction` | 데이터셋 분석 및 Extraction Plan/Mapping 수립·검증·불변 영속화 (1단계) | 완료 |
| POST | `/feature` | Extraction Plan/Mapping 및 Failure 데이터 소비, Feature·Label 생성 및 NPY/메타데이터 불변 발행 (2단계) | 완료 |
| POST | `/train` | 등록된 전체 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행 (3단계) | 완료 |
| POST | `/train/{base_model}` | 지정된 개별 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행 (3단계) | 완료 |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어) | 기존 legacy 호환 API |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어) | 기존 legacy 호환 API |

---

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

> **단계 범위, 식별자 검증 및 부분 발행 정책**:
> - `source_uri`는 `PATHS.data_dir` 또는 `PATHS.data_preprocessed` 내부의 상대경로만 허용되며 절대경로 및 traversal(`..`)은 `DATASET_PATH_NOT_ALLOWED` (422)로 거절됩니다.
> - `dataset_id` 및 `dataset_version`은 `^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$` 정규식으로 검증됩니다.
> - Plan과 Mapping은 canonical JSON에 대한 SHA-256 fingerprint 앞 16자리를 실제 식별 버전(`extraction-plan-<hash>`, `ontology-mapping-<hash>`)으로 독립 저장합니다.
> - 기존 파일이 존재할 경우 내용 해시 및 스키마 무결성을 검증한 후 일치할 때만 재사용하며, 손상된 파일은 덮어쓰지 않고 에러를 반환합니다.
> - `/extraction` 성공은 두 버전이 모두 정상 생성되어 응답에 반환된 경우를 의미합니다. Plan만 존재하면 `/feature` 단계는 거부됩니다.
> - 매핑 생성 시 전역 `mapping_cache.json`을 수정하지 않습니다 (`persist=False`).

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "source_uri": "ai4i/input.csv",
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
    "selected_columns": ["Air temperature [K]", "Process temperature [K]", "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]"],
    "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
    "mapping_uri": "models_store/cache/mappings/ai4i/canonical-ai4i-physics-v3.1/ontology-mapping-b2c3d4e5f6789012.json"
  }
}
```

---

### 4.3 `POST /feature`

> **Feature 계약, 무결성 검증 및 재사용 정책**:
> - `POST /feature`는 이미 발행된 `extraction_plan_version`과 `mapping_version`을 조회 및 검증하고, 요청에 명시된 `failure_dataset_id`, `failure_dataset_version`을 소비합니다.
> - 요청 전 `LabelSchemaProvider`를 통해 `label_schema_version`의 실제 정의를 로드하고 `prediction_task`, `prediction_horizon_hours`, `positive_class`, `anchor_semantic`을 사전 검증합니다 (`LABEL_SCHEMA_MISMATCH`, 422).
> - 9개 계약 요소(`dataset_id`, `dataset_version`, `failure_dataset_id`, `failure_dataset_version`, `extraction_plan_version`, `mapping_version`, `feature_schema_version`, `label_schema_version`, `prediction_horizon_hours`)를 기반으로 SHA-256 fingerprint 앞 16자리를 계산하여 불변 `feature_dataset_version`(`feature-dataset-<fingerprint>`)을 부여합니다.
> - 기존 디렉터리가 존재할 경우 `validate_feature_bundle`을 실행하여 4개 필수 파일 존재, NPY shape, dtype, NaN/Inf 부재, `{0, 1}` 값 범위, 9개 계약 일치, fingerprint 재계산 일치를 전수 검증합니다 (`FEATURE_DATASET_INTEGRITY_ERROR`, 422).

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "failure_dataset_id": "ai4i_failures",
  "failure_dataset_version": "canonical-ai4i-failures-v1",
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
  "run_id": "feature-5e6f7a8b",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "failure_dataset_id": "ai4i_failures",
  "failure_dataset_version": "canonical-ai4i-failures-v1",
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

### 4.4 `POST /train` 및 `POST /train/{base_model}` (Canonical API)

> **학습 오케스트레이션 및 Model Artifact 발행 원칙**:
> - 불변 Feature Dataset Bundle(`features.npy`, `labels.npy`, `feature_columns.json`, `feature_metadata.json`)의 무결성을 전수 검증한 후 학습을 진행합니다.
> - 설비 식별자(`asset_id`)와 타임스탬프(`timestamp`) 기반의 시간순 데이터 분할(`asset_time_split`)을 수행하여 미래 데이터 누수를 방지합니다 (`TRAINING_SPLIT_METADATA_MISSING`, 422).
> - `POST /train`은 등록된 전체 모델(`lightgbm`, `xgboost`, `random_forest`)을 각각 독립적으로 실행하며, 한 모델의 실패가 다른 모델의 학습을 중단시키지 않고 부분 성공(`partially_succeeded`, 200)으로 격리 처리합니다.
> - `POST /train/{base_model}`은 지정된 단일 모델만 학습하며 실패 시 500 오류를 반환합니다.
> - 성공한 모델마다 `contracts/schemas/model-artifact.schema.json`을 준수하는 불변 Model Artifact v1.0 패키지(`manifest.json`, `model.joblib`, `feature_schema.json`, `label_schema.json`, `history_requirement.json`, `metrics.json`)를 원자적으로 발행합니다.
> - 프로세스 단위 학습 Lock을 적용하여 동시 중복 학습을 방지합니다 (`TRAINING_ALREADY_RUNNING`, 409).

**요청 본문:**

```json
{
  "feature_dataset_version": "feature-dataset-c3d4e5f678901234"
}
```

**전체 성공 응답 본문 (HTTP 200):**

```json
{
  "request_id": "req-9c8f2a1b",
  "run_id": "train-20260820051216-3ba9f9",
  "status": "succeeded",
  "feature_dataset_version": "feature-dataset-c3d4e5f678901234",
  "results": [
    {
      "base_model": "lightgbm",
      "status": "succeeded",
      "model_id": "lightgbm",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/lightgbm/v1"
    },
    {
      "base_model": "xgboost",
      "status": "succeeded",
      "model_id": "xgboost",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/xgboost/v1"
    },
    {
      "base_model": "random_forest",
      "status": "succeeded",
      "model_id": "random_forest",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/random_forest/v1"
    }
  ],
  "failed_models": []
}
```

**일부 모델 실패 응답 본문 (HTTP 200, `partially_succeeded`):**

```json
{
  "request_id": "req-9c8f2a1b",
  "run_id": "train-20260820051216-3ba9f9",
  "status": "partially_succeeded",
  "feature_dataset_version": "feature-dataset-c3d4e5f678901234",
  "results": [
    {
      "base_model": "xgboost",
      "status": "succeeded",
      "model_id": "xgboost",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/xgboost/v1"
    },
    {
      "base_model": "random_forest",
      "status": "succeeded",
      "model_id": "random_forest",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/random_forest/v1"
    }
  ],
  "failed_models": [
    {
      "base_model": "lightgbm",
      "code": "MODEL_TRAINING_FAILED",
      "error_id": "err-7a8b9c0d"
    }
  ]
}
```

---

### 4.5 `POST /internal/train` 및 `POST /internal/retrain` (Legacy 호환용)

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

### 4.6 공통 표준 오류 응답 (`ErrorEnvelope`)

모든 에러 응답(4xx, 5xx)은 일관된 `ErrorEnvelope` 포맷을 반환합니다:

```json
{
  "error": {
    "code": "DATASET_PATH_NOT_ALLOWED",
    "message": "source_uri는 허용된 데이터 루트 내 상대경로 파일이어야 하며 절대경로/상위경로(..)는 허용되지 않습니다.",
    "path": "/extraction",
    "request_id": "req-9c8f2a1b",
    "error_id": "err-7a8b9c0d",
    "details": []
  }
}
```

#### 도메인 오류 코드 체계

| HTTP 상태 코드 | 도메인 오류 코드 (`code`) | 원인 및 설명 |
|---|---|---|
| 400 / 422 | `REQUEST_VALIDATION_ERROR` | 식별자 형식 위반, 필드 누락 또는 형식 불일치 |
| 404 | `DATASET_NOT_FOUND` | 요청한 dataset_id 또는 source_uri 파일 부재 |
| 404 | `EXTRACTION_PLAN_NOT_READY` | `/feature` 실행 전 필수 Extraction Plan 파일 부재 |
| 404 | `ONTOLOGY_MAPPING_NOT_READY` | `/feature` 실행 전 필수 Ontology Mapping 파일 부재 |
| 404 | `FEATURE_DATASET_NOT_FOUND` | 요청한 Feature Dataset Bundle 부재 |
| 404 | `MODEL_NOT_REGISTERED` | 지원하지 않는 base model 알고리즘 |
| 404 | `FAILURE_DATA_NOT_READY` | 요청한 Failure 데이터셋 파일 부재 또는 비어 있음 |
| 405 | `METHOD_NOT_ALLOWED` | 허용되지 않은 HTTP 메서드 호출 |
| 409 | `FEATURE_DATASET_CONFLICT` | 동일 Feature Dataset 버전 디렉터리가 이미 존재하나 계약 내용이 불일치함 |
| 409 | `TRAINING_ALREADY_RUNNING` | 중복 학습 요청 (이미 학습 진행 중) |
| 409 | `MODEL_ARTIFACT_CONFLICT` | 동일한 Model Artifact 버전이 이미 존재하여 덮어쓰기 거부 |
| 422 | `DATASET_PATH_NOT_ALLOWED` | source_uri가 절대경로, 상위경로 탐색(..) 또는 허용 루트 밖 경로임 |
| 422 | `INVALID_ARTIFACT_PATH` | Plan/Mapping/Feature 저장 디렉터리가 루트 디렉터리를 벗어남 |
| 422 | `EXTRACTION_PLAN_INTEGRITY_ERROR` | Extraction Plan의 내용 해시와 요청된 버전 불일치 |
| 422 | `ONTOLOGY_MAPPING_INTEGRITY_ERROR` | Ontology Mapping의 내용 해시와 요청된 버전 불일치 |
| 422 | `EXTRACTION_PLAN_CONTRACT_INVALID` | Extraction Plan 파일 손상 또는 스키마 위반 |
| 422 | `ONTOLOGY_MAPPING_CONTRACT_INVALID` | Ontology Mapping 파일 손상 또는 스키마 위반 |
| 422 | `FEATURE_SCHEMA_MISMATCH` | Feature Schema 미존재, allowlist 컬럼 부재, 누수 컬럼 포함 등 |
| 422 | `LABEL_SCHEMA_MISMATCH` | Label Schema 미존재, 버전 불일치, horizon/positive_class/anchor 불일치 |
| 422 | `TRAINING_SPLIT_METADATA_MISSING` | 시간순 데이터 분할(asset_time_split)을 위한 메타데이터 누락 |
| 422 | `LABEL_CONTRACT_INVALID` | 라벨 컬럼/ID/timestamp 부재 또는 라벨 값이 `{0, 1}` 범위를 벗어남 |
| 422 | `LABEL_ANCHOR_NOT_FOUND` | 고장 데이터에서 anchor(failure_point)를 찾을 수 없거나 전체 결측치(NaT)임 |
| 422 | `INSUFFICIENT_POSITIVE_SAMPLES` | 고장 예측 구간 내 Positive 고장 샘플 0건 |
| 422 | `INSUFFICIENT_TRAINING_DATA` | 유효 데이터 행 수 0건 또는 단일 클래스 라벨 등 학습 데이터 부족 |
| 422 | `NPY_VALIDATION_ERROR` | NPY 행렬 shape, dtype, NaN/Inf 불일치 |
| 422 | `FEATURE_DATASET_INTEGRITY_ERROR` | 기존 Feature Dataset 번들 필수 파일 누락, 손상, shape/dtype 불일치 등 |
| 500 | `EXTRACTION_PLAN_PUBLISH_ERROR` | 추출 계획 또는 온톨로지 매핑 파일 저장 실패 |
| 500 | `NPY_PUBLISH_ERROR` | NPY 산출물 디렉터리 저장 실패 |
| 500 | `MODEL_TRAINING_FAILED` | 모델 학습 실행 실패 |
| 500 | `MODEL_ARTIFACT_PUBLISH_FAILED` | Model Artifact 불변 패키지 발행 실패 |
| 500 | `INTERNAL_SERVER_ERROR` | 처리 중 발생한 예기치 않은 서버 내부 오류 |

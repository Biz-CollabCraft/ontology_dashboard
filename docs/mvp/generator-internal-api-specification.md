# Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 제어 API**의 계약이다. [API 명세서](./api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: `generator` 파이프라인(추출/매핑/feature/학습 및 Model Artifact 발행, 활성 버전 포인터 관리) 구현 담당자

---

## 2. 책임 경계 (허용 / 금지 범위)

[런타임 소유권 통합 계약](./runtime-ownership-integration.md) 및 ADR-002 Invariant 22·23에 따라 다음 경계를 엄격히 준수한다:

### 허용 범위
- `GET /health` (데몬 상태 확인)
- `POST /internal/train` (기존 main 제어 API: 최초 학습 실행, 단일 프로세스 Lock 하에 실행)
- `POST /internal/retrain` (기존 main 제어 API: 새 버전 재학습 실행, 단일 프로세스 Lock 하에 실행)
- Target 제어 API: 후속 구조 개편 시 정의될 단계별 엔드포인트(`POST /extraction`, `POST /preprocessing`, `POST /feature`, `POST /train`, `POST /train/{base_model}`, `POST /models/...`)

> **Backend 연계 책임 경계**:
> - Generator의 책임 끝점은 Model Artifact 발행 및 canonical active-version pointer(`latest.json`)의 원자적 관리까지입니다.
> - Backend 런타임에서 `latest.json`을 읽어 진단 모델을 리로드(reload)하고 소비하는 연계 작업은 Generator 구현 완료 조건에 포함하지 않으며, 별도의 Backend 연계 작업으로 진행됩니다.

### 금지 범위
- `POST /internal/predict`, `POST /internal/predict/file`
- 사용자 요청 기반 runtime inference
- `data_preprocessed/predictions/*.json` 파일 생성
- Product Result Artifact / Evidence 생성
- `PredictionOutput` 등 Backend runtime 응답 형식 노출
- Frontend의 Generator 직접 호출

---

## 3. 엔드포인트 목록 및 Migration 매핑

### 3.1 Current API (현재 main 구현 상태)

현재 `main` 브랜치의 Generator 데몬에 실제로 구현되어 동작하는 엔드포인트는 다음 3개입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 프로세스 상태 확인 | Current (운영 중) |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어) | Current (운영 중) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어) | Current (운영 중) |

> **참고**: 기존 `/internal/train`, `/internal/retrain`의 향후 폐기 또는 compatibility shim 유지 여부는 후속 migration 시점에 결정됩니다.

### 3.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 단계별 책임 분리)이 완료된 후 도입될 목표 엔드포인트입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

| Method | Path | Target 의미 및 4대 파이프라인 단계 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Target (유지) |
| POST | `/extraction` | 프로토콜 투영 로그를 정제된 Observation/Failure Dataset으로 추출 (신규 1단계) | Target — 미병합 |
| POST | `/preprocessing` | Observation Dataset을 분석하여 Preprocessing Plan 및 Ontology Mapping 발행 (신규 2단계) | Target — 미병합 |
| POST | `/feature` | Observation/Failure + Plan/Mapping을 소비하여 Feature/Label/Series 및 Feature Bundle 발행 (신규 3단계) | Target — 미병합 |
| POST | `/train` | Feature Dataset Bundle을 소비하여 전체 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/train/{base_model}` | Feature Dataset Bundle을 소비하여 특정 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/models/{base_model}/activate/{model_version}` | 기존 발행된 불변 Model Artifact 패키지 수동 활성화 | Target — 미병합 |
| GET | `/models/{base_model}/active` | 현재 활성화된 Model Artifact 정보 조회 | Target — 미병합 |

### 3.3 기존 명칭 Migration 매핑표

별도 Generator API화 작업에서 설계된 `/extraction`은 데이터셋 분석, Extraction Plan 수립 및 Ontology Mapping을 담당합니다. Target 구조에서는 이 기능을 `/preprocessing`으로 이전하고, `/extraction`은 `gen_data` 프로토콜 투영 로그 가공에 사용합니다.

| 선행 API화 작업 대상 (Migration source) | Target (후속 목표 대상) | Migration 계획 및 비고 |
|---|---|---|
| 선행 API 설계 `POST /extraction` | `POST /preprocessing` | 엔드포인트 URL 변경 (데이터셋 분석 및 Plan/Mapping 기능을 /preprocessing으로 이전) |
| `ExtractionPlan` | `PreprocessingPlan` | Pydantic 스키마 변경 |
| `ExtractionPlanResponse` | `PreprocessingPlanResponse` | 응답 스키마 변경 |
| `extraction_plan_version` | `preprocessing_plan_version` | 식별자 및 메타데이터 키 변경 |
| `ExtractionService` | `PreprocessingService` | 서비스 클래스 변경 |
| `ExtractionRepository` | `PreprocessingRepository` | 저장소 클래스 변경 |
| `ExtractionPlanner` | `PreprocessingPlanner` | LLM 계획기 클래스 변경 |
| `ExtractionProfiler` | `PreprocessingProfiler` | 프로파일러 클래스 변경 |
| (신규 구현) | `POST /extraction` | 신규 프로토콜 투영 로그 추출 엔드포인트 |
| (신규 구현) | `ExtractionService` | 신규 Observation/Failure Dataset 발행 서비스 |

---

## 4. Current 요청/응답 및 런타임 동작 계약

### 4.1 `GET /health`

**성공 응답 본문:**

```json
{
  "status": "ok",
  "system": "generator"
}
```

### 4.2 `POST /internal/train`, `POST /internal/retrain`

**요청 본문:**

```json
{
  "data_dir": "data",
  "force_reanalyze": false
}
```

**성공 응답 본문 (현재 main의 `train_all()` 실제 반환 구조):**

```json
{
  "capabilities": {
    "EquipmentMonitoring": true,
    "SensorAnalytics": true,
    "MaintenanceHistory": false,
    "FailurePrediction": true,
    "ErrorTracking": false
  },
  "mappings": {
    "voltage_raw": {
      "source_field": "voltage_raw",
      "target_ontology": "Voltage",
      "source": "mapping_agent",
      "confidence": 0.8,
      "status": "auto_mapped"
    }
  },
  "registry": {
    "run_version": 3,
    "run_id": "run-v3-20260818070000",
    "trained_at": "2026-08-18T07:00:00+00:00",
    "models": {
      "lightgbm": {
        "model_id": "pdm-cnc-tool-wear-lightgbm",
        "model_version": "v3",
        "local_path": "models_store/lightgbm/model_v3.joblib",
        "artifact_uri": "models_store/artifacts/pdm-cnc-tool-wear-lightgbm/v3",
        "train_positive_rate": 0.0507,
        "validation_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 },
        "test_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 }
      },
      "xgboost": {
        "model_id": "pdm-cnc-tool-wear-xgboost",
        "model_version": "v3",
        "local_path": "models_store/xgboost/model_v3.joblib",
        "artifact_uri": "models_store/artifacts/pdm-cnc-tool-wear-xgboost/v3",
        "train_positive_rate": 0.0507,
        "validation_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 },
        "test_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 }
      }
    },
    "failed_models": null,
    "published_artifacts": {
      "pdm-cnc-tool-wear-lightgbm": {
        "model_id": "pdm-cnc-tool-wear-lightgbm",
        "model_version": "v3",
        "artifact_uri": "models_store/artifacts/pdm-cnc-tool-wear-lightgbm/v3"
      }
    }
  }
}
```

### 4.3 Current 오류 응답 규격

Current API는 FastAPI 기본 `{"detail": "..."}` 형식의 에러 응답을 반환합니다 (Target `ErrorEnvelope`와 혼합하지 않음).

| HTTP 상태 | Current 의미 및 발생 조건 |
|---:|---|
| 400 | `data_dir`가 없거나, 디렉터리가 아니거나, 비어 있는 경우 |
| 409 | startup 자동 학습 또는 다른 학습 요청이 이미 실행 중인 경우 |
| 422 | 요청 JSON 본문 검증 실패 시 |
| 500 | 학습 파이프라인 내부 처리 실패 또는 전체 모델 학습 실패 시 |

### 4.4 Current Model Artifact 발행 계약

- 학습에 성공한 모델은 immutable한 Model Artifact 패키지(`model-artifact-v1.0`)로 발행됩니다.
- 동일한 `model_id`와 `model_version` 조합의 기존 아티팩트는 덮어쓰지 않습니다.
- 발행 위치는 `MODEL_ARTIFACT_URI` 환경변수 또는 주입된 artifact 경로를 사용합니다.
- `registry.json`은 모델 레지스트리의 보조 실행 인덱스 역할을 수행합니다.
- Backend 진단 런타임이 소비하는 정본은 Manifest와 Role 파일을 온전히 포함한 Model Artifact입니다.
- 일부 모델만 학습에 실패한 경우 성공한 모델 Artifact는 보존 및 유지되며, 실패한 모델은 `failed_models`에 별도로 기록됩니다.

### 4.5 Current Startup · Shutdown · 동시성 계약

- **Startup 아티팩트 검사**: Generator startup은 `has_any_published_model_artifact()`를 사용하여 대상 디렉터리에 유효하게 발행된 Model Artifact가 존재하는지 확인합니다.
- **Initial Training 백그라운드 예약**: 유효한 Model Artifact가 존재하지 않을 경우 initial training을 백그라운드 태스크로 예약하며, ASGI startup 프로세스를 차단(block)하지 않습니다.
- **Startup 자동 학습 생략**: 유효한 Model Artifact가 이미 존재하면 startup 시 자동 학습을 안전하게 생략합니다.
- **Shutdown 대기**: 프로세스 shutdown 시 현재 실행 중인 initial training worker가 정상 완료될 때까지 대기합니다.
- **프로세스 전역 Training Lock**: startup 학습과 `POST /internal/train` 및 `POST /internal/retrain`은 동일한 process-wide training lock(`_training_lock`)을 공유합니다.
- **동시성 충돌 방지**: 이미 학습이 진행 중일 때 수신된 동시 학습 요청은 HTTP 409 (`Conflict`)로 거부됩니다.

---

## 5. Target Contract 예시 (후속 목표 설계)

> **주의**: 본 절의 계약 내용은 후속 구현 시 적용될 **목표 계약 예시(Target Contract)**이며, 현재 `main`에 구현된 코드가 아닙니다.

### 5.1 `POST /preprocessing` (Target Contract 예시 — 기존 Extraction 기능 이전)

```json
// 요청 예시 (Target)
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "source_uri": "ai4i/input.csv",
  "force_reanalyze": false,
  "duplicate_policy": "error",
  "aggregation": null
}

// 응답 예시 (Target)
{
  "request_id": "req-9c8f2a1b",
  "run_id": "preprocessing-3d4e5f6a",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "preprocessing_plan_version": "preprocessing-plan-a1b2c3d4e5f67890",
  "result": {
    "extraction_type": "tabular_column_as_attribute",
    "selected_columns": ["Air temperature [K]", "Process temperature [K]", "Rotational speed [rpm]", "Torque [Nm]", "Tool wear [min]"],
    "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
    "mapping_uri": "models_store/cache/mappings/ai4i/canonical-ai4i-physics-v3.1/ontology-mapping-b2c3d4e5f6789012.json"
  }
}
```

### 5.2 `POST /feature` (Target Contract 예시)

```json
// 요청 예시 (Target)
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "failure_dataset_id": "ai4i_failures",
  "failure_dataset_version": "canonical-ai4i-failures-v1",
  "preprocessing_plan_version": "preprocessing-plan-a1b2c3d4e5f67890",
  "mapping_version": "ontology-mapping-b2c3d4e5f6789012",
  "feature_schema_version": "ai4i-feature-v1",
  "label_schema_version": "ai4i-label-v1",
  "prediction_horizon_hours": 24,
  "rebuild_npy": true
}

// 응답 예시 (Target)
{
  "request_id": "req-9c8f2a1b",
  "run_id": "feature-5e6f7a8b",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "failure_dataset_id": "ai4i_failures",
  "failure_dataset_version": "canonical-ai4i-failures-v1",
  "preprocessing_plan_version": "preprocessing-plan-a1b2c3d4e5f67890",
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

### 5.3 `POST /train` 및 `POST /train/{base_model}` (Target Contract 예시)

```json
// 요청 예시 (Target)
{
  "feature_dataset_version": "feature-dataset-c3d4e5f678901234",
  "activation_policy": "latest"
}

// 전체 성공 응답 예시 (Target)
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
      "artifact_uri": "models_store/artifacts/lightgbm/v1",
      "activation_status": "activated",
      "active_model_version": "v1"
    },
    {
      "base_model": "xgboost",
      "status": "succeeded",
      "model_id": "xgboost",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/xgboost/v1",
      "activation_status": "activated",
      "active_model_version": "v1"
    },
    {
      "base_model": "random_forest",
      "status": "succeeded",
      "model_id": "random_forest",
      "model_version": "v1",
      "artifact_uri": "models_store/artifacts/random_forest/v1",
      "activation_status": "activated",
      "active_model_version": "v1"
    }
  ],
  "failed_models": []
}
```

---

## 6. 공통 표준 오류 응답 (`ErrorEnvelope` — Target 규격)

```json
{
  "error": {
    "code": "DATASET_PATH_NOT_ALLOWED",
    "message": "source_uri는 허용된 데이터 루트 내 상대경로 파일이어야 하며 절대경로/상위경로(..)는 허용되지 않습니다.",
    "path": "/preprocessing",
    "request_id": "req-9c8f2a1b",
    "error_id": "err-7a8b9c0d",
    "details": []
  }
}
```

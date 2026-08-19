# Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 제어 API**의 계약이다. [API 명세서](./api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: `generator` 파이프라인(추출/매핑/feature/학습 및 Model Artifact 발행) 구현 담당자

## 2. 책임 경계 (허용 / 금지 범위)

[런타임 소유권 통합 계약](./runtime-ownership-integration.md) 및 ADR-002 Invariant 22·23에 따라 다음 경계를 엄격히 준수한다:

### 허용 범위
- `GET /health` (데몬 상태 확인)
- `POST /internal/train` (최초 학습 실행)
- `POST /internal/retrain` (새 버전 재학습 실행)
- 학습 job 상태 또는 Model Artifact publish 상태 조회

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
| POST | `/extraction` | 데이터셋 분석 및 Extraction Plan/Mapping 수립·검증·원자적 영속화 (1단계) | 완료 |
| POST | `/feature` | Extraction Plan 소비, Feature·Label 생성 및 NPY/메타데이터 원자적 영속화 (2단계) | 완료 |
| POST | `/internal/train` | 파이프라인 최초 학습 실행 (단일 프로세스 Lock 하에 실행) | 후속 단계 |
| POST | `/internal/retrain` | 재학습 실행, 기존 모델을 덮어쓰지 않고 새 버전으로 저장 (Lock 하에 실행) | 후속 단계 |

## 4. 요청/응답 계약

### 4.1 `GET /health`

```json
{
  "status": "ok",
  "system": "generator"
}
```

### 4.2 `POST /extraction`

> **단계 범위 명시**:
> - `/extraction`은 Extraction Plan 및 Mapping 수립·검증 전용 엔드포인트입니다.
> - Feature·Label·NPY 생성(`/feature`) 및 모델 학습·Artifact 발행(`/train`)은 후속 단계이며, `/extraction`이 후속 단계를 자동 실행하지 않습니다.
> - Long-format 데이터셋에서 필수 역할(`id_column`, `attribute_column`, `value_column`)을 결정할 수 없는 경우 위치 기반 추측을 금지하고 `EXTRACTION_ROLE_COLUMNS_MISSING` 오류로 즉시 실패합니다.

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "source_uri": "data_preprocessed/ai4i/input.csv",
  "force_reanalyze": false,
  "duplicate_policy": "error",
  "aggregation": null,
  "idempotency_key": "extract-20260819-001"
}
```

**성공 응답 본문:**

```json
{
  "request_id": "req-...",
  "run_id": "extraction-...",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-ai4i-canonical-ai4i-physics-v3.1",
  "result": {
    "extraction_type": "tabular_row_as_attribute",
    "id_column": "asset_id",
    "time_column": "timestamp",
    "attribute_column": "attribute",
    "value_column": "value",
    "duplicate_policy": "error",
    "aggregation": null,
    "mapping_uri": "models_store/cache/extraction_plans/ai4i-canonical-ai4i-physics-v3.1.json"
  }
}
```

**공통 오류 응답 (ErrorEnvelope):**

```json
{
  "error": {
    "code": "REQUEST_VALIDATION_ERROR",
    "message": "요청 형식이 올바르지 않습니다.",
    "path": "/extraction",
    "request_id": "req-...",
    "error_id": "err-...",
    "details": []
  }
}
```

### 4.3 `POST /feature`

> **단계 범위 명시**:
> - `/feature`는 이미 발행된 `ExtractionPlan`을 조회·검증하여 시계열 피처 및 라벨을 생성하고 NPY 및 메타데이터를 원자적으로 발행합니다.
> - Plan이 존재하지 않거나 버전이 불일치할 경우 `/extraction`을 자동 실행하지 않고 `EXTRACTION_PLAN_NOT_READY` (404) 또는 `EXTRACTION_PLAN_VERSION_MISMATCH` (422)로 실패합니다.
> - 모델 학습 및 Model Artifact 발행은 후속 `/train` 단계이며, `/feature`가 모델 학습을 자동 실행하지 않습니다.

**요청 본문:**

```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-ai4i-canonical-ai4i-physics-v3.1",
  "feature_schema_version": "pdm-feature-v2",
  "label_schema_version": "pdm-label-v3",
  "prediction_horizon_hours": 24,
  "rebuild_npy": true,
  "force": false,
  "idempotency_key": "feature-20260819-001"
}
```

**성공 응답 본문:**

```json
{
  "request_id": "req-...",
  "run_id": "feature-...",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "extraction_plan_version": "extraction-plan-ai4i-canonical-ai4i-physics-v3.1",
  "feature_schema_version": "pdm-feature-v2",
  "label_schema_version": "pdm-label-v3",
  "outputs": {
    "feature_dataset_version": "feature-dataset-ai4i-canonical-ai4i-physics-v3.1",
    "row_count": 10000,
    "feature_count": 42,
    "features_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-ai4i-canonical-ai4i-physics-v3.1/features.npy",
    "labels_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-ai4i-canonical-ai4i-physics-v3.1/labels.npy",
    "metadata_uri": "models_store/cache/features/ai4i-canonical-ai4i-physics-v3.1-feature-dataset-ai4i-canonical-ai4i-physics-v3.1/feature_metadata.json"
  }
}
```

### 4.4 `POST /internal/train`, `POST /internal/retrain`

요청:

```json
{
  "data_dir": "data",
  "force_reanalyze": false
}
```

응답:

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
      },
      "random_forest": {
        "model_id": "pdm-cnc-tool-wear-random_forest",
        "model_version": "v3",
        "local_path": "models_store/random_forest/model_v3.joblib",
        "artifact_uri": "models_store/artifacts/pdm-cnc-tool-wear-random_forest/v3",
        "train_positive_rate": 0.0507,
        "validation_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 },
        "test_metrics": { "average_precision": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0 }
      }
    },
    "failed_models": null,
    "published_artifacts": {
      "lightgbm": "models_store/artifacts/pdm-cnc-tool-wear-lightgbm/v3",
      "xgboost": "models_store/artifacts/pdm-cnc-tool-wear-xgboost/v3",
      "random_forest": "models_store/artifacts/pdm-cnc-tool-wear-random_forest/v3"
    }
  }
}
```

- `models[name]`은 모델별 식별자(`model_id`, `model_version`) 및 공식 발행 위치인 **`artifact_uri`**(immutable `model-artifact-v1.0`)를 포함한다. `local_path`는 Generator 내부 캐시 경로일 뿐 외부 소비용 공식 계약이 아니다.
- `failed_models`는 일부 모델 학습이 실패했을 때 실패한 모델명과 에러 메시지가 채워지며, 성공한 모델의 `artifact_uri`는 `published_artifacts`에 정상 등록된다.

## 5. 오류 Envelope 및 HTTP 상태 코드

`generator`는 내부 전용 API이므로 FastAPI 기본 에러 형식(`{"detail": "..."}`)을 사용한다.

| HTTP Status | 조건 및 세부 내용 |
|---:|---|
| **400** | 입력 `data_dir`가 존재하지 않거나, 디렉터리가 아니거나(파일), 비어 있는 경우 |
| **409** | startup 자동 학습 또는 다른 train/retrain 요청이 이미 진행 중인 경우 (`모델 학습이 이미 진행 중입니다.`) |
| **422** | 요청 JSON 스키마 검증 실패 (FastAPI 기본 동작) |
| **500** | 모든 모델 학습 실패 또는 파이프라인 내부 예외 (스택 트레이스는 은폐하고 `모델 학습에 실패했습니다.` 반환) |

## 6. 모델 버전 관리 및 아티팩트 발행 계약

- 학습 성공 모델은 `model_id`/`model_version` 단위의 immutable `model-artifact-v1.0` 패키지로 `systems/generator/model/model_registry.py:publish_model_artifact()`를 통해 원자적으로 발행된다.
- 발행 위치는 `MODEL_ARTIFACT_URI` 환경변수 또는 주입된 `artifact_uri`로 결정된다.
- 동일 `model_id`/`model_version` 조합은 덮어쓰지 않는다 (재발행 시 `FileExistsError`).
- Run Registry(`models_store/registry.json`)는 학습 실행 이력을 기록하는 보조 인덱스이며, Backend가 소비하는 canonical 계약 단위는 `registry.json`이 아니라 Manifest와 5개 Role 파일이 포함된 [Model Artifact](./model-artifact-publish-contract.md) 디렉터리다.
- 일부 모델이 실패해도 성공한 모델의 Artifact만 발행되며, registry의 `run_version`은 해당 run에서 성공한 모델에 대해서만 유효하게 취급된다.

## 7. Startup, Shutdown 및 동시성 제어 정책

- **Non-blocking Startup**: Generator 데몬 기동 시 유효하게 발행된 Model Artifact가 없으면(`has_any_published_model_artifact() == False`), 초기 학습을 ASGI startup(`lifespan` yield)을 블로킹하지 않고 백그라운드 태스크(`asyncio.create_task`)로 예약한다. 따라서 `/health` 응답과 서버 기동은 즉시 완료된다.
- **Graceful Shutdown Worker 수명 보장**: 데몬 종료 시 실행 중인 초기 학습 worker thread를 가짜로 `cancel()`하지 않고 실제 worker 작업이 안전하게 끝날 때까지 `await task`로 대기한다. 이를 통해 worker와 `_training_lock`의 수명을 완벽히 일치시키고, shutdown 이후에 파일(Artifact/Registry)이 불완전하게 쓰이는 문제를 방지한다.
- **동시성 Lock**: 프로세스 내 전역 `asyncio.Lock`을 두어 startup 백그라운드 학습과 수동 `/internal/train`, `/internal/retrain` 호출이 상호 배타적으로 실행되며, 중복 요청은 즉시 `409 Conflict`로 거부된다.
- **`has_any_published_model_artifact()` 판정 기준**: `has_any_published_model_artifact()`는 현재 실행 가능한 개발 초안 Manifest의 필수 필드를 검증하고, 필수 Role 5개(`model`, `feature_schema`, `label_schema`, `history_requirement`, `metrics`), Role·Path 중복 금지, Artifact 루트 내부 상대경로, 선언 파일 존재 및 `artifact_files[*].sha256` 일치를 모두 확인한다. 이 검증을 통과한 Artifact가 하나 이상 있을 때만 시작 시 자동 학습을 생략한다. 확정된 공식 17필드 구조로의 전체 전환은 Generator publisher, Backend loader, JSON Schema 및 round-trip 테스트를 함께 변경하는 후속 통합 작업에서 수행한다.


## 8. 결정 반영과 후속 확인


### Week 2 결정 완료
- `generator` 내부 API는 프론트엔드에 직접 노출하지 않는다.
- `generator` 데몬은 runtime predict를 노출하지 않으며(ADR-002 Invariant 22·23), 런타임 추론은 Backend Diagnosis가 전담한다.
- 모델은 덮어쓰기가 아닌 immutable Model Artifact 버전 관리 방식으로 보존한다.
- startup 학습은 non-blocking 백그라운드로 실행하고, shutdown 시에는 진행 중인 worker가 끝날 때까지 graceful 대기하며, 프로세스 내 동시 학습은 409로 방어한다.
- 모델 존재 판정은 raw 파일이 아닌 유효하게 발행된 Model Artifact 존재 여부를 기준으로 한다.

### 후속 확인 (별도 이슈 이관)
- 다중 프로세스/Worker 배포 환경을 위한 분산 Lock 또는 Job Queue 도입 검토 (단일 프로세스 `asyncio.Lock` 한계 보완)
- 학습 상태 조회를 위한 `GET /internal/training/status` 엔드포인트 신설 여부
- 장시간 실행되는 학습의 강제 취소가 필요한 경우를 위한 별도 Process/Job Runner 분리

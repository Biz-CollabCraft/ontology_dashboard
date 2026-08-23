# Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 제어 API**의 계약이다. [API 명세서](./api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- 정본 앱 진입점: `systems.generator.app.main:app` (Application Factory `create_app()` 제공)
- 호환성 진입점: `systems.generator.generator_main:app` (Compatibility Shim)
- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: `generator` 파이프라인(전처리 계획 수립/검증/발행 및 Model Artifact 발행, 활성 버전 포인터 관리) 담당

---

## 2. 책임 경계 (허용 / 금지 범위)

[런타임 소유권 통합 계약](./runtime-ownership-integration.md) 및 ADR-002 Invariant 22·23에 따라 다음 경계를 엄격히 준수한다:

### 허용 범위
- `GET /health` (데몬 상태 확인)
- `POST /preprocessing` (Observation Dataset 분석 및 Preprocessing Plan 수립·발행, 동기 endpoint 실행)
- `POST /internal/train` (기존 main 제어 API 호환성: 최초 학습 실행, 단일 프로세스 Lock 하에 실행)
- `POST /internal/retrain` (기존 main 제어 API 호환성: 새 버전 재학습 실행, 단일 프로세스 Lock 하에 실행)
- Target 제어 API: 후속 구조 개편 시 정의될 단계별 엔드포인트(`POST /extraction`, `POST /feature`, `POST /train`, `POST /train/{base_model}`, `POST /models/...`)

> **Preprocessing 도메인 책임 경계**:
> - Preprocessing은 Observation Dataset의 구조 분석, 컬럼 역할 판정, Preprocessing Plan 생성, 전체 데이터셋 변환 검증 및 불변 Plan 발행만 담당합니다.
> - **Ontology Mapping 생성·발행 책임은 Preprocessing에 포함되지 않으며**, 후속 Feature 파이프라인에 필요한 Ontology Mapping은 별도의 Mapping Provider에서 공급받습니다.
>
> **Backend 연계 책임 경계**:
> - Generator의 책임 끝점은 Preprocessing Plan 및 Model Artifact 발행과 canonical active-version pointer(`latest.json`)의 원자적 관리까지입니다.
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

### 3.1 Current API (현재 구현 상태)

현재 Generator 정본 애플리케이션(`systems/generator/app/main.py`)에 실제로 구현되어 동작하는 엔드포인트입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 프로세스 상태 확인 | Current (구현 완료) |
| POST | `/preprocessing` | Observation Dataset 분석, 역할 판정 및 불변 Preprocessing Plan 수립·발행 (동기 방식) | Current (구현 및 정본 Generator App 이관 완료) |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어, 호환성 유지) | Current (호환성 유지) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어, 호환성 유지) | Current (호환성 유지) |

### 3.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 단계별 책임 분리)이 완료된 후 도입될 목표 엔드포인트입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

| Method | Path | Target 의미 및 4대 파이프라인 단계 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Current (유지) |
| POST | `/extraction` | protocol provenance → Observation Dataset / Authorized Truth Source → Failure Dataset (신규 1단계) | Target — 미병합 |
| POST | `/preprocessing` | Observation Dataset을 분석하여 불변 Preprocessing Plan 수립 및 발행 (신규 2단계) | Current (구현 및 정본 Generator App 이관 완료) |
| POST | `/feature` | Observation + Failure + Plan + Mapping을 소비하여 Feature/Label 및 Feature Bundle 발행 (신규 3단계) | Target — 미병합 |
| POST | `/train` | Feature Dataset Bundle을 소비하여 전체 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/train/{base_model}` | Feature Dataset Bundle을 소비하여 특정 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/models/{base_model}/activate/{model_version}` | 기존 발행된 불변 Model Artifact 패키지 수동 활성화 | Target — 미병합 |
| GET | `/models/{base_model}/active` | 현재 활성화된 Model Artifact 정보 조회 | Target — 미병합 |

---

## 4. Preprocessing Plan 불변 식별 및 저장 구조 계약

### 4.1 Plan ID와 Plan Version 분리

- **`preprocessing_plan_id`**: 발행 단위 고유 식별자 (`pp-{UUID4}`, 예: `pp-7c106819-cc59-46da-90dd-22c37c441ac9`).
- **`preprocessing_plan_version`**: Plan 내용 지문 기반 16자리 SHA-256 해시 버전 (`preprocessing-plan-{hash}`, 예: `preprocessing-plan-38f74cc175d5ad12`).

### 4.2 저장 디렉터리 및 latest.json 포인터

```text
models_store/cache/preprocessing_plans/
└─ {dataset_id}/
   └─ {dataset_version}/
      ├─ pp-{uuid}.json    # 불변 Plan 파일 (덮어쓰기 금지)
      └─ latest.json       # 현재 유효한 Plan을 가리키는 원자적 포인터 파일
```

- **Plan 파일 구조**:
  - `preprocessing_plan_id`, `preprocessing_plan_version`, `dataset_id`, `dataset_version`, `structure_type`, `selected_columns`, `id_column`, `time_column`, `duplicate_policy`, `aggregation` 등 필수 메타데이터 포함.
- **`latest.json` 구조**:
  - `dataset_id`, `dataset_version`, `preprocessing_plan_id`, `preprocessing_plan_version`, `path`, `sha256`, `updated_at` 포함.
- **기존 캐시 정책**:
  - 기존 flat 캐시 파일(`{dataset_id}-{dataset_version}.json`)은 자동으로 최신 정본으로 승격하지 않으며 로그에 legacy 캐시 감지를 기록하고 새 구조로 신규 발행합니다.

---

## 5. Current 요청/응답 계약

### 5.1 `GET /health`

**성공 응답 본문:**
```json
{
  "status": "ok",
  "system": "generator"
}
```

### 5.2 `POST /preprocessing`

**요청 본문:**
```json
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-v3.1",
  "source_uri": "ai4i/canonical-v3.1.csv",
  "force_reanalyze": false,
  "duplicate_policy": "error",
  "aggregation": null,
  "idempotency_key": null
}
```

**성공 응답 본문:**
```json
{
  "request_id": "req-9c8f2a1b",
  "run_id": "preprocessing-3d4e5f6a",
  "status": "succeeded",
  "dataset_id": "ai4i",
  "dataset_version": "canonical-v3.1",
  "preprocessing_plan_id": "pp-7c106819-cc59-46da-90dd-22c37c441ac9",
  "preprocessing_plan_version": "preprocessing-plan-38f74cc175d5ad12",
  "result": {
    "structure_type": "tabular_column_as_attribute",
    "id_column": "UDI",
    "time_column": null,
    "attribute_column": null,
    "value_column": null,
    "duplicate_policy": "error",
    "aggregation": null,
    "preprocessing_plan_uri": "models_store/cache/preprocessing_plans/ai4i/canonical-v3.1/pp-7c106819-cc59-46da-90dd-22c37c441ac9.json",
    "preprocessing_plan_sha256": "4a7f...e3b8"
  }
}
```

### 5.3 `POST /internal/train`, `POST /internal/retrain` (호환성)

**요청 본문:**
```json
{
  "data_dir": "data",
  "force_reanalyze": false
}
```

**성공 응답 본문:**
```json
{
  "capabilities": {
    "EquipmentMonitoring": true,
    "SensorAnalytics": true,
    "MaintenanceHistory": false,
    "FailurePrediction": true,
    "ErrorTracking": false
  },
  "mappings": {},
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

### 5.4 Current Model Artifact 발행 계약

- 학습에 성공한 모델은 immutable한 Model Artifact 패키지(`model-artifact-v1.0`)로 발행됩니다.
- 동일한 `model_id`와 `model_version` 조합의 기존 아티팩트는 덮어쓰지 않습니다.
- 발행 위치는 `MODEL_ARTIFACT_URI` 환경변수 또는 주입된 artifact 경로를 사용합니다.
- Backend 진단 런타임이 소비하는 정본은 Manifest와 Role 파일을 온전히 포함한 Model Artifact입니다.

### 5.5 Current Startup · Shutdown · 동시성 계약

- **Startup 아티팩트 검사**: Generator startup은 `has_any_published_model_artifact()`를 사용하여 대상 디렉터리에 유효하게 발행된 Model Artifact가 존재하는지 확인합니다.
- **Initial Training 백그라운드 예약**: 유효한 Model Artifact가 존재하지 않을 경우 initial training을 백그라운드 태스크로 예약하며, ASGI startup 프로세스를 차단하지 않습니다.
- **Startup 자동 학습 생략**: 유효한 Model Artifact가 이미 존재하면 startup 시 자동 학습을 안전하게 생략합니다.
- **Shutdown 대기**: 프로세스 shutdown 시 현재 실행 중인 initial training worker가 정상 완료될 때까지 대기합니다.
- **프로세스 전역 Training Lock**: startup 학습과 `POST /internal/train` 및 `POST /internal/retrain`은 동일한 process-wide training lock(`_training_lock`)을 공유합니다.

---

## 6. Target Contract 예시 (후속 목표 설계)

> **주의**: 본 절의 계약 내용은 후속 구현 시 적용될 **목표 계약 예시(Target Contract)**입니다.

### 6.1 `POST /feature` (Target Contract 예시)
Feature 단계는 Preprocessing Plan과 별도의 Ontology Mapping Provider에서 공급된 Mapping을 소비하여 불변 Feature Dataset Bundle(5개 필수 파일)을 발행합니다.

### 6.2 `POST /train` 및 `POST /train/{base_model}` (Target Contract 예시)
Feature Dataset Bundle을 소비하여 Model Artifact를 발행하고 활성화 포인터를 관리합니다.

# Generator 내부 API 명세서

## 1. 기준과 상태

이 문서는 `systems/generator`가 노출하는 **내부 전용 제어 API**의 계약이다. [API 명세서](./api-specification.md)가 `backend`의 제품 API(사용자·프론트엔드가 소비)를 다루는 것과 달리, 이 문서는 `backend`(또는 운영자)가 `generator` 데몬을 제어하기 위한 API를 다룬다. **외부(프론트엔드)에는 노출되지 않는다.**

- 정본 앱 진입점: `systems.generator.app.main:app` (Application Factory `create_app()` 제공)
- 호환성 진입점: `systems.generator.generator_main:app` (Compatibility Shim)
- Base path: (별도 접두사 없음, `generator` 프로세스가 단독으로 사용)
- 책임: Generator는 단계별 Versioned Observation/Failure Dataset, Preprocessing Plan, Feature Dataset Bundle 및 Model Artifact를 발행한다. Generator의 최종 책임 끝점은 Model Artifact와 활성 버전 포인터(`latest.json`) 발행이다.

Backend Diagnosis는 발행된 Model Artifact와 Observation history를 소비하여 runtime inference, Product Result Artifact 및 Evidence를 생성한다.

Extraction이 사용하는 protocol field Mapping은 canonical Observation 변환 계약이다. Feature 실행 계약은 Feature Schema/Recipe이며 Ontology Mapping이 아니다.

---

## 2. 책임 경계 (허용 / 금지 범위)

[런타임 소유권 통합 계약](./runtime-ownership-integration.md) 및 ADR-002 Invariant 22·23에 따라 다음 경계를 엄격히 준수한다:

### 허용 범위
- `GET /health` (데몬 상태 확인)
- `POST /preprocessing` (Observation Dataset 분석 및 Preprocessing Plan 수립·발행, 동기 endpoint 실행)
- `POST /internal/train` (기존 main 제어 API 호환성: 최초 학습 실행, 단일 프로세스 Lock 하에 실행)
- `POST /internal/retrain` (기존 main 제어 API 호환성: 새 버전 재학습 실행, 단일 프로세스 Lock 하에 실행)
- Target 제어 API: 후속 구조 개편 시 정의될 단계별 엔드포인트(`POST /extraction`, `POST /feature`, `POST /train`, `POST /train/{base_model}`, `POST /models/...`)

> **Preprocessing 도메인 책임 경계**
>
> - Preprocessing은 Observation Dataset의 구조 분석, 컬럼 역할 판정, 전체 변환 가능성 검증 및 불변 Preprocessing Plan 발행만 담당한다.
> - Preprocessing은 Ontology Mapping을 생성하거나 소비하지 않는다.
> - 원본 protocol field를 canonical Observation field로 변환하는 Mapping은 선행 Extraction 단계가 적용한다.
> - Feature 단계는 Ontology Mapping을 조회하지 않으며, Feature Schema/Recipe에 명시된 source field와 계산 규칙을 사용한다.
>
> **Generator 전체 책임 및 Backend 연계 책임 경계**:
>
> - Generator는 단계별 Versioned Observation/Failure Dataset, Preprocessing Plan, Feature Dataset Bundle 및 Model Artifact를 발행한다.
> - Generator의 최종 실행 책임 끝점은 versioned Model Artifact 발행과 Model Artifact의 canonical active-version pointer 관리까지다.
> - Preprocessing Plan의 `latest.json`은 해당 Dataset version에서 현재 선택된 Preprocessing Plan을 가리키는 포인터이며, Model Artifact 활성 버전 포인터와 동일한 파일 또는 저장 경계를 의미하지 않는다.
> - Backend 런타임에서 Model Artifact store의 canonical active-version pointer를 읽어 진단 모델을 reload하고 소비하는 연계 작업은 Generator 구현 완료 조건에 포함하지 않으며, 별도의 Backend 연계 작업으로 진행한다.

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
| POST | `/preprocessing` | Observation Dataset 분석, 역할 판정 및 불변 Preprocessing Plan 수립·발행 (동기 방식) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/feature` | Observation/Failure Dataset, Preprocessing Plan, Feature/Label Schema를 소비하여 Feature Dataset Bundle 발행 (동기 방식, local file adapter) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어, 호환성 유지) | Current (호환성 유지) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어, 호환성 유지) | Current (호환성 유지) |

### 3.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 단계별 책임 분리)이 완료된 후 도입될 목표 엔드포인트입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

| Method | Path | Target 의미 및 4대 파이프라인 단계 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Current (유지) |
| POST | `/extraction` | gen_data protocol data에 지정·승인된 Mapping을 적용하여 Versioned Canonical Observation Dataset을 발행하고, 별도 Authorized Truth Source로 Failure Dataset을 발행 (관련 후속 작업: Issue #108) | Target — 미병합 |
| POST | `/preprocessing` | Observation Dataset을 분석하여 불변 Preprocessing Plan 수립 및 발행 (신규 2단계) | Current — 구현 완료 |
| POST | `/feature` | Observation Dataset, Failure Dataset, Preprocessing Plan, Feature Schema 및 Label Schema를 소비하여 Feature/Label Dataset Bundle 발행 (신규 3단계) | Current — 구현 완료 |
| POST | `/train` | Feature Dataset Bundle을 소비하여 전체 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/train/{base_model}` | Feature Dataset Bundle을 소비하여 특정 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target — 미병합 |
| POST | `/models/{base_model}/activate/{model_version}` | 기존 발행된 불변 Model Artifact 패키지 수동 활성화 | Target — 미병합 |
| GET | `/models/{base_model}/active` | 현재 활성화된 Model Artifact 정보 조회 | Target — 미병합 |

---

## 4. Preprocessing Plan 불변 식별 및 저장 구조 계약

### 4.1 Plan ID와 Plan Version 분리

- **`preprocessing_plan_id`**: 발행 단위 고유 식별자 (`pp-{UUID4}`, 예: `pp-7c106819-cc59-46da-90dd-22c37c441ac9`).
- **`preprocessing_plan_version`**: Dataset 식별자, `source_dataset_sha256`, `source_schema_fingerprint`, `decision_source`, `fallback_reason`, `planner_version`, 구조 유형, 선택 컬럼 및 중복 정책을 포함하는 canonical 지문 기반 16자리 SHA-256 해시 버전 (`preprocessing-plan-{hash}`, 예: `preprocessing-plan-38f74cc175d5ad12`).

### 4.2 Dataset Provenance, Schema Fingerprint 및 Planner 판단 이력

- **입력 결합**: Preprocessing Plan은 Dataset ID/version뿐 아니라 실제 입력 Dataset의 SHA-256 체크섬(`source_dataset_sha256`) 및 논리 상대경로(`source_dataset_uri`)와 결합되어 발행됩니다.
- **Source Schema Fingerprint**: 원본 Dataset의 컬럼 index, 컬럼명, canonical dtype을 기반으로 한 64자리 SHA-256 지문(`source_schema_fingerprint`)을 기록하여 값 변경과 구조 변경을 명확히 구분합니다.
- **Planner 판단 이력**: Plan 생성 방식(`decision_source`: `llm` 또는 `rule_fallback`), fallback 발생 시 정제된 사유(`fallback_reason`), Planner 계약 버전(`planner_version`: `preprocessing-planner-v1`)을 기록합니다.
- **버전 결정성**: 같은 Dataset과 역할 설정이라도 파일 내용(sha256), 컬럼 구조(schema fingerprint), Planner 생성 경로(`decision_source`) 또는 Planner 버전이 다르면 다른 `preprocessing_plan_version`이 생성됩니다.

### 4.3 Structure Type 허용 목록 및 Logical URI Fail-Closed 계약

- **공식 지원 `structure_type`**: `tabular_column_as_attribute`, `tabular_row_as_attribute` 2종류만 공식 지원합니다. `wide_pivot` 및 미지원 형식은 임의 fallback 없이 `422 PREPROCESSING_PLAN_VALIDATION_ERROR`로 거부됩니다.
- **Logical URI Fail-Closed**: `source_dataset_uri`, `preprocessing_plan_uri`는 허용된 저장소 루트(`PATHS.data_dir`, `PATHS.models_store`, workspace) 기반의 논리 상대경로만 저장됩니다. 허용 루트 밖의 경로는 Fail-Closed로 거부(`422 DATASET_CONTRACT_ERROR`)되며 오류 응답에 전체 절대경로가 노출되지 않습니다.

### 4.4 Plan 검증 및 재사용 규칙

- **입력 및 구조 무결성 검증**: `force_reanalyze=False` 시 현재 Dataset의 SHA-256 및 Schema Fingerprint와 Plan의 메타데이터를 비교하여 불일치 시 `409 PREPROCESSING_PLAN_CONFLICT`를 반환합니다 (detail에 `content_changed`, `schema_changed`, 이전/현재 해시 상세 제공).
- **중복 정책 검증**: 요청된 `duplicate_policy` 및 `aggregation`이 기존 Plan과 다르면 `409 PREPROCESSING_PLAN_CONFLICT`를 반환합니다.
- **Fail-Fast 컬럼 검증**: Plan에 선언된 `selected_columns` 또는 역할 컬럼(`id_column`, `time_column` 등) 중 하나라도 Dataset에 없으면 임의 fallback 없이 즉시 `422 PREPROCESSING_PLAN_VALIDATION_ERROR`를 발생시킵니다.
- **Wide-format Timestamp 정규화**: Wide-format에서도 `time_column`이 선언된 경우 `datetime64[ns]` 정규화 및 `[id_column, time_column]` 안정 정렬(stable sort)을 수행합니다.
- **발행 안정성**: 전체 Dataset 변환이 성공적으로 검증된 경우에만 Plan 파일과 `latest.json` 포인터가 발행됩니다.

### 4.5 저장 디렉터리 및 원자적 발행 순서

```text
models_store/cache/preprocessing_plans/
└─ {dataset_id}/
   └─ {dataset_version}/
      ├─ pp-{uuid}.json    # 불변 Plan 파일 (덮어쓰기 금지)
      └─ latest.json       # 현재 유효한 Plan을 가리키는 원자적 포인터 파일
```

- **Plan 본문 원자적 발행**: Plan 본문은 고유 ID의 불변 파일(`pp-{uuid}.json`)로 원자적으로 발행한다.
- **포인터 원자적 갱신**: Plan 파일 작성과 checksum 검증이 완료된 뒤 `latest.json` 포인터를 별도의 원자적 replace로 갱신한다.
- **포인터 무결성**: `latest.json`은 검증되지 않았거나 불완전한 Plan을 가리키지 않는다. Plan 파일 발행 후 포인터 갱신 전에 프로세스가 중단되면 latest에서 참조되지 않는 비활성 Plan 파일이 남을 수 있으나, 비활성 Plan은 활성 계약을 오염시키지 않으며 후속 점검 또는 정리 작업에서 식별할 수 있다.
- **기존 캐시 정책**: 기존 flat 캐시 파일(`{dataset_id}-{dataset_version}.json`)은 자동으로 최신 정본으로 승격하지 않으며 로그에 legacy 캐시 감지를 기록하고 새 구조로 신규 발행합니다.

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
  "aggregation": null
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

### 5.6 Feature Dataset Bundle 계약 (`POST /feature` — Current)

Observation Dataset, Failure Dataset(또는 내장 Failure indicator), Preprocessing Plan, Feature Schema 및 Label Schema를 소비하여 Feature 및 Horizon Label을 계산하고 불변 Feature Dataset Bundle(5개 필수 파일)을 원자적으로 발행합니다.

```json
// 요청 예시 (external_dataset 모드)
{
  "dataset_id": "ai4i",
  "dataset_version": "canonical-ai4i-physics-v3.1",
  "failure_source_mode": "external_dataset",
  "failure_dataset_id": "ai4i_failures",
  "failure_dataset_version": "canonical-ai4i-failures-v1",
  "preprocessing_plan_id": "pp-7c106819-cc59-46da-90dd-22c37c441ac9",
  "preprocessing_plan_version": "preprocessing-plan-a1b2c3d4e5f67890",
  "feature_schema_version": "ai4i-feature-v1",
  "label_schema_version": "ai4i-label-24h-v1",
  "prediction_horizon_hours": 24,
  "rebuild_npy": false
}
```

- **Failure Source 계약 (`failure_source_mode`)**:
  - `external_dataset`: `failure_dataset_id` 및 `failure_dataset_version`이 필수이며, 파일 부재 시 Observation 데이터셋으로 대체하지 않고 즉시 `404 FEATURE_INPUT_NOT_FOUND`로 실패합니다.
  - `embedded_observation`: Observation 내부 failure indicator 컬럼(`Machine failure` 등)을 사용하며, indicator 컬럼 부재 시 `422`로 실패합니다.
- **계산된 Feature 의미 보존**:
  - `lag`, `diff`, `rolling`, `ewm` 등 변환 연산 결과(`series`)에 대해 `missing_value_policy == "ffill"` 적용 시 원본 source 컬럼으로 되돌아가지 않고 계산된 series 자체를 설비 단위(`asset_id`)로 forward-fill합니다.
- **Failure 설비 Identity 및 제외 구간 Fail-Closed**:
  - 다중 설비 데이터셋에서 Failure 데이터셋의 asset ID 컬럼 누락, 결측치 또는 Observation에 존재하지 않는 asset ID 포함 시 `422 FEATURE_LABEL_ALIGNMENT_ERROR`를 반환합니다.
  - Label Schema가 선언한 `anchor` 및 `exclusion_end` 컬럼 누락, NaT 또는 `exclusion_end < anchor` 위반 시 `422`로 처리하며, `[anchor, exclusion_end]` 전체 구간을 학습 데이터에서 엄격히 제거합니다.
- **5개 필수 파일 구성**: `features.npy`, `labels.npy`, `feature_columns.json`, `row_metadata.json`, `feature_metadata.json`
- **저장 디렉터리**: `models_store/cache/features/{dataset_id}/{dataset_version}/{feature_dataset_version}/`
- **식별자 결정론**: `feature_dataset_version`은 입력 Dataset, `failure_source_mode`, Plan(ID/ver/sha), Schema(ver/sha)의 canonical fingerprint로 결정론적 산출.
- **Ontology Mapping 배제**: Feature 단계는 Ontology Mapping을 조회하지 않고 Feature Schema allowlist/recipe만 실행합니다.

---

## 6. Target Contract 예시 (후속 목표 설계)

> **주의**: 본 절의 계약 내용은 후속 구현 시 적용될 **목표 계약 예시(Target Contract)**입니다.

### 6.1 `POST /train` 및 `POST /train/{base_model}` (Target Contract 예시)
Feature Dataset Bundle을 소비하여 Model Artifact를 발행하고 활성화 포인터를 관리합니다.

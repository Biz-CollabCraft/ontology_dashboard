# Generator Domain (개요 및 목표 아키텍처)

`systems/generator`는 센서 데이터셋 분석, 전처리 계획(Preprocessing Plan) 수립, 불변 Plan 발행 및 머신러닝 모델 학습과 Model Artifact 발행을 전담하는 도메인 시스템입니다.

---

## 1. 아키텍처 구조

### 1.1 Current 구조 (현재 구현 상태)

Generator는 `systems/generator/app/main.py`를 정본 FastAPI 애플리케이션으로 사용하며, 기존 `generator_main.py`는 호환성 shim으로 동작합니다.

```text
systems/generator/
├─ app/                       # FastAPI Application 및 도메인 계층
│  ├─ main.py                 # 정본 FastAPI Application Factory (create_app)
│  ├─ preprocessing/          # [2단계 Current] Observation Dataset 분석 및 Preprocessing Plan 수립·발행
│  │  ├─ preprocessing_schema.py
│  │  ├─ preprocessing_service.py
│  │  ├─ preprocessing_repository.py
│  │  ├─ preprocessing_planner.py
│  │  ├─ preprocessing_profiler.py
│  │  ├─ preprocessing_exception.py
│  │  └─ preprocessing_router.py
│  ├─ feature/                # [3단계 Current] Preprocessing Plan 및 Schema 기반 Feature Dataset Bundle 발행
│  │  ├─ feature_schema.py
│  │  ├─ feature_service.py
│  │  ├─ feature_repository.py
│  │  ├─ feature_schema_provider.py
│  │  ├─ label_schema_provider.py
│  │  ├─ feature_exception.py
│  │  └─ feature_router.py
│  └─ training_compat/        # [호환성] legacy /internal/train, /internal/retrain 및 lifecycle
│     ├─ training_compat_router.py
│     └─ training_lifecycle.py
│
├─ generator_main.py          # [호환성 Shim] app.main:app 재노출
├─ generator_config.py        # 전역 경로 및 설정 싱글톤
├─ file_integrity.py          # SHA-256 무결성 검증 유틸리티
├─ feature/                   # Feature 계산 모듈 (수학/시계열 변환 기반)
├─ model/                     # 모델 알고리즘 구현 (LightGBM, XGBoost, RandomForest) 및 Registry
├─ ontology_mapping/          # legacy/보조 semantic mapping 모듈; 신규 Feature API 실행 계약이 아님
├─ topology/                  # 설비 간 위상 관계 추론
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
├─ entrypoint.py
├─ Dockerfile
└─ requirements.txt
```

> **단방향 의존성 원칙**: 공통 기반 모듈(`systems/generator/*.py`)은 `app` 하위 모듈을 절대 import하지 않으며, `FastAPI`에 의존하지 않습니다.
>
> **Python 실행 환경 계약 (Execution Environment Contract)**:
> - Generator 시스템은 저장소 루트(Repository Root)를 표준 `PYTHONPATH`로 사용하는 패키지 구조를 가집니다.
> - 저장소 루트 실행: `python -c "import systems.generator.app.preprocessing; import systems.generator.app.feature"`
> - `systems/generator` 작업 디렉터리 실행: `PYTHONPATH=<repository-root>` 환경변수를 제공하여 legacy facade 및 모듈을 실행합니다.

---

## 2. 도메인 API 현황 및 파이프라인

### 2.1 Current API (현재 구현 상태)

현재 Generator 정본 애플리케이션(`systems/generator/app/main.py`)에 실제로 구현되어 동작하는 엔드포인트입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | Current (구현 완료) |
| POST | `/preprocessing` | Observation Dataset 분석, 역할 판정 및 불변 Preprocessing Plan 수립·발행 (동기 방식) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/feature` | Observation/Failure Dataset, Preprocessing Plan, Feature/Label Schema를 소비하여 Feature Dataset Bundle 발행 (동기 방식, local file adapter) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |

### 2.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 책임 분리)을 통해 도입될 목표 API 목록입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

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

### 2.3 파이프라인 흐름

Generator의 4대 파이프라인 단계별 책임과 데이터 흐름입니다.

```text
1. Extraction
   ├─ 지정 Mapping 기반 Protocol Parsing
   ├─ Canonical Observation Dataset 발행
   └─ Authorized Truth Source 기반 Failure Dataset 발행

2. Preprocessing
   ├─ Observation Dataset 구조 분석
   ├─ ID/time/attribute/value 역할 판정
   └─ Immutable Preprocessing Plan 발행

3. Feature
   ├─ Feature Schema allowlist/recipe 적용 (Ontology Mapping 미소비)
   ├─ Label Schema 적용
   └─ Immutable Feature Dataset Bundle 발행

4. Training
   └─ Feature Dataset Bundle → Immutable Model Artifact
```

---

## 3. Preprocessing Plan 불변 저장 구조 및 provenance 계약

- **지원 구조 유형 (Structure Types)**: 공식 지원 범위는 `tabular_column_as_attribute`, `tabular_row_as_attribute` 2종류로 한정되며, `wide_pivot` 및 미지원 형식은 임의 fallback 없이 422 오류로 처리됩니다.
- **Plan 식별**: `preprocessing_plan_id` (`pp-{UUID4}`)와 `preprocessing_plan_version` (`preprocessing-plan-{hash}`) 분리.
- **Dataset 결합 및 Provenance**: Plan은 `source_dataset_uri`, `source_dataset_sha256`, `source_schema_fingerprint`, `decision_source`, `fallback_reason`, `planner_version`과 결합되며, `preprocessing_plan_version`은 이를 포함한 canonical 해시로 산출.
- **논리 URI Fail-Closed**: `source_dataset_uri`, `preprocessing_plan_uri`는 허용된 저장소 루트(`data_dir`, `models_store`, workspace) 기반의 논리 상대경로만 저장되며, 허용 루트 밖 경로는 Fail-Closed로 거부되고 API 응답에 전체 절대경로가 노출되지 않습니다.
- **저장 디렉터리**: `models_store/cache/preprocessing_plans/{dataset_id}/{dataset_version}/`
- **불변 파일 및 포인터**: `pp-{uuid}.json` (고유 불변 파일 atomic rename 발행) 및 `latest.json` (별도 atomic replace 갱신).
- **재사용 및 Fail-Fast 검증**: `force_reanalyze=False` 시 dataset sha256, schema fingerprint 및 중복 정책 불일치 시 `409 PREPROCESSING_PLAN_CONFLICT` 반환. `selected_columns` 또는 역할 컬럼 누락 시 422 fail-fast.
- **동기 실행**: `/preprocessing` 라우터는 동기 함수로 구성되어 FastAPI threadpool에서 안전하게 실행됩니다.

---

## 4. Feature Dataset Bundle 불변 저장 구조 및 Versioned Dataset 입력 계약

- **Versioned Dataset 입력 경로 및 Manifest 계약**:
  - Observation: `data/observations/{dataset_id}/{dataset_version}/` (`dataset_manifest.json`, `observations.csv` 또는 `.jsonl`)
  - Failure: `data/failures/{dataset_id}/{dataset_version}/` (`dataset_manifest.json`, `failures.csv` 또는 `.jsonl`)
  - `contracts/schemas/generator-dataset-input-manifest.schema.json`에 정의된 Manifest 필수 필드, 단일 role(`observations`, `failures`), payload 상대경로 안전성, 실제 파일 SHA-256 및 크기(size_bytes) 일치 여부를 `FeatureInputResolver`가 철저히 검증.
  - unversioned 파일(`data/{dataset_id}.csv` 등)의 암묵적 검색 fallback을 완전히 제거하여 버전 위조를 원천 차단.
- **Preprocessing Plan과 Observation Manifest 상호 검증**:
  - `request.dataset_id == Plan.dataset_id == Observation Manifest.dataset_id`
  - `request.dataset_version == Plan.dataset_version == Observation Manifest.dataset_version`
  - `Plan.source_dataset_sha256 == Observation payload SHA-256`
  - 불일치 시 `422 FEATURE_CONTRACT_ERROR`로 fail-closed.
- **Bundle 식별**: `feature_dataset_version` (`feature-dataset-{hash16}`)은 Observation/Failure Dataset Manifest 및 Payload SHA-256, `failure_source_mode`, Preprocessing Plan(ID/ver/sha), Feature Schema, Label Schema, prediction horizon의 canonical fingerprint로 결정론적 산출.
- **저장 디렉터리**: `models_store/cache/features/{dataset_id}/{dataset_version}/{feature_dataset_version}/`
- **Failure Source 모드 계약**:
  - `external_dataset` (기본값): Failure 데이터셋이 필수이며 파일 미발견 시 404 Fail-Fast (Observation 대체 fallback 없음).
  - `embedded_observation`: Observation 내부 indicator 컬럼(`Machine failure` 등)을 직접 소비.
- **Feature `ffill` 의미 보존**:
  - `missing_value_policy="ffill"` 적용 시 원본 source 컬럼으로 되돌아가지 않고, 이미 계산된 lag/diff/rolling/ewm series 자체를 설비 단위(`asset_id`)로 forward-fill.
- **`binary_failure_within_horizon` Feature Dataset 발행 조건 (Fail-Closed)**:
  1. **Canonical Observation timestamp 필수**: 누락 또는 NaT 포함 시 `422 FEATURE_LABEL_ALIGNMENT_ERROR`로 거부.
  2. **유효한 failure event 최소 1건 필수**: 외부 Failure Dataset 0행 시 `422 INSUFFICIENT_TRAINING_DATA`로 거부.
  3. **Active failure filtering 후 event 최소 1건 필수**: indicator 필터링 후 0건 시 `422 INSUFFICIENT_TRAINING_DATA`로 거부.
  4. **내장 failure event timestamp 오류 거부**: embedded indicator 행의 timestamp NaT 시 건너뛰지 않고 `422 FEATURE_LABEL_ALIGNMENT_ERROR`로 거부.
  5. **최종 Label 클래스 `{0, 1}` 양자 공존 필수**: 최종 생존 라벨에 0과 1이 모두 존재해야 하며, 단일 클래스 시 `422 INSUFFICIENT_TRAINING_DATA`로 거부.
  6. **설비 Identity & 제외 구간 엄격성**: 다중 설비에서 failure asset 누락/미소속 시 `422`, `anchor`/`exclusion_end` 누락, NaT, 또는 `exclusion_end < anchor` 위반 시 `422` 반환 및 `[anchor, exclusion_end]` 전체 구간 학습 데이터 제외.
- **Asset identity requirement (Fail-Closed 501)**:
  - `POST /feature`가 소비하는 Observation Dataset에는 Preprocessing Plan의 `id_column`으로 선언된 설비 식별 컬럼이 반드시 존재해야 한다.
  - 현재 파이프라인은 ID가 없는 Dataset을 자동으로 단일 설비로 간주하거나 임시 ID(`row_{idx}`, `default_asset`)를 생성하지 않는다.
  - Plan에 `id_column` 누락, Dataset 내 컬럼 미존재, 또는 null/empty ID 값 포함 시 `501 FEATURE_ASSET_ID_RESOLUTION_NOT_IMPLEMENTED`로 실패하며 Feature Dataset Bundle을 발행하지 않는다.
  - ID가 없는 단일 설비 Dataset 지원은 후속 기능으로 별도 구현한다.
- **허용되지 않는 Fallback (Prohibited Fallbacks)**:
  - `row_{idx}`, `default_asset` 등 임시 asset ID 생성 금지
  - Preprocessing Plan의 `id_column` 누락 시 임의 컬럼 휴리스틱 선택 금지
  - timestamp 위치 기반 추측 금지
  - invalid timestamp 행 조용한 건너뛰기(silent skip) 금지
  - 빈 Failure Dataset을 정상 Dataset으로 처리 금지
  - all-zero Label Bundle 발행 금지
  - 단일 클래스 Label을 Training 단계로 전달 금지
  - unversioned 파일 검색 fallback 금지
- **5개 필수 파일 구성**:
  1. `features.npy`: 2D float64 배열, `allow_pickle=False`, NaN/Inf 불가
  2. `labels.npy`: 1D int64 배열 `{0, 1}`, `allow_pickle=False`
  3. `feature_columns.json`: Feature Schema 선언 순서의 컬럼 목록 및 수량
  4. `row_metadata.json`: Feature/Label 행과 1:1 대응되는 실제 설비 식별자(`asset_id`) 및 timestamp
  5. `feature_metadata.json`: 데이터셋 Manifest/payload provenance, 스키마 provenance, 클래스 분포, 4개 payload 파일의 개별 SHA-256 체크섬 (자기참조 순환 방지)
- **원자적 발행 및 불변성 정책**:
  - 임시 디렉터리(`.tmp_{uuid}`)에서 전체 생성 및 검증 완료 후 atomic rename/replace.
  - 동일 fingerprint 시 기존 유효 Bundle 즉시 재사용. Fingerprint 불일치 시 `409 FeaturePublishConflictError`, 파일 손상 시 `422 FeatureDatasetIntegrityError` 반환.
- **동기 실행**: `/feature` 엔드포인트는 동기 함수로 구성되어 FastAPI threadpool에서 안전하게 실행됩니다.

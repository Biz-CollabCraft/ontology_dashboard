# Generator 목표 아키텍처 및 파일 가공 파이프라인 명세서

> **문서 상태**: `Proposed Target` (제안된 목표 설계)
> **주의**: 본 문서는 현재 `main`에 구현된 코드를 설명하는 문서가 아닙니다. 본 문서는 향후 진행될 Generator 구조 개편, 단계별 책임 분리, API 명칭 전환 및 파일 가공 파이프라인 Migration 작업의 단일 기준이 되는 **목표 설계(Target Specification) 문서**입니다.

---

## 1. 배경 및 목적

1. **Observation/Feature Series 책임 정립 (생산자 경계 확립 작업)**:
   - Generator 시스템을 센서/프로토콜 로그로부터 정제된 Observation 및 Feature Series를 생성하는 공식 생산자(Producer)로 정의합니다.
   - 제품 런타임(Backend Diagnosis)은 `gen_data`의 저수준 프로토콜 로그 파일을 직접 파싱하지 않고, Generator가 가공·발행한 정제된 Observation/Feature 산출물 및 Model Artifact를 소비하도록 단방향 데이터 흐름을 확립합니다.

2. **Layer 2 프로토콜 로그와 Reference Fixture (프로토콜 정규화 작업)**:
   - `gen_data` Layer 2 프로토콜 로그 입력 fixture(`sample_log.jsonl`)와 기대 Observation fixture(`expected_observations.json`)가 도입되었습니다.
   - 현재 Generator 내부에는 이 파일 가공 흐름을 표준적·안정적으로 수행할 공식 파일 처리 계층이 아직 구현되어 있지 않으므로, 목표 구조와 가공 규칙을 먼저 문서로 확정합니다.

3. **단계 명칭 정립 및 선행 API화 작업 연계**:
   - 별도 Generator API화 작업에서 설계된 `/extraction`은 데이터셋 분석, Extraction Plan 수립 및 Ontology Mapping을 담당합니다.
   - Target 구조에서는 이 기능을 `/preprocessing`으로 이전하고, `/extraction`은 `gen_data` Layer 2 프로토콜 로그 가공에 사용하도록 4대 파이프라인 단계(`Extraction` → `Preprocessing` → `Feature` → `Training`)의 역할을 명확히 확정합니다.

---

## 2. 시스템 아키텍처 구조 비교

### 2.1 Current 구조 (현재 main 구현 상태)

현재 `main` 브랜치의 Generator는 다음 단일 수준의 디렉터리 및 모듈 구성을 유지하고 있습니다.

```text
systems/generator/
├─ generator_main.py          # 데몬 진입점 및 FastAPI 애플리케이션 (현재 /internal 엔드포인트)
├─ generator_config.py        # 전역 경로 및 설정 싱글톤
├─ extraction/                # 데이터셋 프로파일링, 추출 계획 수립 (LLM)
├─ feature/                   # 피처 계산 모듈 (feature_builder 등)
├─ model/                     # 모델 알고리즘 학습 및 모델 레지스트리
├─ ontology_mapping/          # 컬럼-온톨로지 노드 의미 매핑
├─ topology/                  # 설비 위상 관계 추론
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
├─ entrypoint.py
├─ Dockerfile
└─ requirements.txt
```

### 2.2 Target 구조 (후속 목표 설계)

후속 구조 개편 작업에서는 프레임워크 비의존 공통 모듈을 `systems/generator/` 최상위에 배치하고, use case와 API 계층을 `app/` 하위 도메인으로 분리합니다 (`core/` 디렉터리는 사용하지 않음).

```text
systems/generator/
├─ app/                       # [Target] FastAPI 애플리케이션 및 유스케이스 계층
│  ├─ main.py                 # FastAPI Application Factory (create_app)
│  ├─ dependencies.py         # 공통 의존성 주입 (Repository/Service/Settings)
│  ├─ api/                    # 중앙 Router 조립
│  ├─ extraction/             # [1단계 Target] gen_data 프로토콜 로그 추출 도메인
│  │  ├─ extraction_router.py
│  │  ├─ extraction_service.py
│  │  ├─ extraction_repository.py
│  │  └─ extraction_schema.py
│  ├─ preprocessing/          # [2단계 Target] 데이터셋 분석, Plan/Mapping 수립 도메인 (기존 extraction 이전)
│  │  ├─ preprocessing_router.py
│  │  ├─ preprocessing_service.py
│  │  ├─ preprocessing_planner.py
│  │  ├─ preprocessing_profiler.py
│  │  ├─ preprocessing_repository.py
│  │  └─ preprocessing_schema.py
│  ├─ feature/                # [3단계 Target] Feature/Label/Series 빌드 및 번들 발행 도메인
│  │  ├─ feature_router.py
│  │  ├─ feature_service.py
│  │  ├─ feature_repository.py
│  │  ├─ feature_schema_provider.py
│  │  ├─ label_schema_provider.py
│  │  └─ feature_schema.py
│  └─ training/               # [4단계 Target] 모델 학습, 검증, Artifact 발행 및 활성화 도메인
│     ├─ training_router.py
│     ├─ training_service.py
│     ├─ training_repository.py
│     └─ training_schema.py
│
├─ settings.py                # [Target] 환경설정 싱글톤 (Pydantic Settings)
├─ paths.py                   # [Target] 시스템 전역 파일/디렉터리 경로 레지스트리
├─ logging.py                 # [Target] 구조화 로깅 유틸리티
├─ errors.py                  # [Target] 시스템 전역 표준 ErrorEnvelope 및 공통 예외
├─ file_integrity.py          # [Target] SHA-256 해시 계산 및 파일 안전성 검사기
└─ atomic_publish.py          # [Target] 원자적 임시 디렉터리/파일 Staging 및 교체 유틸리티
```

> **계층 의존성 원칙**: 최상위 공통 기반 모듈(`settings.py`, `paths.py`, `errors.py` 등)은 `app/` 하위 모듈을 절대 import하지 않으며, `FastAPI`에 의존하지 않는 순수 Python 모듈로 작성됩니다.

---

## 3. 4대 파이프라인 단계 및 데이터 흐름 (Target)

시스템 간 통신은 API 호출 및 **파일 기반 Handoff**로 진행되며, `/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않습니다.

```text
gen_data
  ↓ Layer 2 protocol log file (파일 handoff)
Generator Extraction
  ↓ Versioned Observation Dataset / Versioned Failure Dataset
Generator Preprocessing
  ↓ Preprocessing Plan / Ontology Mapping
Generator Feature
  ↓ Feature Dataset Bundle + Observation/Feature series
Generator Training
  ↓ Immutable Model Artifact (latest.json pointer)
Backend Diagnosis
  ↓ Runtime inference / Product Result Artifact / Evidence / Prediction History
Backend Report
  ↓ AssetDetailReportViewModel (공식 read port 기반 composition)
```

### 3.1 단계별 상세 책임 명세 (Target)

#### 1단계: Extraction (신규 파일 가공 — Target)
- **입력**: `gen_data` Layer 2 append-only 로그 파일 (`_log.jsonl`)
- **최소 입력 필드 (Target 예시)**: `node_id`, `source_timestamp`, `server_timestamp`, `value`, `status_code`, `reason`
- **처리 규칙**:
  - `node_id` 파싱: `{asset_id}.{sensor_key}` 형식 분리
  - 타임스탬프 정규화: `source_timestamp`를 `observed_at` (ISO-8601 UTC)으로 변환, `server_timestamp`는 provenance로 보존
  - 동일 `asset_id` + `observed_at` 기준 다중 센서 행 피벗(Pivot)
  - 결측 및 품질 보존: Bad/null/에러 상태값을 임의로 `0`이나 정상값으로 왜곡하지 않고 `quality`, `reason` 메타데이터에 그대로 보존
  - Truth 분리: 고장 라벨/이벤트 정보는 Observation과 엄격히 분리하여 Failure Dataset으로 별도 추출
  - 결정적 정렬: `asset_id` 및 `observed_at` 기준 정렬 보장
- **출력 경로 (Target 예시)**:
  - `data_preprocessed/observations/{dataset_id}/{dataset_version}/observations.jsonl`
  - `data_preprocessed/observations/{dataset_id}/{dataset_version}/observation_metadata.json`
  - `data_preprocessed/failures/{failure_dataset_id}/{failure_dataset_version}/failure_events.jsonl`
  - `data_preprocessed/failures/{failure_dataset_id}/{failure_dataset_version}/failure_metadata.json`

```json
// Observation JSONL 레코드 규격 (Target 예시)
{
  "asset_id": "CNC-S01-L01-01",
  "observed_at": "2026-08-20T01:00:00Z",
  "measurements": {
    "voltage": 220.5,
    "rotation": 1502.1
  },
  "quality": {
    "voltage": {"status_code": "Good", "reason": null},
    "rotation": {"status_code": "Good", "reason": null}
  },
  "source": {
    "log_file": "gen_data/logs/cnc_line1_20260820_log.jsonl",
    "server_timestamp": "2026-08-20T01:00:01.123Z"
  }
}
```

#### 2단계: Preprocessing (기존 Extraction 기능 이전 — Target)
- **입력**: Versioned Observation Dataset (`observations.jsonl`, `observation_metadata.json`)
- **처리**:
  - 파일 프로파일링 및 데이터 구조 타입 판별 (`tabular_column_as_attribute`, `tabular_row_as_attribute`)
  - 역할 컬럼 확정 (`id_column`, `time_column`, `duplicate_policy` 등)
  - 컬럼별 표준 온톨로지 매핑 (MappingStore, 전역 캐시 오염 방지)
  - 내용 기반 해시(SHA-256) 버전 산출 (`preprocessing-plan-<hash>`, `ontology-mapping-<hash>`)
- **출력**: `PreprocessingPlan`, `OntologyMapping`

#### 3단계: Feature (Target)
- **입력**: Observation Dataset, Failure Dataset, Preprocessing Plan, Ontology Mapping, Feature/Label Schema
- **처리**:
  - 번들 재사용 전 Sensor 및 Failure 원본 파일 무결성 및 해시 전수 검증
  - 설비별 시계열 피처 추출 (`build_features`), 고장 이력 기반 라벨링 (`build_labels`)
  - 시간순 분할 메타데이터 생성 (`compute_asset_time_split_indices`, `validate_split_indices`)
  - Feature Schema 선언 순서 유지 및 누수 컬럼 배제
  - NPY 및 메타데이터 원자적 발행
- **출력**: `Feature Dataset Bundle` (`features.npy`, `labels.npy`, `feature_columns.json`, `row_metadata.json`, `feature_metadata.json`), `Observation/Feature series`

#### 4단계: Training (Target)
- **입력**: Feature Dataset Bundle
- **처리**:
  - Feature Bundle 파일/체크섬/차원/타입 전수 검증
  - `asset_time_split` 기반 train/val/test 시간순 분할
  - 등록 모델(`lightgbm`, `xgboost`, `random_forest`) 학습 및 지표 산출 (모델별 실패 격리)
  - 불변 Model Artifact 패키지 발행 및 Validator 검증
  - `activation_policy`(`latest`/`manual`)에 따른 `latest.json` 포인터 갱신 및 실패 복구 지원
- **출력**: 불변 Model Artifact 패키지 (`model-artifact-v1.0`), 활성 모델 포인터 (`latest.json`)

---

## 4. API 명칭 및 Migration 계획

### 4.1 Current API (현재 main 구현 상태) vs Target API (후속 목표 설계)

| Method | Path | Current 상태 (현재 main) | Target 의미 (후속 목표) |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Generator 데몬 상태 확인 |
| POST | `/internal/train` | 데몬 최초 학습 실행 (내부 Lock 제어) | 후속 migration 시 호환 shim 유지 또는 정리 검토 |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (내부 Lock 제어) | 후속 migration 시 호환 shim 유지 또는 정리 검토 |
| POST | `/extraction` | Target — 미병합 | **gen_data 프로토콜 로그를 Observation/Failure Dataset으로 추출 (신규 1단계)** |
| POST | `/preprocessing` | Target — 미병합 | **Observation Dataset 분석 및 Preprocessing Plan/Mapping 발행 (신규 2단계)** |
| POST | `/feature` | Target — 미병합 | **Feature/Label/Series 및 Feature Dataset Bundle 발행 (신규 3단계)** |
| POST | `/train` | Target — 미병합 | **전체 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계)** |
| POST | `/train/{base_model}` | Target — 미병합 | **특정 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계)** |
| POST | `/models/{base_model}/activate/{model_version}` | Target — 미병합 | **기존 발행된 불변 Model Artifact 패키지 수동 활성화** |
| GET | `/models/{base_model}/active` | Target — 미병합 | **현재 활성화된 Model Artifact 정보 조회** |

### 4.2 타입 및 클래스 Migration Mapping 계획

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
| (신규 구현) | `POST /extraction` | 신규 Layer 2 로그 추출 엔드포인트 구현 |
| (신규 구현) | `ExtractionService` | 신규 Observation/Failure Dataset 발행 서비스 구현 |

---

## 5. 기존 Generator 코드 이식 계획

현재까지 개발된 무결성 검증 및 비즈니스 로직은 누락 없이 새 구조로 이동할 계획입니다:

1. **현재 Extraction 기능 → `app/preprocessing/`으로 이전**:
   - Dataset profiling, LLM 2단계 구조 판별 및 규칙 수립 로직
   - long-format (`tabular_row_as_attribute`) 역할 컬럼 검증
   - Ontology Mapping 수립 및 MappingStore 캐시 격리
   - Plan/Mapping 내용 기반 해시 버전 발행 및 원본 source SHA-256 검증
2. **현재 Feature 기능 → `app/feature/`에 유지·정리**:
   - Feature Bundle 재사용 전 원본 Sensor/Failure 파일 및 provenance 전수 재검증
   - Failure Dataset 버전 경로 고정 및 설비 ID 호환성 검증
   - 시계열 Feature 추출, horizon 라벨링, allowlist 및 선언 순서 유지
   - `split_indices` 및 `row_metadata.json` 무결성 검증
3. **현재 Training 기능 → `app/training/`에 유지·정리**:
   - 전체 및 개별 모델 학습 오케스트레이션
   - Feature Dataset Bundle 전수 체크섬 검증
   - `asset_time_split` 시간순 분할 인덱스 검증
   - 모델별 학습 실패 격리 및 불변 Model Artifact 패키지 발행
   - `activation_policy`(`latest`/`manual`), `latest.json` 원자적 갱신 및 수동 활성화 복구
4. **실행 진입점 및 설정 모듈 이전**:
   - `generator_main.py` → `app/main.py`의 `create_app()` 팩토리 기반으로 migration
   - `generator_config.py` → `settings.py` 및 `paths.py` 정본 모듈로 migration
   - 기존 파일은 migration 기간 동안 compatibility shim으로 유지하되 신규 로직 추가는 금지

---

## 6. 계약 스키마 관리 상태 및 후속 정합성 검증 계획

### 6.1 계약 스키마 상태 표

| 계약 대상 | 상태 | 설명 |
|---|---|---|
| Observation Reference Fixture | 참고 fixture 존재 | `tests/fixtures/gen_data_layer2_observation/` (참고용) |
| `generator-observation.schema.json` | **Target — 미작성** | Extraction 구현 단계에서 작성 예정 |
| `generator-failure-event.schema.json` | **Target — 미작성** | Extraction 구현 단계에서 작성 예정 |
| `generator-extraction-result.schema.json` | **Target — 미작성** | Extraction 구현 단계에서 작성 예정 |
| `generator-preprocessing-plan.schema.json` | **Target — 이전 예정** | 기존 Extraction Plan 스키마 검토 후 migration 예정 |
| `generator-feature-series.schema.json` | **Target — 미작성** | Feature 구현 단계에서 작성 예정 |
| Feature Dataset Bundle | **Target — 검토 필요** | 기존 `dataset-bundle-manifest.schema.json` 재사용·확장 여부 검토 |

> **주의**: 본 문서 변경 범위에서는 빈 스키마 파일이나 placeholder JSON을 일체 생성하지 않습니다.

### 6.2 스키마 물리 이관 완료 후 수행할 정합성 검증 항목

별도 스키마 물리 이관 작업이 완료된 후에는 다음 검증을 순차적으로 수행합니다:
1. 실제 `contracts/schemas/` 파일 목록과 문서 내 참조 목록의 1:1 일치 여부 비교
2. 문서 내 `미작성`, `이전 예정` 상태 태그 현행화
3. 스키마 `$id` 식별자 및 내부 `$ref` 경로 유효성 검증
4. 문서 내 예시 JSON payload와 JSON Schema 간의 유효성 검증 (Draft 2020-12)
5. Pydantic API 모델과 JSON Schema 필드 간의 100% 정합성 검증
6. 기존 스키마와 신규 스키마 간의 역할 중복 여부 전수 검사

---

## 7. 후속 구현 로드맵 (단계별 계획)

```text
[구조 migration 단계]
  ├─ 공통 기반 모듈(settings.py, paths.py, errors.py, file_integrity.py, atomic_publish.py) 구성
  ├─ FastAPI Application Factory (app/main.py create_app) 및 Router Composition
  ├─ 기존 Extraction 도메인 → Preprocessing 도메인 rename 및 이전
  ├─ Feature / Training 도메인 파일 이식 및 정리
  ├─ Compatibility Shim 구성 (기존 import 경로 임시 지원)
  └─ API 테스트 회귀 검증

        ↓

[프로토콜 로그 Extraction 구현 단계]
  ├─ Layer 2 append-only JSONL 파서 구현
  ├─ node_id 분리, timestamp 정규화 및 다중 센서 행 피벗
  ├─ quality/reason 메타데이터 보존 및 Failure truth 분리
  ├─ Versioned Observation / Failure Dataset 원자적 발행 및 SHA-256 체크섬
  └─ Reference Fixture 비교 계약 테스트 작성

        ↓

[파이프라인 통합·검증 단계]
  ├─ Extraction 산출물 → Preprocessing 파이프라인 연결
  ├─ Preprocessing Plan/Mapping → Feature 파이프라인 연결
  ├─ Feature Dataset Bundle → Training 파이프라인 연결
  ├─ Observation/Feature Series 공식 계약 스키마 확정
  └─ Architecture CI 규칙 추가 (공통 모듈 app 역참조 금지, FastAPI 비의존 등)
```

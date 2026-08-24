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
│  └─ training_compat/        # [호환성] legacy /internal/train, /internal/retrain 및 lifecycle
│     ├─ training_compat_router.py
│     └─ training_lifecycle.py
│
├─ generator_main.py          # [호환성 Shim] app.main:app 재노출
├─ generator_config.py        # 전역 경로 및 설정 싱글톤
├─ file_integrity.py          # SHA-256 무결성 검증 유틸리티
├─ feature/                   # Feature 계산 모듈
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
> - 저장소 루트 실행: `python -c "import systems.generator.app.preprocessing"`
> - `systems/generator` 작업 디렉터리 실행: `PYTHONPATH=<repository-root>` 환경변수를 제공하여 legacy facade 및 모듈을 실행합니다.

---

## 2. 도메인 API 현황 및 파이프라인

### 2.1 Current API (현재 구현 상태)

현재 Generator 정본 애플리케이션(`systems/generator/app/main.py`)에 실제로 구현되어 동작하는 엔드포인트입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | Current (구현 완료) |
| POST | `/preprocessing` | Observation Dataset 분석, 역할 판정 및 불변 Preprocessing Plan 수립·발행 (동기 방식) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |

### 2.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 책임 분리)을 통해 도입될 목표 API 목록입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

| Method | Path | Target 의미 및 4대 파이프라인 단계 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Current (유지) |
| POST | `/extraction` | gen_data protocol data에 지정·승인된 Mapping을 적용하여 Versioned Canonical Observation Dataset을 발행하고, 별도 Authorized Truth Source로 Failure Dataset을 발행 (관련 후속 작업: Issue #108) | Target — 미병합 |
| POST | `/preprocessing` | Observation Dataset을 분석하여 불변 Preprocessing Plan 수립 및 발행 (신규 2단계) | Current — 구현 및 정본 Generator App 등록 완료 |
| POST | `/feature` | Observation Dataset, Failure Dataset, Preprocessing Plan, Feature Schema 및 Label Schema를 소비하여 Feature/Label Dataset Bundle 발행 (신규 3단계) | Target — 미병합 |
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
   ├─ Feature Schema allowlist/recipe 적용
   ├─ Label Schema 적용
   └─ Feature Dataset Bundle 발행

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

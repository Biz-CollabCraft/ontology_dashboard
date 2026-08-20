# Generator Domain (FastAPI 기반 재구성)

`systems/generator`는 센서 데이터셋 분석, 추출 계획(Extraction Plan) 수립, 온톨로지 매핑, Feature/Label 빌드 및 머신러닝 모델 학습과 Model Artifact 발행을 전담하는 도메인 시스템입니다.

---

## 1. 아키텍처 및 패키지 구조

FastAPI 기반의 도메인 주도 계층 구조(`systems/generator/app/`)를 도입하여 각 파이프라인 단계를 독립된 도메인으로 분리 운영합니다.

```text
systems/generator/
├─ app/
│  ├─ __init__.py
│  ├─ main.py                 # Generator FastAPI App 진입점, 공통 ErrorEnvelope, Request-ID 미들웨어
│  ├─ extraction/             # Extraction 도메인 (Plan & Mapping 수립 및 불변 영속화)
│  │  ├─ __init__.py
│  │  ├─ extraction_router.py # POST /extraction HTTP 엔드포인트
│  │  ├─ extraction_schema.py # ExtractionRequest, ExtractionResponse, ExtractionPlanResponse, ErrorEnvelope
│  │  ├─ extraction_service.py# 데이터셋 경로 해석(보안 containment), Plan/Mapping 생성/검증, extract_with_plan 실행
│  │  ├─ extraction_planner.py# LLM 2단계 구조 판별 및 컬럼 역할 규칙 계획기
│  │  ├─ extraction_repository.py # Plan/Mapping 내용 기반 해시 버전 영속화 및 재사용 전 무결성 검증
│  │  ├─ extraction_profiler.py # Stage 0 파일 프로파일링
│  │  └─ extraction_exception.py# Extraction 도메인 예외 계층
│  ├─ feature/                # Feature 도메인 (Plan/Mapping/Failure 소비, Feature·Label·NPY 생성)
│  │  ├─ __init__.py
│  │  ├─ feature_router.py    # POST /feature HTTP 엔드포인트
│  │  ├─ feature_schema.py    # FeatureRequest, FeatureResponse, FeatureOutputsPayload 등 (식별자 검증)
│  │  ├─ feature_service.py   # Plan/Mapping/Failure 조회/검증, Feature 계산, Label 생성, allowlist 적용
│  │  ├─ feature_schema_provider.py # Feature Schema allowlist 조회 및 선언 순서 보장 검증기
│  │  ├─ label_schema_provider.py   # Label Schema 조회 및 prediction_task/horizon/anchor 검증기
│  │  ├─ feature_repository.py# 불변 디렉터리 기반 NPY 및 메타데이터 원자적 Staging, Publish 및 재사용 무결성 검증
│  │  └─ feature_exception.py # Feature 도메인 예외 계층
│  └─ training/               # Training 도메인 (Feature Bundle 소비, 모델 학습, Model Artifact 발행, 활성화)
│     ├─ __init__.py
│     ├─ training_router.py   # POST /train, POST /train/{base_model}, POST /models/.../activate, GET /models/.../active
│     ├─ training_schema.py   # TrainingRequest, TrainingResponse, ModelResultItem, ModelActivationResponse, ActiveModelResponse
│     ├─ training_service.py  # Bundle 검증, asset_time_split, 모델별 학습 격리, Artifact 발행 및 활성화 orchestration
│     ├─ training_repository.py # Feature Bundle 로드/무결성 전수 검증, Model Artifact 불변 발행/검증, latest.json 관리
│     └─ training_exception.py# Training 도메인 예외 계층
├─ extraction/                # [Compatibility Facade] 하위 호환 re-export 제공
├─ ontology_mapping/          # 온톨로지 매핑 도메인 (전역 캐시 오염 방지)
├─ feature/                   # Feature 엔지니어링 계산 모듈 (feature_builder, feature_label_service 등)
├─ model/                     # 모델 알고리즘 구현 (LightGBM, XGBoost, RandomForest) 및 Registry
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
└─ generator_config.py        # 시스템 전역 경로 및 환경설정 싱글톤
```

---

## 2. 도메인 API 현황

| Method | Path | 목적 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | 완료 |
| POST | `/extraction` | 데이터셋 분석 및 내용 기반 해시 Extraction Plan/Mapping 수립·검증·불변 영속화 | 완료 (1단계) |
| POST | `/feature` | Extraction Plan/Mapping 및 명시적 Failure 데이터 소비, Feature·Label 생성 및 NPY/메타데이터 불변 발행 | 완료 (2단계) |
| POST | `/train` | 등록된 전체 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행 및 활성화 | **완료 (3단계, Canonical API)** |
| POST | `/train/{base_model}` | 지정된 개별 머신러닝 모델 학습 및 불변 Model Artifact v1.0 패키지 발행 및 활성화 | **완료 (3단계, Canonical API)** |
| POST | `/models/{base_model}/activate/{model_version}` | 지정된 모델 버전을 수동 활성화하고 latest.json 포인터 갱신 | **완료 (활성화 제어 API)** |
| GET | `/models/{base_model}/active` | 현재 활성화된 모델 버전 및 아티팩트 정보 조회 | **완료 (활성화 조회 API)** |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 Lock 제어) | 기존 legacy 호환 API |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 Lock 제어) | 기존 legacy 호환 API |

> **학습 API 경로 상태 구분**:
> - 신규 호출자는 `/train` 및 `/train/{base_model}` 계약을 사용해야 하며, `/internal/train`, `/internal/retrain`은 기존 기능 호환용입니다.
> - 두 계층은 동일한 프로세스 전역 학습 Lock을 공유하여 중복 실행 충돌을 방지합니다.

---

## 3. 파이프라인 단계별 경계 및 안전 원칙

```text
[1단계: POST /extraction]
  → 데이터셋 경로 보안 검증 (허용된 루트 내 상대경로, 절대경로/상위경로 거부)
  → 데이터셋 분석 및 Sensor 원본 SHA-256 해시 계산
  → Extraction Plan 생성·검증 (기존 파일 존재 시 무결성 검증 후 재사용)
  → Ontology Mapping 생성·검증 (전역 캐시 미오염 persist=False, 기존 파일 무결성 검증 후 재사용)
  → 내용 기반 해시(SHA-256) 버전 산출 (extraction-plan-<hash>, ontology-mapping-<hash>)
  → Plan & Mapping 독립적 불변 영속화 (models_store/cache/extraction_plans, models_store/cache/mappings)

        ↓

[2단계: POST /feature]
  → Sensor 원본 데이터셋 SHA-256 해시 일치 검증 (SOURCE_DATASET_INTEGRITY_ERROR)
  → Label Schema 실제 로드 및 검증 (prediction_task, horizon, anchor, positive_class)
  → 기존 Extraction Plan 및 Ontology Mapping 무결성 검증 및 조회
  → 명시적 Failure 데이터셋(버전 경로 고정, versionless fallback 배제) 연결 및 설비 ID 호환성 검증
  → 9대 계약 요소 SHA-256 지문(feature-dataset-<fingerprint>) 산출
  → 기존 Feature Bundle 존재 시 전체 4개 파일/차원/dtype/NaN 무결성 검증(FEATURE_DATASET_INTEGRITY_ERROR) 후 재사용
  → 원본 데이터 추출 (기존 label 컬럼 배제)
  → 시계열 Feature 계산 (build_features)
  → 공식 고장 이력 기반 Label 생성 (build_labels, positive 0건 및 결측치 fail-fast)
  → Feature Schema allowlist 검증 및 선언 순서 유지
  → split_indices 및 row_metadata.json 검증 및 생성 (실패 시 TRAINING_SPLIT_METADATA_MISSING fail-fast)
  → 체크섬 allowlist(ALLOWED_FEATURE_BUNDLE_FILES) 검증 및 불변 NPY 및 메타데이터 원자적 발행

        ↓

[3단계: POST /train 및 POST /train/{base_model}]
  → 프로세스 전역 학습 Lock 획득 (단일 워커 제한, 중복 요청 시 TRAINING_ALREADY_RUNNING 409)
  → Feature Dataset Bundle SHA-256 체크섬 및 무결성 전수 검증 (shape, dtype, NaN/Inf 부재, {0,1} 라벨)
  → Feature Schema 열 순서 및 스키마 메타데이터 엄격 검증 (FEATURE_SCHEMA_MISMATCH 422)
  → 설비 ID/타임스탬프 원본 인덱스 기반 시간순 분할 및 정합성 검증 (asset_time_split, split_indices)
  → 관측 주기 기반 동적 History Requirement 계산 (lookback, minimum history rows)
  → 등록 모델(lightgbm, xgboost, random_forest) 학습 및 평가 지표 산출 (모델별 실패 격리)
  → 불변 Model Artifact v1.0 패키지(manifest.json, model.joblib, schemas, metrics) 원자적 발행
  → 발행 직후 validator 검증 및 activation_policy(latest/manual)에 따른 latest.json 활성 포인터 원자적 갱신
  → 모델별 결과 반환 (succeeded / partially_succeeded)
```

1. **Feature Bundle SHA-256 체크섬 및 무결성 전수 검증**:
   - 학습 전 `features.npy`, `labels.npy`, `feature_columns.json`, `feature_metadata.json`, `row_metadata.json`의 SHA-256 체크섬을 재계산하여 선언값과 비교하고 shape, dtype, NaN/Inf 부재, `{0, 1}` 값 범위, 계약 지문 일치를 전수 검증합니다.
2. **미래 데이터 누수 방지 시간순 분할 및 정합성 보장 (`asset_time_split`)**:
   - 원본 행 식별자(`_row_index`)를 기반으로 설비별 시간순 분할 인덱스(`split_indices: {"train": [...], "val": [...], "test": [...]}`)를 생성·검증합니다.
   - 상호 배타성, 중복 부재, 전체 커버리지, 설비별 시간순(train <= val <= test)을 만족해야 합니다.
3. **독립된 불변 Model Artifact v1.0 발행 및 Active Version 연결**:
   - Generator의 책임 끝점은 Model Artifact v1.0 발행 및 `<models_store>/artifacts/<model_id>/latest.json` 활성 버전 갱신이며, Runtime Inference(예측), Evidence, Result Artifact 발행은 Backend Diagnosis의 책임입니다.
4. **단일 워커 제한 및 동시성 제어**:
   - Generator 데몬은 단일 프로세스/단일 워커 환경을 전제로 하며, canonical `/train` 및 legacy `/internal/train`, `/internal/retrain`은 프로세스 전역 `_training_lock`을 공유하여 동시 실행을 방지합니다.

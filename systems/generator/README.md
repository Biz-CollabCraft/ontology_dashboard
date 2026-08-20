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
│  └─ feature/                # Feature 도메인 (Plan/Mapping/Failure 소비, Feature·Label·NPY 생성)
│     ├─ __init__.py
│     ├─ feature_router.py    # POST /feature HTTP 엔드포인트
│     ├─ feature_schema.py    # FeatureRequest, FeatureResponse, FeatureOutputsPayload 등 (식별자 검증)
│     ├─ feature_service.py   # Plan/Mapping/Failure 조회/검증, Feature 계산, Label 생성, allowlist 적용
│     ├─ feature_schema_provider.py # Feature Schema allowlist 조회 및 선언 순서 보장 검증기
│     ├─ label_schema_provider.py   # Label Schema 조회 및 prediction_task/horizon/anchor 검증기
│     ├─ feature_repository.py# 불변 디렉터리 기반 NPY 및 메타데이터 원자적 Staging, Publish 및 재사용 무결성 검증
│     └─ feature_exception.py # Feature 도메인 예외 계층
├─ extraction/                # [Compatibility Facade] 하위 호환 re-export 제공
├─ ontology_mapping/          # 온톨로지 매핑 도메인 (전역 캐시 오염 방지)
├─ feature/                   # Feature 엔지니어링 계산 모듈 (feature_builder, feature_label_service 등)
├─ model/                     # 모델 학습 및 Artifact 발행 도메인 (후속 /train 단계 대상)
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
| POST | `/train` | 다중 머신러닝 모델 학습 및 Model Artifact 발행 | **신규 canonical API (후속 PR 구현 대상)** |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 Lock 제어) | **기존 legacy 호환 API** |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 Lock 제어) | **기존 legacy 호환 API** |

> **학습 API 경로 상태 구분**:
> - 신규 호출자는 `/train` 계약을 사용해야 하며, `/internal/train`, `/internal/retrain`은 현재 main의 기존 기능 호환용입니다.
> - 후속 `/train` 구현과 검증이 완료되기 전에는 legacy 경로를 제거하지 않으며, 장기적으로 세 경로를 병행 운영하지 않습니다.
> - 이번 Feature 브랜치에서는 학습 API 코드를 변경하지 않습니다.

---

## 3. 파이프라인 단계별 경계 및 안전 원칙

```text
[1단계: POST /extraction]
  → 데이터셋 경로 보안 검증 (허용된 루트 내 상대경로, 절대경로/상위경로 거부)
  → 데이터셋 분석
  → Extraction Plan 생성·검증 (기존 파일 존재 시 무결성 검증 후 재사용)
  → Ontology Mapping 생성·검증 (전역 캐시 미오염 persist=False, 기존 파일 무결성 검증 후 재사용)
  → 내용 기반 해시(SHA-256) 버전 산출 (extraction-plan-<hash>, ontology-mapping-<hash>)
  → Plan & Mapping 독립적 불변 영속화 (models_store/cache/extraction_plans, models_store/cache/mappings)

        ↓

[2단계: POST /feature]
  → Label Schema 실제 로드 및 검증 (prediction_task, horizon, anchor, positive_class)
  → 기존 Extraction Plan 및 Ontology Mapping 무결성 검증 및 조회
  → 명시적 Failure 데이터셋(failure_dataset_id, failure_dataset_version) 연결 및 설비 ID 호환성 검증
  → 9대 계약 요소 SHA-256 지문(feature-dataset-<fingerprint>) 산출
  → 기존 Feature Bundle 존재 시 전체 4개 파일/차원/dtype/NaN 무결성 검증(FEATURE_DATASET_INTEGRITY_ERROR) 후 재사용
  → 원본 데이터 추출 (기존 label 컬럼 배제)
  → 시계열 Feature 계산 (build_features)
  → 공식 고장 이력 기반 Label 생성 (build_labels, positive 0건 및 결측치 fail-fast)
  → Feature Schema allowlist 검증 및 선언 순서 유지
  → 불변 NPY 및 메타데이터 원자적 발행

        ↓

[3단계: POST /train]
  → (후속 PR) NPY/메타데이터 소비 ➔ ML 모델 학습 ➔ Model Artifact 발행
```

1. **기존 번들 및 Plan/Mapping 재사용 무결성 검증**:
   - 기존 Feature Bundle 재사용 전 4개 필수 파일(`features.npy`, `labels.npy`, `feature_columns.json`, `feature_metadata.json`), 2D/1D shape, dtype, NaN/Inf 부재, `{0,1}` 값, 9대 계약 일치, SHA-256 지문 일치를 전수 검증하며 위반 시 `FEATURE_DATASET_INTEGRITY_ERROR` (422)를 반환하고 덮어쓰지 않습니다.
   - Plan과 Mapping 또한 기존 파일 재사용 전 canonical 해시 및 스키마 검증을 수행합니다.
2. **명시적 Failure 데이터셋 연결 및 9대 계약 지문**:
   - `failure_dataset_id`, `failure_dataset_version`을 요청에 필수 지정하며, telemetry와의 설비 식별 체계 호환성을 검증합니다.
   - Feature Dataset fingerprint는 9개 계약 요소의 SHA-256 해시 지문으로 확장되었습니다.
3. **Label Schema 실제 검증**:
   - `label_schema_provider.py`를 통해 요청된 Label Schema를 실제 로드하고 `prediction_task`, `horizon`, `anchor_semantic` 등의 계약을 사전 검증합니다.
4. **저장소 디렉터리 격리 및 Root Containment**:
   - 모든 식별자 및 파일 경로는 `is_relative_to(base_dir)` 검증을 거쳐 `INVALID_ARTIFACT_PATH` (422)로 경로 탈출을 원천 방어합니다.
   - `source_uri`는 `PATHS.data_dir` 및 `PATHS.data_preprocessed` 내부의 유효한 상대경로 파일만 허용하며 절대경로 및 traversal(`..`)은 `DATASET_PATH_NOT_ALLOWED` (422)로 거절됩니다.
5. **전역 매핑 캐시 비오염 원칙**:
   - `/extraction`은 데이터셋별 격리된 `MappingStore`를 사용하며 `persist=False`로 실행되어 전역 `mapping_cache.json`을 수정하지 않습니다.

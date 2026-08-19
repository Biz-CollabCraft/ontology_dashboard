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
│  ├─ extraction/             # Extraction 도메인 (Plan & Mapping 수립 및 영속화)
│  │  ├─ __init__.py
│  │  ├─ extraction_router.py # POST /extraction HTTP 엔드포인트
│  │  ├─ extraction_schema.py # ExtractionRequest, ExtractionResponse, ExtractionPlanResponse, ErrorEnvelope
│  │  ├─ extraction_service.py# 데이터셋 경로 해석, Plan 생성/검증, Mapping 생성/검증, extract_with_plan 실행
│  │  ├─ extraction_planner.py# LLM 2단계 구조 판별 및 컬럼 역할 규칙 계획기
│  │  ├─ extraction_repository.py # Extraction Plan/Mapping 버전 영속화 (내용 기반 해시 버전 및 무결성 검증)
│  │  ├─ extraction_profiler.py # Stage 0 파일 프로파일링
│  │  └─ extraction_exception.py# Extraction 도메인 예외 계층
│  └─ feature/                # Feature 도메인 (Plan/Mapping 소비, Feature·Label·NPY 생성)
│     ├─ __init__.py
│     ├─ feature_router.py    # POST /feature HTTP 엔드포인트
│     ├─ feature_schema.py    # FeatureRequest, FeatureResponse, FeatureOutputsPayload 등
│     ├─ feature_service.py   # Plan/Mapping 조회/검증, Feature 계산, Label 생성, allowlist 적용
│     ├─ feature_schema_provider.py # Feature Schema allowlist 조회 및 선언 순서 보장 검증기
│     ├─ feature_repository.py# 불변 디렉터리 기반 NPY 및 메타데이터 원자적 Staging & Publish
│     └─ feature_exception.py # Feature 도메인 예외 계층
├─ extraction/                # [Compatibility Facade] 하위 호환 re-export 제공
├─ ontology_mapping/          # 온톨로지 매핑 도메인
├─ feature/                   # Feature 엔지니어링 계산 모듈 (feature_builder, feature_label_service 등)
├─ model/                     # 모델 학습 및 Artifact 발행 도메인 (후속 /train 단계 대상)
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
└─ generator_config.py        # 시스템 전역 경로 및 환경설정 싱글톤
```

---

## 2. 도메인 API 현황

| Method | Path | 목적 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | 구현 완료 |
| POST | `/extraction` | 데이터셋 분석 및 내용 기반 해시 Extraction Plan/Mapping 수립·검증·불변 영속화 | 구현 완료 (1단계) |
| POST | `/feature` | Extraction Plan 및 Mapping 소비, Feature·Label 생성 및 NPY/메타데이터 불변 발행 | 구현 완료 (2단계) |
| POST | `/train` | 다중 머신러닝 모델 학습 및 Model Artifact 발행 | **후속 PR 대상 (미구현)** |

---

## 3. 파이프라인 단계별 경계 및 불변성 안전 원칙

```text
[1단계: POST /extraction]
  → 데이터셋 분석
  → Extraction Plan 생성·검증
  → Ontology Mapping 생성·검증
  → 내용 기반 해시(SHA-256) 버전 산출 (extraction-plan-<hash>, ontology-mapping-<hash>)
  → Plan & Mapping 불변 영속화 (models_store/cache/extraction_plans, models_store/cache/mappings)

        ↓

[2단계: POST /feature]
  → 기존 Extraction Plan 및 Ontology Mapping 무결성 검증 및 조회 (자체 매핑 생성 금지)
  → 원본 데이터 추출 (기존 label 컬럼 배제)
  → 시계열 Feature 계산 (build_features)
  → 공식 고장 이력 기반 Label 생성 (build_labels, positive 0건 fail-fast)
  → Feature Schema allowlist 검증 및 선언 순서 유지 (알파벳 정렬 금지)
  → 7개 계약 SHA-256 지문 기반 불변 NPY 및 메타데이터 원자적 발행 (feature-dataset-<fingerprint>)

        ↓

[3단계: POST /train]
  → (후속 PR) NPY/메타데이터 소비 ➔ ML 모델 학습 ➔ Model Artifact 발행
```

1. **Extraction Plan & Mapping 내용 기반 버전 (Content-Addressed Immutability)**:
   - Plan과 Mapping의 canonical JSON에 대한 SHA-256 fingerprint 앞 16자리를 실제 식별 버전(`extraction-plan-<hash>`, `ontology-mapping-<hash>`)으로 사용합니다.
   - 내용이 변경되면 새로운 버전이 생성되며, 동일한 버전의 파일은 절대 덮어쓰지 않습니다.
   - 조회 시 파일 내용의 SHA-256 해시를 재계산하여 변조/불일치 시 `*_INTEGRITY_ERROR` (422)로 즉시 거절합니다.
2. **Feature Schema allowlist 및 순서 보장**:
   - `feature_schema_version`으로 Feature Schema를 조회하고 선언된 `feature_names` allowlist에 따라 X 행렬을 구성합니다.
   - Schema에 선언된 순서를 엄격히 유지하며 알파벳 정렬을 금지합니다.
   - 메타 컬럼(`id_column`, `time_column`, `label`, `degradation_start` 등)이 allowlist에 포함된 경우 계약 위반(`FEATURE_SCHEMA_MISMATCH`)으로 거절합니다.
3. **결정론적 Feature Dataset 버전 (Contract Fingerprint)**:
   - `(dataset_id, dataset_version, extraction_plan_version, mapping_version, feature_schema_version, label_schema_version, prediction_horizon_hours)`의 canonical JSON에 대한 SHA-256 해시 기반 `feature-dataset-{fingerprint}` 식별자를 사용합니다.
   - 동일한 버전 디렉터리가 이미 존재할 때, 계약 내용이 일치하면 기존 산출물을 반환하고 불일치 시 `FEATURE_DATASET_CONFLICT` (409) 오류를 발생시킵니다 (기존 디렉터리 선삭제 `shutil.rmtree` 금지).
4. **라벨 Fail-Fast 및 기존 Label 컬럼 비신뢰 원칙**:
   - 데이터셋에 기입된 기존 `label` 컬럼을 신뢰하지 않고 공식 failure event 데이터셋을 기준으로 `[anchor - horizon, anchor)` 구간을 계산합니다.
   - 고장 이력 데이터 부재 시 `FAILURE_DATA_NOT_READY` (404), anchor/id/time 누락 시 `LABEL_ANCHOR_NOT_FOUND` (422), 라벨 값이 `{0,1}` 범위를 벗어나면 `LABEL_CONTRACT_INVALID` (422)로 즉시 실패합니다.
   - 고장 예측 구간 내 Positive 고장 샘플이 0건인 경우 `INSUFFICIENT_POSITIVE_SAMPLES` (422)로 fail-fast합니다.
5. **불변 NPY 및 메타데이터 원자적 Staging & Publish**:
   - 임시 디렉터리(`.tmp_...`) 작성 ➔ 디스크 재로드 및 교차 검증(shape, dtype, NaN/Inf 부재, {0,1} 라벨) ➔ 원자적 rename.
   - 실패 시 staging 디렉터리만 정리되고 기존 산출물은 완벽히 보존됩니다.

---

## 4. Python Import 경로

- **새로운 Canonical 경로**:
  - `from systems.generator.app.extraction.extraction_service import extract_with_plan, load_all_sources`
  - `from systems.generator.app.extraction.extraction_schema import ExtractionPlanResponse, ExtractionRequest`
  - `from systems.generator.app.feature.feature_service import FeatureService`
  - `from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse`
  - `from systems.generator.app.feature.feature_repository import FeatureRepository`
  - `from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider`
- **호환 경로 (Deprecated, 점진적 이관 예정)**:
  - `from systems.generator.extraction.extraction_service import extract_with_plan`
  - `from systems.generator.extraction.extraction_agent import build_extraction_plan`
  - `from systems.generator.generator_llm_client import ExtractionPlanResponse`

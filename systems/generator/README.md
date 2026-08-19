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
│  ├─ extraction/             # Extraction 도메인 (1단계 구현 완료)
│  │  ├─ __init__.py
│  │  ├─ extraction_router.py # POST /extraction HTTP 엔드포인트
│  │  ├─ extraction_schema.py # ExtractionRequest, ExtractionResponse, PlanResponse, ErrorEnvelope
│  │  ├─ extraction_service.py# 데이터셋 경로 해석, Plan 생성/검증, extract_with_plan 실행
│  │  ├─ extraction_planner.py# LLM 2단계 구조 판별 및 컬럼 역할 규칙 계획기
│  │  ├─ extraction_repository.py # Extraction Plan/Mapping 버전 영속화 (원자적 Staging/Publish)
│  │  ├─ extraction_profiler.py # Stage 0 파일 프로파일링
│  │  └─ extraction_exception.py# Extraction 도메인 예외 계층
│  └─ feature/                # Feature 도메인 (2단계 구현 완료)
│     ├─ __init__.py
│     ├─ feature_router.py    # POST /feature HTTP 엔드포인트
│     ├─ feature_schema.py    # FeatureRequest, FeatureResponse, FeatureOutputsPayload 등
│     ├─ feature_service.py   # Plan 조회/검증, Feature 계산, Label 생성, allowlist 적용
│     ├─ feature_repository.py# NPY 및 메타데이터 원자적 Staging & Publish
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
| POST | `/extraction` | 데이터셋 분석 및 Extraction Plan/Mapping 수립·검증·원자적 영속화 | 구현 완료 (1단계) |
| POST | `/feature` | Extraction Plan 소비, Feature·Label 생성 및 NPY/메타데이터 원자적 영속화 | 구현 완료 (2단계) |
| POST | `/train` | 다중 머신러닝 모델 학습 및 Model Artifact 발행 | **후속 PR 대상 (미구현)** |

---

## 3. 파이프라인 단계별 경계 및 안전 원칙

```text
[1단계: /extraction] ➔ Extraction Plan 발행 (Plan/Mapping 수립 및 검증 전용)
        ↓
[2단계: /feature]    ➔ Plan 소비 ➔ Feature·Label 계산 ➔ NPY/메타데이터 원자적 발행
        ↓
[3단계: /train]      ➔ (후속 PR) NPY/메타데이터 소비 ➔ ML 모델 학습 ➔ Model Artifact 발행
```

1. **Extraction Plan 필수 소비**:
   - `POST /feature`는 이미 발행된 `ExtractionPlan`을 조회하여 소비하며, Plan이 없거나 버전이 불일치할 경우 `/extraction`을 자동 실행하지 않고 `EXTRACTION_PLAN_NOT_READY` (404) 또는 `EXTRACTION_PLAN_VERSION_MISMATCH` (422)로 fail-fast합니다.
2. **시계열 Feature 및 Horizon Label 안전 규칙**:
   - 설비별(`id_column`) `groupby` 안에서만 rolling/shift/diff 연산 수행 (설비 경계 오염 차단).
   - 입력 행 순서 무관성 보장 (내부 정렬).
   - 공식 positive 구간: `[anchor - prediction_horizon, anchor)`.
   - active failure 구간: `[anchor, exclusion_end]` 행 삭제.
   - `degradation_start` 누수 컬럼 1차 및 allowlist 2차 완벽 제거.
   - `id_column`, `time_column`, `label` 등 메타 컬럼은 학습 Feature 행렬(`features.npy`)에서 배제.
3. **NPY 및 메타데이터 원자적 Staging & Publish**:
   - 임시 디렉터리(`.tmp_...`) 작성 ➔ 교차 검증(행 수 일치, 열 수 일치, NaN/Inf 부재) ➔ `os.replace` 원자적 이동.
   - 실패 시 임시 디렉터리는 즉시 정리되며 기존 정상 NPY를 보존합니다.

---

## 4. Python Import 경로

- **새로운 Canonical 경로**:
  - `from systems.generator.app.extraction.extraction_service import extract_with_plan, load_all_sources`
  - `from systems.generator.app.extraction.extraction_schema import ExtractionPlanResponse, ExtractionRequest`
  - `from systems.generator.app.feature.feature_service import FeatureService`
  - `from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse`
  - `from systems.generator.app.feature.feature_repository import FeatureRepository`
- **호환 경로 (Deprecated, 점진적 이관 예정)**:
  - `from systems.generator.extraction.extraction_service import extract_with_plan`
  - `from systems.generator.extraction.extraction_agent import build_extraction_plan`
  - `from systems.generator.generator_llm_client import ExtractionPlanResponse`

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
│  └─ extraction/             # Extraction 도메인 (1단계 구현 완료)
│     ├─ __init__.py
│     ├─ extraction_router.py # POST /extraction HTTP 엔드포인트
│     ├─ extraction_schema.py # ExtractionRequest, ExtractionResponse, PlanResponse, ErrorEnvelope
│     ├─ extraction_service.py# 데이터셋 경로 해석, Plan 생성/검증, extract_with_plan 실행
│     ├─ extraction_planner.py# LLM 2단계 구조 판별 및 컬럼 역할 규칙 계획기
│     ├─ extraction_repository.py # Extraction Plan/Mapping 버전 영속화 (원자적 Staging/Publish)
│     ├─ extraction_profiler.py # Stage 0 파일 프로파일링
│     └─ extraction_exception.py# Extraction 도메인 예외 계층
├─ extraction/                # [Compatibility Facade] 하위 호환 re-export 제공
├─ ontology_mapping/          # 온톨로지 매핑 도메인
├─ feature/                   # Feature 엔지니어링 도메인 (후속 /feature 단계 대상)
├─ model/                     # 모델 학습 및 Artifact 발행 도메인 (후속 /train 단계 대상)
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
└─ generator_config.py        # 시스템 전역 경로 및 환경설정 싱글톤
```

---

## 2. Extraction 도메인 API (1단계)

### Endpoints

- `GET /health`: Generator 데몬 헬스체크 (`{"status": "ok", "system": "generator"}`)
- `POST /extraction`: 데이터셋 분석 ➔ 컬럼 역할 및 추출 방식 결정 ➔ Plan 검증 ➔ 버전 지정 원자적 저장 ➔ 결과 반환

### 1단계 경계 및 안전 원칙

1. **Extraction Plan/Mapping 전용**:
   - `/extraction`은 Extraction Plan 수립 및 추출 유효성 검증 전용 엔드포인트입니다.
   - Feature·Label·NPY 생성은 후속 `/feature` 단계이며, 모델 학습 및 Artifact 발행은 후속 `/train` 단계입니다.
   - `/extraction` 호출이 후속 단계를 자동 실행하지 않습니다.
2. **역할 컬럼 위치 추측 절대 금지**:
   - Long-format (`tabular_row_as_attribute`)에서 `id_column`, `attribute_column`, `value_column`을 명확히 결정하지 못할 경우 위치 기반으로 추측하지 않고 `EXTRACTION_ROLE_COLUMNS_MISSING` 에러로 fail-fast합니다.
3. **원자적 저장 및 롤백**:
   - Plan 저장 실패 시 임시 파일을 정리하고 기존 정상 결과를 덮어쓰지 않습니다.

---

## 3. Python Import 경로

- **새로운 Canonical 경로**:
  - `from systems.generator.app.extraction.extraction_service import extract_with_plan, load_all_sources`
  - `from systems.generator.app.extraction.extraction_schema import ExtractionPlanResponse, ExtractionRequest`
  - `from systems.generator.app.extraction.extraction_planner import ExtractionPlanner`
  - `from systems.generator.app.extraction.extraction_repository import ExtractionRepository`
- **호환 경로 (Deprecated, 점진적 이관 예정)**:
  - `from systems.generator.extraction.extraction_service import extract_with_plan`
  - `from systems.generator.extraction.extraction_agent import build_extraction_plan`
  - `from systems.generator.generator_llm_client import ExtractionPlanResponse`

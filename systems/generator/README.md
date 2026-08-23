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
├─ ontology_mapping/          # 컬럼-온톨로지 노드 의미 매핑
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

## 2. 도메인 API 현황 및 로드맵

### 2.1 Current API (현재 구현 상태)

현재 Generator 정본 애플리케이션(`systems/generator/app/main.py`)에 실제로 구현되어 동작하는 엔드포인트입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | Current (구현 완료) |
| POST | `/preprocessing` | Observation Dataset 분석, 역할 판정 및 불변 Preprocessing Plan 수립·발행 (동기 방식) | Current (구현 및 정본 Generator App 이관 완료) |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 프로세스 Lock 제어) | Current (호환성 유지) |

### 2.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 책임 분리)을 통해 도입될 목표 API 목록입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

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

## 3. Preprocessing Plan 불변 저장 구조

- **Plan 식별**: `preprocessing_plan_id` (`pp-{UUID4}`)와 `preprocessing_plan_version` (`preprocessing-plan-{hash}`) 분리.
- **저장 디렉터리**: `models_store/cache/preprocessing_plans/{dataset_id}/{dataset_version}/`
- **불변 파일 및 포인터**: `pp-{uuid}.json` (불변 파일) 및 `latest.json` (원자적 교체 포인터).
- **동기 실행**: `/preprocessing` 라우터는 동기 함수로 구성되어 FastAPI threadpool에서 안전하게 실행됩니다.

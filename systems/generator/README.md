# Generator Domain (개요 및 목표 아키텍처)

`systems/generator`는 센서 데이터셋 분석, 추출 계획(Extraction Plan) 수립, 온톨로지 매핑, Feature/Label 빌드 및 머신러닝 모델 학습과 Model Artifact 발행을 전담하는 도메인 시스템입니다.

---

## 1. 아키텍처 구조

### 1.1 Current 구조 (현재 main 구현 상태)

현재 `main` 브랜치의 Generator는 다음 단일 레벨 모듈 및 디렉터리 구성을 유지하고 있습니다.

```text
systems/generator/
├─ generator_main.py          # 데몬 진입점 및 FastAPI 애플리케이션 (현재 /internal 제어 엔드포인트 호스팅)
├─ generator_config.py        # 전역 경로 및 설정 싱글톤
├─ extraction/                # 데이터셋 프로파일링 및 추출 계획 수립 (LLM)
├─ feature/                   # Feature 엔지니어링 계산 모듈 (feature_builder 등)
├─ model/                     # 모델 알고리즘 구현 (LightGBM, XGBoost, RandomForest) 및 Registry
├─ ontology_mapping/          # 컬럼-온톨로지 노드 의미 매핑
├─ topology/                  # 설비 간 위상 관계 추론
├─ common/                    # 공통 에이전트 및 타임스탬프 정규화 유틸리티
├─ entrypoint.py
├─ Dockerfile
└─ requirements.txt
```

### 1.2 Target 구조 (후속 목표 설계)

후속 구조 개편 작업에서는 프레임워크 비의존 공통 모듈을 최상위에 배치하고, 4대 파이프라인 단계별 use case를 `app/` 하위 도메인으로 분리할 계획입니다 (`core/` 디렉터리는 사용하지 않음).

```text
systems/generator/
├─ app/                       # [Target] FastAPI Application 및 Use Case 계층
│  ├─ main.py                 # FastAPI Application Factory (create_app)
│  ├─ dependencies.py         # 공통 의존성 주입
│  ├─ api/                    # 중앙 Router 조립
│  ├─ extraction/             # [1단계 Target] gen_data 프로토콜 로그 추출 및 Observation/Failure 분리
│  ├─ preprocessing/          # [2단계 Target] 데이터셋 분석 및 Preprocessing Plan / Ontology Mapping 수립 (기존 extraction 이전)
│  ├─ feature/                # [3단계 Target] Feature/Label/Series 빌드 및 Feature Dataset Bundle 발행
│  └─ training/               # [4단계 Target] 모델 학습, 검증, Model Artifact 발행 및 활성화
│
├─ settings.py                # [Target] 환경설정 싱글톤 (Pydantic Settings)
├─ paths.py                   # [Target] 시스템 전역 파일/디렉터리 경로 레지스트리
├─ logging.py                 # [Target] 구조화 로깅 유틸리티
├─ errors.py                  # [Target] 표준 ErrorEnvelope 및 공통 예외
├─ file_integrity.py          # [Target] SHA-256 무결성 검증 유틸리티
└─ atomic_publish.py          # [Target] 원자적 파일/디렉터리 발행 유틸리티
```

> **단방향 의존성 원칙**: 공통 기반 모듈(`systems/generator/*.py`)은 `app` 하위 모듈을 절대 import하지 않으며, `FastAPI`에 의존하지 않습니다.

---

## 2. 도메인 API 현황 및 로드맵

### 2.1 Current API (현재 main 구현 상태)

현재 `main` 브랜치에 구현되어 있는 실제 API 엔드포인트입니다.

| Method | Path | 현재 의미 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 및 시스템 식별자 확인 | Current (운영 중) |
| POST | `/internal/train` | 데몬 최초 학습 실행 (단일 프로세스 Lock 제어) | Current (운영 중) |
| POST | `/internal/retrain` | 데몬 새 버전 재학습 실행 (단일 프로세스 Lock 제어) | Current (운영 중) |

### 2.2 Target API (후속 목표 설계)

후속 구조 개편(4대 파이프라인 책임 분리)을 통해 도입될 목표 API 목록입니다 (`/ingestion`, `/observations` 같은 파일 수신 엔드포인트는 도입하지 않으며 파일 handoff 방식을 유지함).

| Method | Path | Target 의미 및 4대 파이프라인 단계 | 상태 |
|---|---|---|---|
| GET | `/health` | Generator 데몬 상태 확인 | Target (유지) |
| POST | `/extraction` | `gen_data` Layer 2 프로토콜 로그를 정제된 Observation/Failure Dataset으로 추출 (신규 1단계) | Target (후속 구현) |
| POST | `/preprocessing` | Observation Dataset을 분석하여 Preprocessing Plan 및 Ontology Mapping 발행 (신규 2단계) | Target (기존 기능 이전) |
| POST | `/feature` | Observation/Failure + Plan/Mapping을 소비하여 Feature/Label/Series 및 Feature Bundle 발행 (신규 3단계) | Target (후속 구현/정리) |
| POST | `/train` | Feature Dataset Bundle을 소비하여 전체 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target (후속 구현/정리) |
| POST | `/train/{base_model}` | Feature Dataset Bundle을 소비하여 특정 머신러닝 모델 학습 및 Model Artifact 발행 (신규 4단계) | Target (후속 구현/정리) |
| POST | `/models/{base_model}/activate/{model_version}` | 기존 발행된 불변 Model Artifact 패키지 수동 활성화 | Target (후속 구현/정리) |
| GET | `/models/{base_model}/active` | 현재 활성화된 Model Artifact 정보 조회 | Target (후속 구현/정리) |

### 2.3 Target 4대 파이프라인 전환 요약

```text
1. Extraction    : gen_data Layer 2 protocol log → Versioned Observation/Failure Dataset
2. Preprocessing : Observation Dataset → Preprocessing Plan / Ontology Mapping (기존 extraction 이전)
3. Feature       : Observation/Failure + Plan/Mapping → Feature/Label/Series & Feature Dataset Bundle
4. Training      : Feature Dataset Bundle → Immutable Model Artifact (latest.json pointer)
```

상세한 Target 아키텍처, 단계별 책임 명세, Migration 매핑 및 3단계 후속 PR 계획은 [`docs/mvp/generator-architecture-and-file-pipeline-target.md`](../../docs/mvp/generator-architecture-and-file-pipeline-target.md)를 단일 기준으로 따릅니다.

---

## 3. 기존 코드 migration 및 호환성 계획

1. **기존 파일 migration 계획**:
   - `generator_main.py` → `app/main.py`의 `create_app()` 팩토리 기반으로 migration
   - `generator_config.py` → `settings.py` 및 `paths.py` 정본 모듈로 migration
   - 기존 `extraction/` 로직 → `app/preprocessing/` 도메인으로 이전
   - 기존 `feature/`, `model/` 로직 → `app/feature/`, `app/training/` 도메인으로 이전 및 정리
2. **Compatibility Shim 계획**:
   - migration 기간 동안 기존 import 경로 및 legacy 제어 엔드포인트(`/internal/train`, `/internal/retrain`)에 대한 compatibility shim을 한시적으로 제공하되, 신규 기능 추가는 금지합니다.

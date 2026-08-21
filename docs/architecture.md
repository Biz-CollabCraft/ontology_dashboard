# 프로젝트 아키텍처 — systems/ 도메인 구조와 Artifact 계약

> 이 문서는 PR #8에서 확정한 저장소 책임 경계를 상위 계약으로 사용한다. 실제 코드 구조와 배포 경계가 이 문서와 모순되지 않도록 함께 갱신한다.

---

## 1. 저장소 수준 책임 경계

`Biz-CollabCraft/gen_data`와 `Biz-CollabCraft/ontology_dashboard`는 다음 단방향 책임 흐름을 따른다.

```text
Biz-CollabCraft/gen_data
Source Data Producer
raw / simulation / synthetic sensor data
Layer 2 protocol append-only log files
source/reference/test fixtures
seed reproducibility + source lineage
        ↓ Layer 2 protocol log contract (file handoff)
ontology_dashboard/systems/generator
Extraction (protocol log → Observation/Failure Dataset)
→ Preprocessing (Observation → Plan/Ontology Mapping)
→ Feature (Observation/Failure + Plan/Mapping → Feature/Label/Series)
→ Training (Feature Dataset → Model Artifact)
→ versioned Model Artifact (latest.json pointer)
        ↓ Model Artifact / Observation contract
ontology_dashboard/systems/backend/app/diagnosis
Runtime feature replay + Model Artifact
→ runtime inference
→ Result Artifact / Evidence / Prediction History
        ↓ Canonical Read Port
ontology_dashboard/systems/frontend / Report
AssetDetailReportViewModel (composition via read port)
```

정비 후 Closed-loop feedback은 위 단방향 학습/추론 소유권을 뒤집지 않고 별도 Runtime
Overlay handoff로 연결한다.

```text
Closed-loop MaintenanceEvent
        ↓ versioned Integration event
gen_data Runtime Overlay
target equipment snapshot + branch-local simulation clock
        ↓ continuous maintenance_replay_overlay Observation availability
ontology_dashboard/systems/backend/app/diagnosis
history requirement/readiness validation
        ├─ insufficient: wait for subsequent Observation
        └─ ready: runtime inference
        ↓
new Result Artifact / Evidence
```

Canonical/source Replay는 계속 read-only다. Runtime Overlay는 대상 설비에만 적용하는
opt-in 경로이며 전체 Replay Clock이나 Canonical 원본을 변경하지 않는다. 상세는
[`closed-loop-runtime-overlay-contract.md`](./closed-loop-runtime-overlay-contract.md)를
따른다.

### 저장소별 Source of Truth

- **`gen_data` = Source Data Producer**
  - 센서 프로토콜 레코드 생성 및 Layer 2 append-only 로그 파일(`_log.jsonl`) 생성
  - Canonical V3.1 물리·생성 기준
  - source/reference/test fixture와 seed 기반 재현성 및 source lineage 보존
  - Closed-loop Target에서 정비 대상 설비의 Runtime Overlay Snapshot과 branch-local
    Simulation Clock을 이용한 source Observation 생성
  - 과거 model/prediction/result 파일을 보존할 수 있으나 제품 운영 SoT가 아니라 reference/regression fixture로 취급한다.
- **`ontology_dashboard` = Semantic/ML + Prediction + Result Artifact/Evidence + Product**
  - **`systems/generator`**: 프로토콜 로그 검증과 파일 가공, Observation/Failure Dataset 분리, Preprocessing Plan/Mapping 수립, Feature/Label/Series 빌드 및 versioned Model Artifact 발행
  - **`systems/backend/app/diagnosis`**: Runtime feature 재현, runtime inference 및 제품 Result Artifact/Evidence/Prediction History 최종 생성
  - **`systems/frontend` / Report**: 공식 read port를 통한 ViewModel composition (gen_data 원본 파일 직접 파싱 금지)

`gen_data`를 제품 prediction 또는 Result Artifact의 운영 producer로 해석하지 않는다.

---

## 2. 전체 구조 원칙

- 실행 가능한 제품 코드는 `systems/` 하위에 격리한다. 저장소 메타데이터·CI 설정과 `docs/`, `README.md`는 루트에 둘 수 있다.
- `systems/generator`, `systems/backend`, `systems/frontend`는 배치·API·UI라는 서로 다른 **독립 실행/배포 단위**다.
- 시스템 간 Python/TypeScript 코드 direct import로 결합하지 않는다. 시스템 경계는 안정된 API 또는 versioned Artifact contract로 연결한다.
- 각 시스템 내부는 계층 우선이 아니라 도메인 우선으로 구성한다. 계층 파일은 `{도메인}_{계층}.py` 형식을 따른다.
- `systems/backend/ontology_dashboard`는 정식 compatibility architecture가 아니라 제거 대상 legacy migration source다. Migration 완료 전까지 한시적으로 존재할 수 있으나 신규 기능 또는 신규 파일 추가는 금지한다.
- `common/` 이동 기준: 애매하면 우선 사용하는 domain에 둔다. 실제로 둘 이상의 domain에서 재사용되고, 특정 domain 고유의 업무 개념이 아닌 경우에 한해 `common`으로 승격한다. 단, 둘 이상에서 사용되더라도 특정 domain이 의미를 소유하는 개념(예: `DiagnosisResult`, `MaintenanceEvent`, `EquipmentId`)은 이동하지 않고 해당 domain이 계속 소유한다.
- 물리 디렉터리 경로, sibling checkout 배치, 특정 로컬 파일명은 시스템 간 계약이 아니다.


```text
project-root/
├── docs/
├── experiments/
│   └── preventive_intervention/  # 비배포 What-if 계약·정책·실험 코드
├── README.md
└── systems/
    ├── generator/
    ├── backend/
    └── frontend/
```

### 비배포 Experiment 계층

`experiments/preventive_intervention`은 네 번째 제품 시스템이나 독립 배포 단위가 아니다. 예방조치 What-if의 버전된 계약, 합성 정책과 재현 가능한 실험 코드를 소유하는 **비배포 producer 계층**이다.

- API를 호스팅하거나 자체 데이터베이스를 소유하지 않는다.
- `systems/generator`와 `systems/backend`의 내부 구현을 직접 import하지 않는다.
- 시스템과 연결할 때는 versioned Artifact/API contract를 사용한다.
- 검증된 기능을 제품 runtime으로 승격할 때는 책임 시스템, 배포 방식과 계약 변경을 별도 architecture decision으로 확정한다.
- `contracts/schemas/preventive-what-if.schema.json`은 downstream consumer가 사용하는 공유 산출물 계약이다.

---

## 3. systems/generator — Semantic/ML Pipeline

**책임 끝점은 versioned Model Artifact publish 및 활성 버전 포인터(`latest.json`) 관리까지다.** 사용자 요청 기반 runtime inference, 제품 Result Artifact 생성, 최종 Evidence 생성은 이 시스템의 책임이 아니다.

### 상위 아키텍처 및 책임 원칙

1. **로그 생산과 파일 가공 경계**: `gen_data`는 Layer 2 프로토콜 로그 파일 생산자이며, `systems/generator`는 프로토콜 로그를 파싱·검증하여 Observation/Failure Dataset 및 Feature/Label을 생성하고 Model Artifact를 발행합니다.
2. **런타임 추론과 근거 생성 경계**: `systems/backend/app/diagnosis`는 Generator가 발행한 Observation/Feature와 Model Artifact를 기반으로 runtime feature 재현, inference, Result Artifact 및 Evidence 생성을 전담합니다.
3. **소비 경계**: Backend Report와 Frontend는 공식 read boundary를 통해서만 ViewModel을 구성하며, `gen_data` 원본 로그를 직접 파싱하지 않습니다.
4. **금지 범위**: Generator는 Product Result Artifact나 Evidence를 직접 생성하지 않습니다.

### Generator 구조 현황 (Current vs Target)

- **Current (현재 main 구현 상태)**:
  - 단일 레벨 모듈 구조 (`generator_main.py`, `generator_config.py`, `extraction/`, `feature/`, `model/`, `ontology_mapping/`, `topology/`, `common/`)
  - 제어 엔드포인트: `GET /health`, `POST /internal/train`, `POST /internal/retrain`
- **Target (후속 개편 목표 설계)**:
  - 프레임워크 비의존 공통 모듈 최상위 배치 (`settings.py`, `paths.py`, `errors.py`, `file_integrity.py`, `atomic_publish.py`)
  - 도메인별 FastAPI 계층 분리 (`app/extraction/`, `app/preprocessing/`, `app/feature/`, `app/training/`)
  - 4대 파이프라인 데이터 흐름: `Extraction` → `Preprocessing` → `Feature` → `Training`

> **상세 명세 위임**: Generator의 상세 Target 디렉터리, 파일명, API 요청/응답 필드 및 단계별 migration 계획은 목표 정본 문서인 [`docs/mvp/generator-architecture-and-file-pipeline-target.md`](./mvp/generator-architecture-and-file-pipeline-target.md)에 위임합니다.

### Generator Feature 책임

Feature engineering은 versioned Feature Contract를 생산한다. Feature Contract는 source field, ontology node, dtype, unit, transform, parameter, partition key, ordering key를 포함한다. 상세 필드와 naming 규칙은 `docs/mvp/generator-feature-label-contract.md`와 `docs/architecture-decisions/ADR-001-unified-feature-contract.md`를 따른다.

### Label 책임

학습 Label은 Model Artifact provenance의 일부다. prediction horizon, anchor semantics, exclusion policy와 label schema version을 기록한다. 상세 규칙은 `docs/mvp/generator-feature-label-contract.md` §3을 따른다.

---

## 4. Versioned Model Artifact contract

Generator와 Backend 사이의 계약은 `systems/generator/model/model_store`라는 **로컬 물리 경로**가 아니라 versioned Model Artifact의 **형식과 식별자 및 `MODEL_ARTIFACT_URI` 주입 방식**이다.

### 4.1 Model Artifact 원칙

- Model Artifact는 `systems/generator`가 발행하는 불변(immutable) 산출물 패키지다.
- `MODEL_ARTIFACT_URI` 또는 injected provider를 통해서만 Backend에 전달된다.
  Backend는 sibling 경로(`../generator/...`)나 물리 디렉터리를 정적으로 탐색하지 않는다.
- 각 `model_id` + `model_version` 조합은 재사용되지 않는다 (immutable publish).
- publish는 atomic하게 수행되며, 실패 시 부분 결과를 남기지 않고 run registry도
  갱신하지 않는다.
- 파일 무결성은 `artifact_files[*].sha256` 개별 검증으로만 판단한다.
  incompatible/corrupt Artifact를 heuristic으로 조용히 대체하지 않는다.
- 현재 공식 계약 버전은 `model-artifact-v1.0`이다. 이전 코드·문서·테스트에서
  사용된 동일 문자열은 이 계약 이전의 개발 초안이며 호환 대상이 아니다.

Manifest의 실제 필드 구조, 6개 필수 파일의 역할, `artifact_files` role 목록,
검증 규칙, publisher/consumer 책임은
`docs/mvp/model-artifact-publish-contract.md`를
단일 상세 기준으로 사용한다. 이 문서에는 Manifest JSON 구조를 복제하지 않는다.

### 4.2 디렉터리 예시

아래는 local filesystem adapter의 한 예시이며 계약으로 고정하지 않는다.

```text
model_store/
└── <model-id>/
    └── <version>/
        ├── manifest.json
        ├── model.*
        ├── feature_schema.json
        └── metrics.json
```

Backend는 sibling directory 구조를 알아서는 안 된다. 실제 위치는 `MODEL_ARTIFACT_URI` 또는 동등한 환경설정/URI로 외부 주입한다.

예시:

```text
MODEL_ARTIFACT_URI=/mnt/model-artifacts
MODEL_ARTIFACT_URI=s3://team-artifacts/pdm-models
MODEL_ARTIFACT_URI=registry://pdm/production
```

스캐폴딩 단계에서는 모든 URI scheme의 adapter를 구현하지 않아도 되지만, Backend 코드·문서·Docker 기본값이 `../generator/...` 같은 sibling 경로를 전제로 해서는 안 된다.

### 4.3 Publish/consume 규칙

- `model_version`은 immutable publish 단위로 취급한다.
- consumer는 manifest의 schema/version/checksum/compatibility를 검증한 뒤 모델을 로드한다.
- `latest` 같은 alias가 필요하더라도 실제 추론 기록에는 해석된 immutable `model_version`을 남긴다.
- publish 도중 불완전한 파일 집합을 consumer가 보지 않도록 atomic publish 또는 동등한 보장 방식을 사용한다.
- incompatible/corrupt artifact는 명시적으로 실패시키고 임의의 sibling 파일로 fallback하지 않는다.

---

## 5. systems/backend — Product Runtime

Backend는 모델을 **학습하지 않는다**. `app/diagnosis`가 versioned Model Artifact와 현재 observation을 입력으로 runtime inference를 수행하고, 제품이 실제 소비하는 **Result Artifact/Evidence를 최종 생성**한다.

### 5.1 Backend Canonical Root 및 목표 디렉터리 구조

`systems/backend/app`은 제품 Backend Python package의 **유일한 Source of Truth**다.

`systems/backend/ontology_dashboard`는 정식 compatibility architecture가 아니라 제거 대상 legacy migration source다. Migration 완료 전까지 한시적으로 존재할 수 있으나 신규 기능 또는 신규 파일 추가는 금지한다.

목표 디렉터리 구조는 다음과 같다.

```text
systems/backend/
├── app/
│   ├── common/                  # 도메인 중립적 cross-cutting 유틸리티 및 기본 예외
│   ├── infra/                   # 순수 기술 구현 (외부 I/O, DB, Storage, LLM 등)
│   │   ├── db/
│   │   ├── storage/
│   │   ├── external/
│   │   ├── llm/
│   │   ├── messaging/
│   │   └── observability/
│   ├── identity/                # IAM bounded context (User, Session, Role, Scope 등)
│   ├── project/                 # Project 메타데이터 및 라이프사이클
│   ├── equipment/               # 설비 마스터 및 설비 상태
│   ├── ontology/                # Object/Link/Action 온톨로지 레지스트리 및 인스턴스
│   ├── dataset/                 # 데이터셋 소스 및 프로젝션
│   ├── diagnosis/               # 런타임 추론 및 Result Artifact/Evidence 생성
│   ├── maintenance/             # Closed-loop 정비 조치/이벤트/결정/작업지시 (구 closed_loop)
│   ├── dashboard/               # Read-model composition 영역
│   ├── report/                  # 보고서 생성 및 내보내기
│   ├── planner/                 # 자연어 플래너
│   └── governance/              # 거버넌스 및 감사
├── migrations/
├── tests/
├── Dockerfile
└── README.md
```

### 5.2 diagnosis 책임

```text
Model Artifact
+ Current Observation
        ↓
systems/backend/app/diagnosis
runtime inference
        ↓
Result Artifact / Evidence
        ↓
API / Dashboard / Report / Frontend
```

- `MODEL_ARTIFACT_URI`로 주입된 artifact provider에서 Model Artifact 로드
- manifest compatibility / integrity 검증
- current observation에 대한 runtime inference
- 특정 asset + observation time에 대한 Result Artifact 생성
- inference 결과에 연결되는 Evidence/provenance 생성 또는 조립
- **제품 Result Artifact의 최종 producer**

Training metrics, feature importance 등 모델 개발 설명자료는 Model Artifact provenance에 포함될 수 있지만, 이를 제품 runtime Evidence와 동일 개념으로 취급하지 않는다.

### 5.3 Backend Feature 소비

Backend는 Generator 구현을 import하지 않는다. Backend가 runtime Feature를 생성해야 한다면 Model Artifact에 포함된 검증된 Feature Contract(`feature_schema.json`)와 지원 transform 집합만을 사용한다. 지원하지 않는 transform이나 `feature_schema_version` 불일치는 명시적으로 실패시킨다. 상세는 `docs/architecture-decisions/ADR-001-unified-feature-contract.md`를 따른다.

정비 후 Overlay Observation은 `restart_at`부터 새 history segment를 사용한다. Backend는
Model Artifact의 `history_requirement.json`을 충족하기 전에는 heuristic이나 silent
fallback으로 Prediction하지 않으며 `warming_up` 또는 `history_insufficient`를 명시한다.
Inference readiness는 Backend Diagnosis가 단독 판정한다. `gen_data`는 Model Artifact를
소비하지 않고 Overlay branch의 Observation을 지속 생성한다. 이력이 부족하면 Backend는
Prediction을 수행하지 않고 같은 branch의 다음 Observation을 기다린다.
첫 inference-ready Observation에서 새 Product Result/Evidence를 생성하고 이후 정상
Runtime Prediction 주기를 유지한다.

Runtime Overlay Observation은 Canonical Observation 테이블을 update하거나 같은
Canonical identity로 삽입하지 않는다. 별도 append-only Overlay 저장소와 branch-aware
read model을 사용해 대상 설비의 정비 후 예정 Canonical 행이 Overlay history에 다시
섞이지 않도록 한다.

### 5.4 Backend 도메인 및 구조 규칙

- **Domain-First 구조**: 각 도메인은 독립된 업무 단위를 형성하며, 계층 파일은 `{도메인}_{계층}.py` 형식을 따른다 (`{domain}_domain.py`, `{domain}_schema.py`, `{domain}_service.py`, `{domain}_repository.py`, `{domain}_router.py`, `{domain}_exception.py`).
  - Domain-First 계층 파일 규칙(`{domain}_{layer}.py`)은 Service, Repository, Schema, Router, Exception 등 표준 계층 파일에만 적용한다. 특정 domain 내부에서 해당 domain만을 위해 사용하는 세부 기능 모듈(예: `app/diagnosis/evidence.py`, `predictor.py`, `artifact_provider.py`, `feature_executor.py`, `model_registry.py`, `contracts.py`, `evidence_baseline.py`, `evidence_enrichment.py`)은 이 규칙의 적용 대상이 아니며 별도 naming 제한을 두지 않는다.
- **도메인 간 서비스/레포지토리 직접 참조 금지**: 도메인 간 임의 `*_service.py` 또는 `*_repository.py`/`*_adapter.py` direct import를 금지한다. 다른 도메인과의 조합이 필요하면 public port/interface 또는 application query/read-model 경유로 결합한다.
- **기술 중심 최상위 패키지 금지**: `routers/`, `adapters/`, `orchestration/`, `integrations/`, `modeling/`, `domain_packs/`, `predictive_maintenance_runtime/`, `closed_loop/` 등을 업무 package 최상위로 남기지 않는다.
- **`infra/` 구조 및 기술 격리**: `infra/{db, storage, external, llm, messaging, observability}`로 구성하며 순수 기술 구현(DB 연결, 외부 API 클라이언트, 스토리지 드라이버 등)만 포함한다. 업무 도메인 로직을 포함하거나 domain service를 import해서는 안 된다.
- **Exception 정책**:
  - 도메인 전용 예외는 각 도메인의 `{domain}_exception.py`(예: `identity_exception.py`, `diagnosis_exception.py`, `maintenance_exception.py`)에 정의한다.
  - 범도메인 공통 예외는 `common/exceptions.py`로 정의한다.
  - 도메인 서비스 레이어(`*_service.py`, domain logic)에서 `FastAPI`의 `HTTPException`을 직접 import하거나 발생시키는 것을 금지한다.
  - 흐름: 도메인 오류 발생 (`DomainException`) → Router/Presentation 레이어 또는 app exception handler에서 포착 → HTTP 응답 변환.
- **Identity vs Project 경계 구분**:
  - `identity`: IAM bounded context (User, Session, Role, Permission, Organization, ProjectMembership, WorkspaceScope, OIDC, SCIM, MFA 등 "누가 접근 가능한가").
  - `project`: Project 자체의 생성, 메타데이터, 라이프사이클 관리.
- **`closed_loop` 명칭 정리**:
  ```text
  closed-loop = architecture / use-case 워크플로 패턴 명칭
  maintenance = Backend bounded context 명칭 (app/maintenance)
  ```
  Backend 구현상의 bounded context 명칭은 `maintenance`이며, `app/maintenance`가 Recommendation, Decision, WorkOrder, MaintenanceAction, MaintenanceEvent를 소유한다.
- **Dashboard 성격**: `dashboard`는 독립 business bounded context가 아니라 여러 public query/read model을 조합하는 **application/read-model composition** 영역으로 정의한다.

### 5.5 레거시 처분과 Migration Ledger

레거시 Source가 현재 import되거나 테스트된다는 이유만으로 새 구조에 자동 이관하지
않는다. 모든 `systems/backend/ontology_dashboard` Python Source에는 `MOVE`, `SPLIT`,
`REPLACE`, `REMOVE`, `DEFER` 중 하나의 처분을 부여하고, 실제 target과 삭제 조건은
[`backend-migration-map.md`](./backend-migration-map.md)를 정본으로 관리한다.

- `MOVE`/`SPLIT`은 승인된 제품 책임과 실제 consumer가 확인된 경우에만 사용한다.
- `REPLACE`는 새 canonical 구현과 회귀 테스트가 준비된 뒤 레거시를 삭제한다.
- `DEFER`를 임의 도메인으로 이동하지 않는다.
- Phase 14에서 레거시 디렉터리를 제거하기 전에 미배정 Source, `UNDECIDED`, `DEFER`가
  모두 0건이어야 한다.

Phase 0.5의 capability disposition은 `backend-migration-map.md` §4~§5를 따른다. 이 결정은
현재 compatibility UI/API가 호출한다는 이유만으로 기능을 보존하지 않으며 다음 경계를
명시적으로 고정한다.

- 시각적 Analysis와 generic multi-store Agent는 Diagnosis/Planner로 자동 이관하지 않는다.
- Analysis/Connector Durable Worker는 Maintenance Outbox와 다른 runtime이며 제거 대상으로 본다.
- generic Platform branch/merge는 `maintenance_replay_overlay`가 아니며 `gen_data`의
  branch-local clock/Observation 생성 책임을 침범하지 않는다.
- Backend Platform MLOps와 sample pipeline은 Generator의 Feature/학습/Model Artifact 책임을
  대체하거나 중복 소유하지 않는다.
- Project 3 integration은 graph/RAG 구현을 Backend로 가져오지 않고 typed external adapter와
  실제 Ontology/Planner consumer port로만 분리한다.
- hosted demo bootstrap은 domain service가 아니라 명시적 deployment/bootstrap entrypoint로
  대체한다.

`scripts/check_backend_migration_ledger.py`는 legacy Python Source의 누락·중복, 잘못된 disposition,
`UNDECIDED`/`DEFER` 잔존을 deterministic하게 차단하고 `systems/verify_architecture.py`에서 실행된다.

Phase 0.6부터 [`backend-migration-baseline.json`](./backend-migration-baseline.json)이 현재 남아 있는
legacy Python Source와 non-legacy 영역의 static/dynamic import 및 문자열 runtime entrypoint를 정확한
경로 단위로 기록한다. `scripts/check_backend_migration_ratchet.py`는 저장소 상태와 baseline의 정확한
일치, Migration Ledger 유효성, PR base 대비 감소 전용 조건을 표준 라이브러리만으로 검증한다.

- 현재 Source/reference를 baseline에 누락하거나 이미 제거된 항목을 남길 수 없다.
- PR base에 없던 legacy Source/reference를 추가하거나 이관 완료 Source를 재생성할 수 없다.
- Migration PR은 실제 Source/reference 제거와 같은 변경에서 baseline 항목도 함께 제거한다.
- Phase 14에서 `mode`를 `strict`로 전환하고 두 목록을 모두 0건으로 만든다.
- Architecture CI는 의존성 설치 전 이 검사와 음성 fixture를 실행하며 docs-only PR에도 적용한다.


---

## 6. Model Artifact와 Result Artifact 구분

| 구분 | Model Artifact | Result Artifact |
|---|---|---|
| Producer | `systems/generator` | `systems/backend/app/diagnosis` |
| Consumer | `systems/backend/app/diagnosis` | Backend API / Dashboard / Report / Frontend |
| 생성 시점 | 학습/publish 시점 | runtime inference 시점 |
| 의미 | 학습된 모델, feature contract, metrics, version, provenance | 특정 asset + observation time에 대한 실제 inference 결과 |
| Evidence 관계 | 학습 provenance/평가 정보 포함 가능 | 제품 판단에 제시되는 runtime Evidence/provenance 포함 |

두 artifact를 같은 파일 또는 같은 책임으로 취급하지 않는다.

---

## 7. systems/frontend — Workflow/UI 중심 Consumer

Frontend는 Backend API의 안정된 contract를 소비한다. 초기 스캐폴딩에서 폴더명이 `equipment`, `diagnosis`, `report`, `dashboard`로 유사하더라도 **Backend 도메인 이름과 1:1 대응을 강제하지 않는다.**

Closed-loop에서는 Backend Domain이 상태 머신의 canonical owner다. Frontend가 role·permission·현재
상태를 조합해 상태 전이를 재구현하지 않으며, Backend가 계산한 `available_actions`를 presentation에
사용한다. 기존 Event API는 additive extension으로 유지한다. 상세 Product/API/UI 소비 계약은
[`closed-loop-product-consumption-contract.md`](./closed-loop-product-consumption-contract.md)를 따른다.

Frontend 구조는 다음 기준으로 독립적으로 진화할 수 있다.

- 사용자 workflow
- 화면 feature
- 역할별 navigation / read model
- UI 공통 컴포넌트와 cross-cutting concern

Backend의 내부 도메인 재구성은 API contract가 유지되는 한 Frontend 폴더 재구성을 강제하지 않는다.

---

## 8. 독립 실행/배포와 Artifact injection

- Generator image/process는 Model Artifact를 외부 publish location에 기록한다.
- Backend image에는 generator 소스나 sibling `model_store`가 포함되어 있다고 가정하지 않는다.
- Backend 배포 시 `MODEL_ARTIFACT_URI`와 필요한 credential/reference를 주입한다.
- 지원 가능한 provider 예시는 mounted volume, externally provisioned path, object storage, artifact registry다.
- local 개발에서는 두 프로세스가 동일한 local directory를 각자의 `MODEL_ARTIFACT_URI`로 가리킬 수 있지만, 그 상대 경로가 architecture contract가 되지는 않는다.

---

## 9. 최소 Architecture CI / 검증 기준 및 12대 목표

구조 PR과 이후 재배치 PR은 최소한 다음 기본 검증을 통과해야 한다.

1. Generator 주요 package import smoke
2. Backend FastAPI import 및 `GET /health` 200
3. Frontend dependency install 후 production build
4. Generator ↔ Backend Python direct import 금지
5. 문서가 요구하는 필수 시스템/도메인 구조 존재
6. Backend의 sibling `../generator/model/model_store` 하드코딩 부재
7. git conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`) 부재 검사
8. `git diff --check`

### Architecture CI 12대 목표 항목

Domain-First 구조 전환 및 완전 수렴을 위해 다음 12개 Architecture invariant를 검증 목표로 유지한다.

1. **Backend canonical package = `app/`**: `systems/backend/app`이 유일한 canonical package root임
2. **`ontology_dashboard/` 존재 금지**: migration 완료 후 레거시 디렉터리 완전 제거
3. **Domain-first 구조 유지**: `{domain}_{layer}.py` 구조 준수
4. **`common` → `domain` import 금지**: 공통 계층이 개별 비즈니스 도메인에 역의존 금지
5. **`domain` → 다른 domain의 `*_service`/`*_repository`/`*_adapter` 직접 import 금지**: port/interface 경유 조합
6. **domain layer → FastAPI import 금지**: 도메인 계층의 HTTP 프레임워크 결합 금지
7. **domain layer → DB/HTTP/storage 기술 라이브러리 직접 의존 금지**: 기술 구현 결합 금지
8. **`infra` → domain service import 금지**: 인프라 계층의 상위 비즈니스 로직 역의존 금지
9. **Backend → `systems.generator` direct import 금지**: 시스템 간 코드 직접 참조 금지
10. **`main.py` business logic 포함 제한**: FastAPI 초기화, lifespan, middleware, exception handler, router include, DI 조립만 유지
11. **domain exception / common exception 경계 검사**: 도메인별 `{domain}_exception.py`와 `common/exceptions.py` 책임 분리
12. **신규 top-level 기술 중심 패키지 생성 방지**: 최상위에 `routers/`, `adapters/`, `closed_loop/` 등 생성 금지

> 위 12개 항목은 Architecture invariant 전체 목록이며, 기계적으로 안정적으로 검출 가능한 항목(예: 1, 2, 4, 5, 6, 8, 9)은 `verify_architecture.py`에 정적 검사로 구현하고, 의미 판단이 필요한 항목(예: 10 `main.py` business logic 포함 제한, 11 exception ownership 경계, 12 신규 기술 중심 package 여부)은 AI/code review checklist 및 테스트로 보완한다. CI가 regex 기반 정적 검사만으로 12개 전부를 완벽 판정하려 하지 않는다.

Migration 중에는 phase-aware ratchet을 적용한다. Phase 0~13은 레거시 존재를 허용하되
신규 레거시 파일·import와 이미 이관된 경로의 회귀를 차단한다. Phase 14에서 레거시
경로와 참조 0건을 강제하고, Phase 15에서 이를 최종 strict gate로 유지한다.

현재 baseline을 기계적으로 갱신해야 하는 Migration PR에서는 다음 명령을 사용한다. 이 명령은
현 상태를 기록할 뿐 증가를 승인하지 않으며, CI가 PR base와 비교해 증가 여부를 별도로 차단한다.

```bash
python scripts/check_backend_migration_ratchet.py --write-baseline
python systems/verify_architecture.py
```

---

## 10. 후속 #9 integration 기준

PR #9의 대규모 실행 코드는 이 PR에서 이동하지 않는다. 이후 재배치 시 다음 책임으로 귀속한다.

- semantic extraction / mapping / topology / feature / training → `systems/generator`
- runtime prediction / inference / Result Artifact / Evidence → `systems/backend/app/diagnosis`
- 정비 대상 설비 Runtime Overlay Observation → `gen_data`의 opt-in Runtime Overlay
- 사용자 화면 및 report rendering → Frontend/Report consumer

재배치 과정에서도 `gen_data`의 Source Data Producer 책임과 본 문서의 Model Artifact / Result Artifact 경계를 변경하지 않는다.

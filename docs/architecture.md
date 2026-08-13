# 프로젝트 아키텍처 — systems/ 도메인 구조와 Artifact 계약

> 이 문서는 PR #8에서 확정한 저장소 책임 경계를 상위 계약으로 사용한다. 실제 코드 구조와 배포 경계가 이 문서와 모순되지 않도록 함께 갱신한다.

---

## 1. 저장소 수준 책임 경계

`Biz-CollabCraft/gen_data`와 `Biz-CollabCraft/ontology_dashboard`는 다음 단방향 책임 흐름을 따른다.

```text
Biz-CollabCraft/gen_data
Source Data Producer
raw / simulation / synthetic sensor data
Canonical V3.1 physical-generation baseline
source/reference/test fixtures
seed reproducibility + source validation
        ↓ source/reference contract
ontology_dashboard/systems/generator
extraction
→ ontology mapping
→ topology
→ feature
→ model training
→ versioned Model Artifact
        ↓ Model Artifact contract
ontology_dashboard/systems/backend/diagnosis
current observation + Model Artifact
→ runtime inference
→ Result Artifact / Evidence
        ↓ API contract
ontology_dashboard/systems/frontend / Report
Result Artifact / Evidence consumer
```

### 저장소별 Source of Truth

- **`gen_data` = Source Data Producer**
  - raw / simulation / synthetic sensor data 생성·갱신
  - Canonical V3.1 물리·생성 기준
  - source/reference/test fixture와 seed 기반 재현성
  - source package validation
  - 과거 model/prediction/result 파일을 보존할 수 있으나 제품 운영 SoT가 아니라 reference/regression fixture로 취급한다.
- **`ontology_dashboard` = Semantic/ML + Prediction + Result Artifact/Evidence + Product**
  - `systems/generator`: Semantic/ML pipeline 및 versioned Model Artifact producer
  - `systems/backend/diagnosis`: runtime inference 및 제품 Result Artifact/Evidence 최종 producer
  - API / frontend / report: 제품 결과 소비자

`gen_data`를 제품 prediction 또는 Result Artifact의 운영 producer로 해석하지 않는다.

---

## 2. 전체 구조 원칙

- 실행 가능한 제품 코드는 `systems/` 하위에 격리한다. 저장소 메타데이터·CI 설정과 `docs/`, `README.md`는 루트에 둘 수 있다.
- `systems/generator`, `systems/backend`, `systems/frontend`는 배치·API·UI라는 서로 다른 **독립 실행/배포 단위**다.
- 시스템 간 Python/TypeScript 코드 direct import로 결합하지 않는다. 시스템 경계는 안정된 API 또는 versioned Artifact contract로 연결한다.
- 각 시스템 내부는 계층 우선이 아니라 도메인 우선으로 구성한다. 계층 파일은 `{도메인}_{계층}.py` 형식을 따른다.
- `common/` 이동은 사용 개수("3개 이상" 등)로 결정하지 않는다. **도메인 의미가 없고 안정된 cross-cutting concern 또는 infrastructure/common contract인지**를 먼저 판단한다. 성급한 공용화와 서로 다른 도메인 개념의 우연한 통합을 모두 피한다.
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
- `schemas/preventive-what-if.schema.json`은 downstream consumer가 사용하는 공유 산출물 계약이다.

---

## 3. systems/generator — Semantic/ML Pipeline

**책임 끝점은 versioned Model Artifact publish까지다.** 사용자 요청 기반 runtime inference, 제품 Result Artifact 생성, 최종 Evidence 생성은 이 시스템의 책임이 아니다.

```text
systems/generator/
├── extraction/               # 1. 원본 구조 판별 → 추출 계획 (LLM) 및 추출 실행
│   ├── extraction_agent.py
│   ├── extraction_service.py
│   └── extraction_cache.py
├── ontology_mapping/         # 2. 컬럼 → 온톨로지 노드 의미 매핑
│   ├── mapping_agent.py
│   ├── mapping_service.py
│   └── mapping_cache.py
├── topology/                 # 3. 설비 간 관계(위상) 추론
│   ├── topology_agent.py
│   ├── topology_service.py
│   └── topology_cache.py
├── feature/                  # 4. Feature 생성 및 카탈로그 관리
│   ├── feature_builder.py
│   └── feature_catalog.py
├── model/                    # 5. 모델 학습 및 Registry/Store 보관
│   ├── model_training.py
│   ├── model_registry.py
│   └── model_store/          # local publish 구현 예시 (계약 상위 개념은 MODEL_ARTIFACT_URI)
├── common/                   # 도메인 중립적 공통 베이스 (agent_base, cache_base)
├── .env.example
└── requirements.txt
```

### generator 내부 파이프라인 순서

```text
Raw / Canonical Observation
  → extraction
  → ontology_mapping
  → topology
  → feature
  → model training
  → versioned Model Artifact publish
```

각 파이프라인 단계는 "판단 단위 분리" 원칙을 따른다 — 하나의 LLM 호출은 하나의 판단만 담당하며, 여러 판단을 한 프롬프트에 섞지 않는다.

`model_store/`는 local filesystem publish 구현 예시일 뿐이다. 운영 환경에서는 mounted volume, externally provisioned path, object storage, artifact registry 등으로 교체될 수 있다.

### Generator Feature 책임

Feature engineering은 versioned Feature Contract를 생산한다. Feature Contract는 source field, ontology node, dtype, unit, transform, parameter, partition key, ordering key를 포함한다. 상세 필드와 naming 규칙은 `docs/mentoring-mvp-2026-08/week2-generator-feature-label-contract.md`와 `docs/architecture-decisions/ADR-001-unified-feature-contract.md`를 따른다.

### Label 책임

학습 Label은 Model Artifact provenance의 일부다. prediction horizon, anchor semantics, exclusion policy와 label schema version을 기록한다. 상세 규칙은 `docs/mentoring-mvp-2026-08/week2-generator-feature-label-contract.md` §3을 따른다.

---

## 4. Versioned Model Artifact contract

Generator와 Backend 사이의 계약은 `systems/generator/model/model_store`라는 **로컬 물리 경로**가 아니라 versioned Model Artifact의 **형식과 식별자 및 `MODEL_ARTIFACT_URI` 주입 방식**이다.

### 4.1 필수 manifest 메타데이터

각 publish 단위는 최소한 다음 메타데이터를 제공한다.

| 필드 | 의미 |
|---|---|
| `artifact_type` | 산출물 종류. 예: `predictive_maintenance_model` |
| `artifact_schema_version` | manifest/contract schema 버전 |
| `model_id` | 논리 모델 식별자 |
| `model_version` | immutable 모델 버전 |
| `dataset_version` | 학습 데이터 버전 |
| `feature_schema_version` | 입력 feature 계약 버전 |
| `created_at` | 생성 시각 |
| `training_config` | 학습 설정 및 재현성 정보 |
| `metrics` | 평가 metric 요약 또는 metric 파일 참조 |
| `checksum` | manifest가 가리키는 핵심 artifact 무결성 값 |
| `provenance` | 소스 데이터·코드·실행 provenance |
| `compatibility` | Backend/runtime 호환 조건 |
| `artifact_files` | 모델, feature schema, metrics 등 파일 목록/참조 |

위 표는 `feature_schema_version`만 명시하므로, 실제 publish에서는 다음을 보강한다.

- `feature_schema` artifact file(`feature_schema.json`)을 `artifact_files`에 필수로 포함한다.
- label schema 또는 label contract metadata(`label_schema.json` 또는 `training_config.label_schema_version`)를 포함한다. Label Schema 전달 방식은 Artifact schema version 전환 결정과 함께 확정한다.
- prediction horizon을 `training_config` 또는 label schema에 기록한다.
- Feature 순서가 `feature_schema.json`과 학습 시점의 `feature_cols` 순서와 일치함을 보장한다.
- training/runtime compatibility 범위를 `compatibility` 필드에 명시한다.

> ADR-001/002는 현재 `Proposed` 상태다. 해당 목표 계약은 승인 및 관련 구현 PR 적용 전까지 현행 구현 계약을 대체하거나 자동 merge blocker로 사용하지 않는다.

상세 스키마는 `docs/mentoring-mvp-2026-08/week2-model-artifact-publish-contract.md`를 따른다.

변경 영향:

- Backend artifact provider의 검증 범위가 늘어날 수 있음
- 기존 Model Artifact는 새 계약 버전과 호환되지 않을 수 있음
- artifact schema version bump가 필요할 수 있음

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

Backend는 모델을 **학습하지 않는다**. `diagnosis`가 versioned Model Artifact와 현재 observation을 입력으로 runtime inference를 수행하고, 제품이 실제 소비하는 **Result Artifact/Evidence를 최종 생성**한다.

```text
Model Artifact
+ Current Observation
        ↓
systems/backend/diagnosis
runtime inference
        ↓
Result Artifact / Evidence
        ↓
API / Dashboard / Report / Frontend
```

### diagnosis 책임

- `MODEL_ARTIFACT_URI`로 주입된 artifact provider에서 Model Artifact 로드
- manifest compatibility / integrity 검증
- current observation에 대한 runtime inference
- 특정 asset + observation time에 대한 Result Artifact 생성
- inference 결과에 연결되는 Evidence/provenance 생성 또는 조립
- **제품 Result Artifact의 최종 producer**

Training metrics, feature importance 등 모델 개발 설명자료는 Model Artifact provenance에 포함될 수 있지만, 이를 제품 runtime Evidence와 동일 개념으로 취급하지 않는다.

### Backend Feature 소비

Backend는 Generator 구현을 import하지 않는다. Backend가 runtime Feature를 생성해야 한다면 Model Artifact에 포함된 검증된 Feature Contract(`feature_schema.json`)와 지원 transform 집합만을 사용한다. 지원하지 않는 transform이나 `feature_schema_version` 불일치는 명시적으로 실패시킨다. 상세는 `docs/architecture-decisions/ADR-001-unified-feature-contract.md`를 따른다.

### Backend domain dependency rule

- 도메인 간 임의 `*_service.py` direct import를 금지한다.
- 다른 도메인의 repository/adapter 구현을 직접 참조하지 않는다.
- dependency cycle을 금지한다.
- 조합이 필요하면 public application/query/port interface를 사용한다.
- `dashboard`는 독립 business domain이라기보다 여러 public query/read model을 조합하는 **application/read-model composition** 영역으로 정의한다.
- 실제 구현이 아직 placeholder인 경우에도 docstring과 새 코드는 위 방향을 위반하지 않는다.

---

## 6. Model Artifact와 Result Artifact 구분

| 구분 | Model Artifact | Result Artifact |
|---|---|---|
| Producer | `systems/generator` | `systems/backend/diagnosis` |
| Consumer | `systems/backend/diagnosis` | Backend API / Dashboard / Report / Frontend |
| 생성 시점 | 학습/publish 시점 | runtime inference 시점 |
| 의미 | 학습된 모델, feature contract, metrics, version, provenance | 특정 asset + observation time에 대한 실제 inference 결과 |
| Evidence 관계 | 학습 provenance/평가 정보 포함 가능 | 제품 판단에 제시되는 runtime Evidence/provenance 포함 |

두 artifact를 같은 파일 또는 같은 책임으로 취급하지 않는다.

---

## 7. systems/frontend — Workflow/UI 중심 Consumer

Frontend는 Backend API의 안정된 contract를 소비한다. 초기 스캐폴딩에서 폴더명이 `equipment`, `diagnosis`, `report`, `dashboard`로 유사하더라도 **Backend 도메인 이름과 1:1 대응을 강제하지 않는다.**

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

## 9. 최소 Architecture CI / 검증 기준

구조 PR과 이후 재배치 PR은 최소한 다음을 검증한다.

1. Generator 주요 package import smoke
2. Backend FastAPI import 및 `GET /health` 200
3. Frontend dependency install 후 production build
4. Generator ↔ Backend Python direct import 금지
5. 문서가 요구하는 필수 시스템/도메인 구조 존재
6. Backend의 sibling `../generator/model/model_store` 하드코딩 부재
7. git conflict marker (`<<<<<<<`, `=======`, `>>>>>>>`) 부재 검사
8. `git diff --check`

이 저장소의 `systems/verify_architecture.py`는 4~7번의 정적 구조 검사(git conflict marker 검사 포함)를 담당한다. 런타임 import/build 검증은 각 시스템의 dependency 환경에서 별도로 실행한다.

---

## 10. 후속 #9 integration 기준

PR #9의 대규모 실행 코드는 이 PR에서 이동하지 않는다. 이후 재배치 시 다음 책임으로 귀속한다.

- semantic extraction / mapping / topology / feature / training → `systems/generator`
- runtime prediction / inference / Result Artifact / Evidence → `systems/backend/diagnosis`
- 사용자 화면 및 report rendering → Frontend/Report consumer

재배치 과정에서도 `gen_data`의 Source Data Producer 책임과 본 문서의 Model Artifact / Result Artifact 경계를 변경하지 않는다.

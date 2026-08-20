# 온톨로지 기반 설비 예지보전 플랫폼 (`ontology_dashboard`)

제조 설비의 센서·정비·예측 데이터를 온톨로지 기반으로 연결하고, 같은 분석 결과를
Dashboard, Operations, Executive Brief, API에서 일관되게 활용하기 위한 팀 프로젝트입니다.

이 저장소는 단순 예측 모델 저장소가 아니라 `Biz-CollabCraft/gen_data`가 생성한 source data를
소비해 Feature/Model Artifact, runtime inference, Product Result Artifact/Evidence, 업무 Action,
Frontend와 Report까지 연결하는 제품 실행 저장소입니다.

## 1. 프로젝트 목표

핵심 목표는 "모델을 만드는 것"에서 끝나지 않고, 예측 결과가 실제 제품 흐름으로 이어지게 하는 것입니다.

```text
Canonical V3.1 source data
        ↓
Feature / Label / Model Training
        ↓
Model Artifact
        ↓
Backend Runtime Inference
        ↓
Product Result Artifact / Evidence
        ↓
Decision / Recommended Action / Maintenance Action
        ↓
Dashboard / Operations / Executive Brief
```

최종적으로 하나의 설비 위험 Event가 다음 흐름으로 연결되는 것을 목표로 합니다.

```text
위험 탐지
→ 근거 확인
→ 대응 판단
→ 정비 Action
→ Ontology 상태 반영
→ 보고서 생성
```

## 2. 시스템 책임 흐름

```text
Biz-CollabCraft/gen_data
Source Data Producer / Canonical V3.1 source-reference baseline
        ↓
systems/generator
extraction → ontology mapping → topology → feature → training/evaluation
→ immutable versioned Model Artifact
        ↓ MODEL_ARTIFACT_URI
systems/backend/app/diagnosis
current observation + Model Artifact
→ runtime inference → Product Result Artifact / Evidence
        ↓
Backend Product API
        ↓
Ontology Decision / Action / Maintenance State
        ↓
systems/frontend / Executive Brief / LLM Report
```

- `Biz-CollabCraft/gen_data`: raw/simulation/synthetic sensor data, Canonical V3.1 생성 기준, source/reference fixture와 재현성의 Source of Truth
- `systems/generator`: Extraction, Feature/Label, Model Training/Evaluation, versioned Model Artifact producer
- `systems/backend/app/diagnosis`: Model Artifact loader, runtime inference, Product Result Artifact/Evidence 최종 producer
- Backend Product API: Frontend, Report, Closed-loop가 공통으로 소비하는 제품 경계
- Ontology Closed-loop: Decision, Recommended Action, Maintenance Action과 설비 상태 연결
- `systems/frontend`: Overview, Objects, Operations, Executive Brief와 최종 사용자 경험

`gen_data`에 보존된 기존 model/prediction/result 파일은 compatibility/regression/migration fixture이며
제품 runtime의 운영 최신 결과로 직접 사용하지 않습니다.

## 3. 공식 제품 화면

### Overview

전체 설비의 정상·주의·경고·위험 상태와 주요 위험 설비를 빠르게 확인하는 첫 화면입니다.

### Objects

선택한 설비의 센서, 추세, failure probability, top factor, Evidence와 provenance를 확인합니다.

### Operations

Risk Event를 기준으로 Evidence, Decision, Recommended Action, Maintenance Action, Activity를 연결합니다.

### Executive Brief

동일한 Product Result/Evidence와 업무 Action을 관리자·임원 관점의 보고서로 표현합니다.
먼저 deterministic/static report를 보장하고, 그 위에 LLM을 표현 계층으로 연결합니다.

```text
Structured Data = Truth
LLM = Expression Layer
```

LLM이 실패해도 정적 보고서는 항상 생성될 수 있어야 합니다.

## 4. 팀 최종 역할 분배

각 담당자는 특정 기능 하나만 구현하고 끝나는 것이 아니라, 프로젝트 종료까지 자기 전문 축의 계약·구현·통합·검증을 계속 책임집니다.

| 사람 | 프로젝트 전체 역할 | 최종 책임 | 주요 산출물이 넘어가는 곳 |
|---|---|---|---|
| **성민 (`smmini`)** | **ML Lifecycle & Contract Engineering** | Feature/Label, Training, Model Artifact, 모델 버전·평가·재현성·Runtime compatibility | → **호범** Runtime, → **우수** CI/Report provenance |
| **호범 (`enjoylonelines`)** | **Backend Intelligence & Dynamic Reporting** | Runtime Inference, Product Result/Evidence, Dynamic Report grounding·내용·검증 규칙 | → **광우** Closed-loop, → **우수** Product/LLM runtime |
| **광우 (`KOR-GANG`)** | **Ontology Operations & Closed-loop** | RiskEvent, Recommendation, Decision, Action, Maintenance, Ontology state와 업무 feedback loop | → **호범** Report context, → **우수** Product surface |
| **우수 (`oosuhada`)** | **Product AI & Integration** | Product/Report Backend, LLM Runtime Integration, Frontend·Visualization, CI·E2E, Deployment·Release | → **전체 팀** Acceptance/Release, → **최종 사용자** |

동적 보고서는 **호범이 Grounding/Prompt/내용·검증 규칙의 feature owner**, 우수가 **실제 LLM provider runtime과 Report API/UI 통합 owner**로 역할을 분리합니다. Static Executive Brief는 LLM과 독립적으로 우수가 Product/Report 계층에서 보장합니다.

각 Step에서 네 사람이 맡는 세부 책임, 인계 산출물, 완료 조건은
**[최종 역할 분배 및 Step별 실행 계획](./docs/final_team_role_and_step_plan.md)**을 기준으로 합니다.

## 5. 저장소 구조

```text
systems/
├── generator/                 # extraction / feature / label / training / Model Artifact publish
├── backend/                   # FastAPI application + diagnosis runtime + migrations
│   ├── ontology_dashboard/    # 제품 API application package
│   └── app/diagnosis/         # Model Artifact load / inference / Result Artifact / Evidence
└── frontend/                  # React + Vite 제품 Frontend

contracts/                     # 시스템 간 공유 계약의 목표 위치
docs/                          # 아키텍처, 요구사항, 팀 실행 계획, 구현 기록
ml/                            # 이전 ML import/CLI compatibility adapter
```

시스템 경계는 direct Python import 대신 versioned Artifact 또는 Product API 계약으로 연결합니다.
Backend는 Generator의 물리 `model_store` 경로나 Python 구현에 직접 의존하지 않습니다.

## 6. 로컬 실행 및 검증

Python 3.11+와 프로젝트 Frontend가 요구하는 Node.js 환경을 사용합니다.

전체 로컬 실행:

```bash
bash scripts/run_local.sh
```

Architecture 검증:

```bash
python3 systems/verify_architecture.py
```

Backend:

```bash
cd systems/backend
pip install -e ../../ml -e '.[dev]'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd systems/frontend
npm ci
npm test
npm run build
```

운영/통합 runtime에서는 `.env.example`을 참고해 `MODEL_ARTIFACT_URI`와 데이터베이스 등
필요한 runtime 설정을 주입합니다.

## 7. CI와 품질 기준

현재 프로젝트는 다음 계층을 자동 검증 대상으로 확장하고 있습니다.

- Architecture boundary
- Generator import / contract safety
- Feature / Label
- Model Artifact publish / schema validation
- Backend Artifact load / Product Result / Evidence
- Closed-loop Action API
- Frontend unit / production build
- Playwright E2E
- Docker runtime smoke

CI의 목적은 다른 담당자의 구현을 대신 수정하는 것이 아니라, 잘못된 구현이 `main`에 들어오기 전에
경계와 계약 위반을 자동으로 발견하는 것입니다.

## 8. 배포 구조

팀 공유 및 발표 환경은 다음 구조를 사용합니다.

```text
PR / branch
  ↓
GitHub Actions
  ├─ Frontend unit/build
  ├─ Playwright E2E
  └─ Backend / architecture checks
        ↓ main + architecture green
Mac mini release watcher
        ↓ outbound pull
Mac mini
  ├─ Frontend :8120
  ├─ Backend  :8110
  └─ Cloudflare Tunnel → https://ontology.oosu.dev/
```

- GitHub Actions: PR/frontend CI와 main 검증을 담당하며 Preview 배포를 생성하지 않습니다.
- Mac mini release watcher: `main` SHA의 `architecture` CI 성공을 확인한 뒤 검증된 SHA만 pull합니다.
- Mac mini: 실제 제품 Frontend/Backend runtime 및 단일 공개 진입점을 담당합니다.
- Cloudflare Tunnel: `https://ontology.oosu.dev/`을 Mac mini Frontend로 연결합니다.
- Model Artifact: 사전에 학습·검증한 Artifact를 영속 위치에 발행하고 Mac mini Backend에
  `MODEL_ARTIFACT_URI`로 주입합니다. Runtime 컨테이너 내부 파일시스템을 Artifact 정본으로 사용하지 않습니다.

자세한 기준은 [Mac mini demo deployment baseline](./docs/deployment/free-demo-stack.md)을 참고합니다.

## 9. 주요 문서

- [최종 역할 분배 및 Step별 실행 계획](./docs/final_team_role_and_step_plan.md)
- [프로젝트 문서 인덱스](./docs/README.md)
- [시스템 아키텍처](./docs/architecture.md)
- [Architecture Decision Records](./docs/architecture-decisions/README.md)
- [Shared Contracts](./contracts/README.md)
- [MVP / Product documentation](./docs/mvp/README.md)
- [MVP 요구사항](./docs/mvp/requirements-specification.md)
- [Generator Feature/Label 계약](./docs/mvp/generator-feature-label-contract.md)
- [Model Artifact Publish 계약](./docs/mvp/model-artifact-publish-contract.md)
- [Runtime Ownership](./docs/mvp/runtime-ownership-integration.md)

현재 제품/MVP 계약은 `docs/mvp/` 바로 아래에서 관리하고, 2026년 8월 Week 2의
역할 분담·이관·provenance 기록은 `docs/mvp/history/2026-08-week2/`에 보존합니다.

## 10. 최종 완료 정의

프로젝트 완료 기준은 각 팀원의 PR merge가 아니라 다음 전체 흐름이 공개 환경에서 재현되는 것입니다.

```text
Canonical V3.1
→ Feature / Label
→ Model Training
→ Model Artifact
→ Backend Runtime Inference
→ Product Result / Evidence
→ Recommended Action / Manager Decision
→ Maintenance Action / Event
→ Ontology State
→ 새로운 Observation / Prediction
→ Dashboard
→ Executive Brief
→ LLM Dynamic Report
```

이 흐름이 CI, E2E와 Mac mini 공개 배포 환경에서 일관되게 동작하는 것을 최종 목표로 합니다.

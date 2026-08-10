# ontology_dashboard

온톨로지 기반 설비 예지보전(PdM) 및 실시간 대시보드 저장소입니다.

> Week 2 실행 기준: 프론트엔드·백엔드 MVP 실행 소스는
> `oosuhada/agentic-ontology-dashboard`의
> `feature/predictive-maintenance-adaptive-modeling` 브랜치 커밋
> `37c1251b46cb80f793d782088849b4b02d9cc295`를 기준으로 팀 저장소에
> 이관했습니다. 이후 팀 단위 변경은 이 저장소를 기준으로 진행합니다.

---

## 1. 시스템 책임 개요

PR #8의 저장소 책임과 PR #10의 시스템 아키텍처를 실행 코드에 적용한다.

```text
Biz-CollabCraft/gen_data
Source Data Producer / Canonical V3.1 source-reference baseline
        ↓
systems/generator
semantic extraction → mapping → topology → feature → training/evaluation
→ versioned Model Artifact
        ↓ MODEL_ARTIFACT_URI
systems/backend/diagnosis
current observation + Model Artifact
→ runtime inference → Product Result Artifact / Evidence
        ↓
api/ FastAPI → web/ React / Report
```

### 핵심 연동 원칙
1. `gen_data`는 raw/simulation/synthetic source와 Canonical V3.1 생성·재현성의 Source of Truth다.
2. `systems/generator`는 versioned Model Artifact를 publish하고 runtime inference를 수행하지 않는다.
3. `systems/backend/diagnosis`는 주입된 Model Artifact로 runtime inference를 수행하고 Product Result Artifact/Evidence를 최종 생성한다.
4. Backend는 generator 내부 Python 코드나 sibling `model_store` 경로를 직접 참조하지 않는다.
5. `gen_data`의 기존 prediction/result/model output은 compatibility/regression/migration fixture이며 제품 runtime SoT가 아니다.

---

## 2. 개발 및 가이드라인 안내

프로젝트에 기여하거나 코드를 작성하기 전, 반드시 다음 운영 매뉴얼 및 개발 표준 문서를 참조하십시오:

- 에이전트 운영 매뉴얼: [.agents/AGENTS.md](file:///.agents/AGENTS.md)
- 시스템 아키텍처: [.agents/project/architecture.md](file:///.agents/project/architecture.md)
- 코딩 및 주석 표준: `.agents/standards/` 참조

## 3. 프로젝트 문서

- [문서 인덱스](./docs/README.md)
- [2026년 8월 멘토링 MVP 문서](./docs/mentoring-mvp-2026-08/README.md)
- [Week 2 MVP 실행 소스 이관 기록](./docs/mentoring-mvp-2026-08/week2-frontend-implementation-import.md)
- [Week 2 실행 코드 책임 재배치 기록](./docs/mentoring-mvp-2026-08/week2-runtime-ownership-integration.md)

## 4. 실행 소스 구조

```text
systems/generator/             Semantic/ML + Model Artifact producer
systems/backend/diagnosis/    Runtime inference + Product Result Artifact/Evidence producer
web/                           React + Vite 프론트엔드와 MVP 화면 (PR #9 migration host)
api/                           FastAPI API와 이벤트·리포트 consumer/composition (PR #9 migration host)
ml/                            기존 import/CLI compatibility adapter
schemas/      API·Result Artifact·Evidence 계약 스키마
scripts/      로컬 실행·데이터 적재·검증 스크립트
tests/        백엔드 및 계약 테스트
infra/        Docker Compose 등 로컬 인프라
data/         실행용 소규모 fixture/manifest
```

Canonical V3.1 원본·생성 코드와 source/reference fixture는 `Biz-CollabCraft/gen_data`가 소유한다. 과거 대용량 Result Artifact는 regression fixture로 보존될 수 있지만 운영 Product Result Artifact는 `systems/backend/diagnosis`가 생성한다.

## 5. 로컬 실행

Node.js 22.13+와 Python 3.11+를 기준으로 합니다.

```bash
cd web
npm ci
npm run build
```

전체 로컬 실행은 루트에서 다음 스크립트를 사용합니다.

```bash
bash scripts/run_local.sh
```

환경값은 `.env.example`을 기준으로 로컬 `.env`를 구성하고, credential과
실제 secret은 Git에 커밋하지 않습니다.

운영/통합 runtime에서는 `MODEL_ARTIFACT_URI`에 Generator가 publish한 immutable Model Artifact 위치를 주입한다. Week 2 데모의 deterministic heuristic fallback은 로컬 호환 용도이며 `ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=0`으로 비활성화할 수 있다.

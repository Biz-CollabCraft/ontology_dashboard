# ontology_dashboard

CodeMap 프로젝트의 온톨로지 기반 설비 예지보전(PdM) 및 실시간 대시보드 저장소입니다.

> Week 2 실행 기준: 프론트엔드·백엔드 MVP 실행 소스는
> `oosuhada/agentic-ontology-dashboard`의
> `feature/predictive-maintenance-adaptive-modeling` 브랜치 커밋
> `37c1251b46cb80f793d782088849b4b02d9cc295`를 기준으로 팀 저장소에
> 이관했습니다. 이후 팀 단위 변경은 이 저장소를 기준으로 진행합니다.

---

## 1. 시스템 구조 개요

본 프로젝트는 4개의 독립된 시스템으로 구동되며, 파일 매개 방식을 통해 연동됩니다.

```text
USER
 ↕
Front (React)
 ↕
Back (FastAPI)
 ↑ file read
Result (json)
 ↑ file write
┌───────────────────────┐
│      Auto PdM         │
│         ↑             │
│    센서 데이터(file)   │
└───────────────────────┘
         ↑
  Azure PdM 데이터 증강기   → 별도의 repo로 분리
```

### 핵심 연동 원칙
1. **Back ↔ Auto PdM**: 직접 네트워크 통신 없이 `Result (json)` 파일로만 연동합니다.
2. **Auto PdM ↔ Augmenter**: `센서 데이터(file)` 갱신을 통해 단방향으로 연동합니다.

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

## 4. 실행 소스 구조

```text
web/          React + Vite 프론트엔드와 MVP 화면
api/          FastAPI 백엔드와 예측·이벤트·리포트 API
ml/           모델/예측 런타임 보조 패키지
schemas/      API·Result Artifact·Evidence 계약 스키마
scripts/      로컬 실행·데이터 적재·검증 스크립트
tests/        백엔드 및 계약 테스트
infra/        Docker Compose 등 로컬 인프라
data/         실행용 소규모 fixture/manifest
```

Canonical V3.1 원본·생성 코드·대용량 Result Artifact는
`Biz-CollabCraft/gen_data`를 기준 저장소로 분리합니다.

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

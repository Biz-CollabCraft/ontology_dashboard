# 온톨로지 기반 설비 예지보전 플랫폼 (ontology_dashboard)

`Biz-CollabCraft/gen_data`의 source data를 받아 Semantic/ML 처리, runtime inference, Result Artifact/Evidence, API와 UI를 제공하는 팀 저장소입니다.

PR #8의 저장소 책임과 PR #10의 시스템 아키텍처를 상위 기준으로 사용하며, PR #9는 기존 Week 2 MVP 실행 코드를 이 구조로 수렴시키는 통합 단계입니다.

## 1. 책임 흐름

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
API / Dashboard / Report / Frontend
```

- `gen_data`: raw/simulation/synthetic sensor data, Canonical V3.1 물리·생성 기준, source/reference/test fixture와 seed 재현성의 Source of Truth
- `systems/generator`: Semantic/ML pipeline과 versioned Model Artifact producer
- `systems/backend/app/diagnosis`: runtime inference와 Product Result Artifact/Evidence 최종 producer
- API / Frontend / Report: Result Artifact/Evidence consumer

`gen_data`의 기존 model contract, prediction snapshot/factor/timeline, result artifact는 compatibility/regression/migration fixture이며 제품 runtime의 운영 SoT가 아닙니다.

Generator와 Backend 사이의 계약은 sibling `model_store` 경로가 아니라 versioned Model Artifact manifest이며 실제 artifact 위치는 `MODEL_ARTIFACT_URI`로 주입합니다. Backend는 generator Python 구현이나 `../generator/...` 경로를 직접 참조하지 않습니다.

## 2. PR #10 시스템 구조와 PR #9 이관 구조

```text
systems/
├── generator/                 # semantic/feature/training + Model Artifact publish
├── backend/app/diagnosis/     # runtime inference + Result Artifact/Evidence
└── frontend/                  # PR #10 frontend scaffold

api/                           # PR #9 기존 FastAPI MVP 실행 host / compatibility composition
web/                           # PR #9 기존 React MVP 실행 host
ml/                            # 이전 ML import/CLI compatibility adapter
```

PR #9의 기존 `api/`와 `web/`은 Week 2 MVP를 깨지 않기 위해 이번 통합에서 즉시 대량 이동하지 않습니다. 대신 실제 semantic mapping, feature materialization, model training은 `systems/generator`로, runtime scoring/Evidence는 `systems/backend/app/diagnosis`로 옮겼습니다. `api/ontology_dashboard/modeling`에는 기존 ML Validator/workbench 계약을 보존하는 compatibility port만 남습니다.

Frontend는 backend domain 폴더명과 1:1로 맞추지 않고 Dashboard, Report, Evidence, Decision, Activity 등 사용자 workflow 단위 구조를 유지할 수 있습니다.

## 3. Week 2 MVP 실행

Node.js 22.13+와 Python 3.11+를 기준으로 합니다.

```bash
bash scripts/run_local.sh
```

프론트엔드만 검증하려면:

```bash
cd web
npm ci
npm test
npm run build
```

운영/통합 runtime에서는 `.env.example`을 참고해 `MODEL_ARTIFACT_URI`를 주입합니다. Week 2 deterministic heuristic fallback은 로컬 호환 용도이며 `ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=0`으로 비활성화할 수 있습니다.

PR #10의 독립 scaffold 자체는 다음 경로에서 확인할 수 있습니다.

```bash
python3 systems/verify_architecture.py

cd systems/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

cd ../frontend
npm install
npm run build
```

## 4. 문서

- [시스템 아키텍처](./docs/architecture.md)
- [문서 인덱스](./docs/README.md)
- [2026년 8월 멘토링 MVP 문서](./docs/mentoring-mvp-2026-08/README.md)
- [Week 2 MVP 실행 소스 이관 기록](./docs/mentoring-mvp-2026-08/week2-frontend-implementation-import.md)
- [Week 2 실행 코드 책임 재배치 기록](./docs/mentoring-mvp-2026-08/week2-runtime-ownership-integration.md)

Canonical V3.1 원본·생성 코드와 source/reference fixture는 `Biz-CollabCraft/gen_data`가 소유합니다. 이 저장소는 source를 소비해 semantic/model artifact와 제품 runtime 결과를 생성합니다.

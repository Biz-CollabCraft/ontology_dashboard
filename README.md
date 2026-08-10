# 온톨로지 기반 설비 예지보전 플랫폼 (ontology_dashboard)

본 프로젝트는 `Biz-CollabCraft/gen_data`가 제공하는 raw/simulation/Canonical source data를 받아 Semantic/ML 파이프라인, runtime inference, Result Artifact/Evidence, API 및 UI를 제공하는 설비 예지보전 플랫폼입니다.

---

## 1. 프로젝트 최상위 구조

`docs/architecture.md` (2026-08-08 확정본) 기준에 따라 실행 가능한 모든 코드는 `systems/` 하위 세 개의 대등한 시스템으로 격리되어 있습니다.

```text
ontology_dashboard/
├── docs/                  ← 팀 공유 지식 문서 (docs/architecture.md 포함)
├── README.md              ← 프로젝트 개요, 실행 방법 (본 문서)
└── systems/                ← 실행 가능한 코드 격리 그루핑 디렉토리
    ├── generator/          ← semantic processing, feature/model training, versioned Model Artifact publish
    ├── backend/            ← FastAPI, runtime inference, Result Artifact/Evidence 최종 생성
    └── frontend/           ← React 기반 실시간 대시보드 및 리포트 UI
```

---

## 2. 3대 대등 시스템 개요

| 시스템 | 담당 역할 | 주요 기술 스택 |
| --- | --- | --- |
| **`systems/generator`** | extraction, ontology mapping, topology, Feature 연산, 모델 학습 및 **versioned Model Artifact publish** | Python 3.11, pandas, scikit-learn, LightGBM, XGBoost |
| **`systems/backend`** | 주입된 Model Artifact + current observation으로 runtime inference를 수행하고 **Result Artifact/Evidence를 최종 생성**, REST API 제공 | FastAPI, Uvicorn, Pydantic |
| **`systems/frontend`** | Backend API가 제공하는 Result Artifact/Evidence를 사용자 workflow와 화면 feature 기준으로 소비 | React 18, TypeScript, Vite |

상위 데이터 책임은 다음과 같이 분리합니다.

```text
Biz-CollabCraft/gen_data
Source Data Producer / Canonical V3.1 source-reference baseline
        ↓
systems/generator
Semantic/ML → versioned Model Artifact
        ↓
systems/backend/diagnosis
runtime inference → Result Artifact / Evidence
        ↓
API / Frontend / Report
```

Generator와 Backend 사이의 계약은 sibling `model_store` 경로가 아니라 versioned Model Artifact contract입니다. 실제 artifact 위치는 `MODEL_ARTIFACT_URI`로 주입합니다.

---

## 3. 실행 방법 (Quick Start)

### 1) Backend (FastAPI) 기동
```bash
cd systems/backend
pip install -r requirements.txt
export MODEL_ARTIFACT_URI=/absolute/or/mounted/model-artifacts
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 헬스체크 확인: GET http://localhost:8000/health
```

### 2) Generator (오프라인 파이프라인) 실행
```bash
cd systems/generator
pip install -r requirements.txt
export MODEL_ARTIFACT_URI=./model/model_store
# 모듈별 자가테스트 실행 예시
python extraction/extraction_agent.py
```

### 3) Frontend (React) 기동
```bash
cd systems/frontend
npm install
npm run dev
# 대시보드 화면 확인: http://localhost:3000
```

---

## 4. 팀 구성원 및 역할

- **Platform & Pipeline Lead**: `systems/generator` Semantic/ML 파이프라인 및 versioned Model Artifact 구축
- **Backend Developer**: `systems/backend` FastAPI, runtime inference, Result Artifact/Evidence 생성 구현
- **Frontend Developer**: `systems/frontend` React 대시보드 UI 개발

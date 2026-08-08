# CodeMap 온톨로지 기반 설비 예지보전 플랫폼

본 프로젝트는 온톨로지(Ontology) 기반 설비 센서 데이터 재가공, 판단 Agent 파이프라인, 실시간 진단/추론 백엔드 및 대시보드 프론트엔드를 제공하는 설비 예지보전 플랫폼입니다.

---

## 1. 프로젝트 최상위 구조

`docs/architecture.md` (2026-08-08 확정본) 기준에 따라 실행 가능한 모든 코드는 `systems/` 하위 세 개의 대등한 시스템으로 격리되어 있습니다.

```text
ontology_dashboard/
├── .agents/              ← 에이전트 작업 규칙 및 설계 지침
├── docs/                  ← 팀 공유 지식 문서 (docs/architecture.md 포함)
├── README.md              ← 프로젝트 개요, 실행 방법 (본 문서)
└── systems/                ← 실행 가능한 코드 격리 그루핑 디렉토리
    ├── generator/          ← 데이터 재가공, 판단(LLM), 모델 학습 및 model_store 보관 (배치/오프라인)
    ├── backend/            ← FastAPI 기반 사용자 요청 응답, 실시간 추론 및 리포트 API
    └── frontend/           ← React 기반 실시간 대시보드 및 리포트 UI
```

---

## 2. 3대 대등 시스템 개요

| 시스템 | 담당 역할 | 주요 기술 스택 |
| --- | --- | --- |
| **`systems/generator`** | 원본 데이터 파싱, 판단 Agent(LLM), 위상 추론, Feature 연산, 모델 오프라인 배치 학습 및 `model_store/` 보관 | Python 3.11, pandas, scikit-learn, LightGBM, XGBoost |
| **`systems/backend`** | `model_store` 산출물 읽기 전용 참조, 실시간 고장 진단/위험도 추론, 리포트 생성 및 통합 대시보드 REST API 제공 | FastAPI, Uvicorn, Pydantic |
| **`systems/frontend`** | 설비 마스터 현황, 실시간 진단, 리포트 뷰어, 통합 대시보드 UI 화면 | React 18, TypeScript, Vite |

---

## 3. 실행 방법 (Quick Start)

### 1) Backend (FastAPI) 기동
```bash
cd systems/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 헬스체크 확인: GET http://localhost:8000/health
```

### 2) Generator (오프라인 파이프라인) 실행
```bash
cd systems/generator
pip install -r requirements.txt
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

- **Platform & Pipeline Lead**: `systems/generator` 파이프라인 및 판단 Agent 구축
- **Backend Developer**: `systems/backend` FastAPI REST API 및 실시간 추론 인터페이스 구현
- **Frontend Developer**: `systems/frontend` React 대시보드 UI 개발

# 최종 역할 분배 및 Step별 실행 계획

> 목적: 4명이 각자 기능을 따로 만드는 구조가 아니라, **한 사람의 산출물이 다음 사람의 입력이 되도록** 프로젝트 종료까지의 역할과 실행 순서를 고정한다.
> 기준: 담당자별 책임은 명확히 나누되, 계약은 작성자와 구현 소유자를 분리하고 최종 결과는 하나의 E2E 서비스로 연결한다.

---

## 1. 최종 역할 분배

| 사람 | 최종 책임 | 산출물이 넘어가는 곳 |
|---|---|---|
| **성민 (`smmini`)** | Generator / Feature·Label / Model Training / Model Artifact + Backend API·Artifact 계약 명세 | → **호범** Backend 구현 |
| **호범 (`enjoylonelines`)** | Backend Runtime / Model Artifact Loader / Runtime Inference / Product Result Artifact / Evidence / Product API 구현 | → **광우**, **우수** |
| **광우 (`KOR-GANG`)** | Ontology Closed-loop / Decision / Recommended Action / Maintenance Action / What-if 활용 흐름 | → **우수** Frontend·Report |
| **우수 (`oosuhada`)** | Frontend / UI·UX / CI / E2E / 배포 / 최종 통합 + Executive Brief 정적 보고서 + LLM 기반 동적 보고서 | → **최종 사용자 / 발표 데모** |

---

## 2. 전체 연결 흐름

```text
gen_data
Canonical V3.1 source
        ↓
성민
Extraction / Feature / Label / Train
        ↓
Model Artifact
        ↓
호범
Artifact Load / Runtime Inference
        ↓
Product Result Artifact / Evidence / API
        ↓
광우
Decision / What-if / Recommended Action
        ↓
Maintenance Action / Ontology State
        ↓
우수
Overview / Objects / Operations / Executive Brief
        ↓
Static Report + LLM Dynamic Report
        ↓
CI / E2E / Vercel·Render·Neon / 최종 Demo
```

---

# 3. 사람별 최종 책임

## 3.1 성민 (`smmini`)

### 최종 책임

**Generator와 학습 결과 계약의 owner**로 한다.

성민의 책임 끝점은 다음이다.

```text
Canonical source
→ Extraction
→ Feature Engineering
→ Label
→ Model Training / Evaluation
→ Immutable Model Artifact Publish
```

추가로 **Backend API / Artifact 계약 명세 작성**까지 맡는다.

단, Backend runtime 구현 자체는 맡지 않는다.

### 담당 작업

- Extraction / profiling / semantic mapping
- Feature Engineering
- Feature naming contract
- Label contract
- prediction horizon 반영
- target leakage 방지
- 모델 학습 / 평가
- Model Artifact v1.0 생성
- immutable / atomic publish
- manifest / checksum / provenance
- Generator health / train / retrain endpoint
- Backend가 소비할 API request / response schema 초안
- Product Result / Evidence API shape 명세
- Artifact error / compatibility contract 명세
- OpenAPI 수준의 계약 문서 정리

### 필수 산출물

```text
manifest.json
model.joblib
feature_schema.json
label_schema.json
history_requirement.json
metrics.json
```

### 계약 작성과 구현의 분리

```text
성민
Backend API / Artifact Contract 작성
        ↓
호범
구현 가능성 검토 및 소비자 관점 승인
        ↓
합의된 Contract
        ↓
호범
Backend 실제 구현
```

### 하지 않을 일

- Backend runtime inference 구현
- Product Result Artifact 최종 producer 구현
- Evidence 최종 producer 구현
- `/internal/predict*` Generator 소유
- Frontend 구현
- 범용 Schema Registry
- 범용 Workflow Engine
- multi-version negotiation infrastructure
- 새 microservice 추가

### 완료 조건

> **Backend가 실제로 읽을 수 있는 Model Artifact를 1개 발행하고, 그 Artifact와 API 계약을 호범에게 넘기면 완료.**

---

## 3.2 호범 (`enjoylonelines`)

### 최종 책임

**Backend Product Runtime owner**로 한다.

성민이 만든 Model Artifact와 계약을 입력으로 받아 실제 서비스 결과를 만든다.

```text
Model Artifact
        ↓
Artifact Loader
        ↓
Current Observation
        ↓
Runtime Inference
        ↓
Product Result Artifact
        ↓
Evidence
        ↓
Product API
```

### 담당 작업

- Model Artifact loader
- manifest / checksum / compatibility validation
- current observation 조회
- history requirement 처리
- runtime inference orchestration
- failure probability / status 산출
- Product Result Artifact 생성
- Evidence enrichment
- Evidence provenance
- Product API endpoint 구현
- DB persistence / query
- unavailable / corrupt / unsupported artifact 처리
- Backend integration test
- 광우 Closed-loop가 사용할 Backend service 연결

### 상태 계약

최소 다음 상태를 명확히 처리한다.

```text
normal
warning
danger
unavailable
```

`unavailable`은 다음과 같은 상황에서 명시적으로 발생해야 한다.

- history 부족
- corrupt artifact
- unsupported artifact
- incompatible contract
- 필수 입력 부재

### 현재 #24 관련 원칙

기존 Generator prediction 구현에서 재사용할 수 있는:

- model load
- predict
- SHAP / factor 계산

등은 Backend diagnosis 쪽으로 가져와 재구성한다.

### 하지 않을 일

- Feature Engineering 정책 변경
- Label 정책 변경
- 모델 학습 소유
- Frontend 구현
- Generator daemon 확장
- 장기 계약 거버넌스 설계

### 완료 조건

> **성민의 Model Artifact를 실제로 로드하고, current observation에 대해 Product Result Artifact와 Evidence를 API로 반환하면 완료.**

---

## 3.3 광우 (`KOR-GANG`)

### 최종 책임

**Ontology Closed-loop와 분석 결과의 업무 반영 흐름 owner**로 한다.

광우가 원하는 “분석 결과가 다시 설비·공정에 반영되는 온톨로지 서비스”는 범용 플랫폼이 아니라 **하나의 대표 Closed-loop Use Case**로 증명한다.

### 대표 Use Case

**CNC Tool Replacement Closed-loop**

```text
CNC 센서
        ↓
위험 상승
        ↓
Product Result Artifact / Evidence
        ↓
What-if / Recommendation
        ↓
관리자 Decision
        ↓
TOOL_REPLACEMENT Action
        ↓
Maintenance Event
        ↓
Ontology Equipment 상태 반영
        ↓
Dashboard / Report에서 조치 결과 확인
```

### 담당 작업

- RiskEvent와 Equipment 연결
- Evidence와 RiskEvent 연결
- RecommendedAction 생성
- What-if 결과와 Action 연결
- 관리자 Decision
- MaintenanceAction 생성
- MaintenanceEvent 생성
- Action 완료 상태
- Activity / audit trail
- Ontology state 반영
- Action 이후 UI에서 다시 조회 가능한 상태 제공

### 최소 Ontology 관계

```text
Equipment
  └─ HAS_RISK_EVENT → RiskEvent
                         │
                         ├─ SUPPORTED_BY → Evidence
                         │
                         └─ RECOMMENDS → RecommendedAction
                                             │
Manager ─ APPROVES ─────────────────────────┘
                                             ↓
                                     MaintenanceAction
                                             ↓
                                      MaintenanceEvent
                                             ↓
                                        Equipment
```

### 추천 API 범위

```text
POST /events/{event_id}/decision
POST /events/{event_id}/actions
POST /actions/{action_id}/complete
GET  /events/{event_id}/activity
```

### 하지 않을 일

- 범용 Ontology Engine
- 범용 Workflow Engine
- MES / ERP 구축
- 실제 설비 자동 정지
- Agent framework 확장
- 모든 Action 유형 구현

### 완료 조건

> **한 개의 CNC 위험 Event에서 Evidence → Recommendation → Decision → Tool Replacement Action → MaintenanceEvent → Ontology 상태 갱신까지 한 사이클이 실제로 동작하면 완료.**

---

## 3.4 우수 (`oosuhada`)

### 최종 책임

**최종 Product Integration / Frontend / Report / CI / Release owner**로 한다.

UI·UX에서 끝나는 역할이 아니라, 다른 세 사람의 결과를 실제 사용 가능한 하나의 서비스로 통합한다.

### 담당 영역

```text
Frontend
UI / UX
Executive Brief
LLM Report
CI
E2E
Deployment
Release
Final Demo
```

### A. Frontend / UI·UX

다음 4개 공식 MVP 화면을 제품 흐름으로 연결한다.

```text
Overview
→ Objects
→ Operations
→ Executive Brief
```

#### Overview

- 전체 설비 상태
- 정상 / 주의 / 경고 / 위험 분포
- 주요 위험 설비
- 다음 상세 화면 진입점

#### Objects

- 개별 설비 상세
- 센서 / 추세
- failure probability
- top factors
- Evidence
- provenance

#### Operations

- Risk Event
- Evidence
- Decision
- Recommended Action
- Maintenance Action
- Activity
- Closed-loop 상태

#### Executive Brief

- 동일 Event / Result / Evidence를 보고서 형태로 표현
- 관리자·임원 관점의 핵심 요약 제공

### B. Executive Brief — 1단계: 정적 보고서

먼저 **LLM 없이도 항상 생성 가능한 deterministic/static report**를 구현한다.

입력:

```text
Product Result Artifact
Evidence
Decision
RecommendedAction
MaintenanceAction
Activity
```

정적 보고서 구성:

```text
1. 상황 요약
2. 위험 설비
3. 고장 위험 / 상태
4. 주요 판단 근거
5. 권고 조치
6. 관리자 결정
7. 실제 수행 Action
8. 현재 조치 상태
9. 데이터 / 모델 / Artifact provenance
10. 제한사항
```

#### 정적 보고서 완료 조건

- LLM 없이 생성 가능
- 같은 입력이면 같은 결과
- Dashboard 숫자와 일치
- 없는 정보를 생성하지 않음
- Evidence source reference 유지
- Report fallback으로 항상 사용 가능

### C. Executive Brief — 2단계: LLM 기반 동적 보고서

정적 보고서를 기준 데이터로 사용하고, 그 위에서 **문장 표현만 LLM이 동적으로 생성**하도록 한다.

```text
Structured Report Data
        ↓
Grounded Prompt
        ↓
LLM
        ↓
Executive Narrative
```

LLM이 맡는 영역:

- 상황 요약 문장
- 위험 설명
- 주요 원인 설명
- 관리자용 시사점
- 권고 조치 설명
- Decision / Action 결과 설명
- 보고서 문체 변환

LLM이 하지 않는 영역:

- 새로운 수치 생성
- 새로운 고장 원인 추측
- 없는 정비 이력 생성
- 없는 비용 / 손실 계산
- Evidence에 없는 근거 생성

#### LLM Report 원칙

```text
Structured data = Truth
LLM = Expression layer
```

LLM 실패 시:

```text
LLM Report
   ↓ 실패
Static Deterministic Report
```

로 fallback한다.

#### 동적 보고서 완료 조건

- 같은 Product Result / Evidence를 grounding
- 정적 보고서의 숫자와 불일치 없음
- 근거 없는 주장 없음
- LLM 실패 시 정적 보고서 정상 표시
- manager / engineer 등 역할별 문체 차이 가능
- 최종 Executive Brief 화면에서 동작

### D. CI

우수가 전체 흐름의 통합 안전망을 담당한다.

```text
Generator
        ↓
Model Artifact Contract
        ↓
Backend Runtime
        ↓
Product Result / Evidence
        ↓
Closed-loop Action
        ↓
Frontend
        ↓
Executive Brief
        ↓
E2E
```

CI에서 단계적으로 검증할 항목:

- Architecture rules
- Generator standalone import
- Feature / Label tests
- Model Artifact publish
- JSON Schema validation
- Backend Artifact load
- Product Result / Evidence contract
- Closed-loop Action API
- Frontend unit
- production build
- Playwright E2E
- Docker runtime smoke

### CI 역할 원칙

> 다른 팀원의 구현을 대신 수정하는 것이 아니라, **잘못된 구현이 main에 들어오기 전에 자동으로 실패시키는 역할**을 한다.

### E. 배포 / Release

최종 공개 실행 환경을 우수가 책임진다.

```text
Vercel
Frontend
        ↓
Render
FastAPI Backend
        ↓
Neon
PostgreSQL
```

완료 기준은:

> “로컬에서 된다”가 아니라 **“발표용 공개 URL에서 처음부터 끝까지 된다”**.

### 하지 않을 일

- Generator 내부 ML 구현 대행
- Backend runtime 구현 대행
- 광우의 Action/Ontology 구현 대행
- 각 팀원의 기능을 대신 고치는 방식의 통합

### 완료 조건

> **4명의 산출물을 하나의 사용자 흐름으로 연결하고, 공개 배포 환경에서 E2E 시나리오와 Executive Brief까지 정상 동작하면 완료.**

---

# 4. Step별 실행 계획

## Step 1. 공통 계약 기준선 고정

### 성민

- Feature Contract 확정
- Label Contract 확정
- Model Artifact v1.0 계약 확정
- Backend API / Artifact 계약 초안 작성

### 호범

- Backend 소비자 관점 계약 검토
- 실제 구현 가능한 API / Artifact 계약인지 승인
- runtime 입력 / 출력 경계 확인

### 광우

- Closed-loop에 필요한 Product Result / Evidence / Decision 필드 확인
- 추가 필드가 필요하면 계약 단계에서만 요청

### 우수

- Frontend / Executive Brief에서 필요한 API 필드 확인
- CI에서 검증할 계약 목록 정리

### 완료 조건

```text
Feature Contract
Label Contract
Model Artifact Contract
Product API Contract
Result / Evidence Contract
Action Contract
Report Input Contract
```

의 역할과 owner가 명확하다.

---

## Step 2. Generator Feature / Label 구현 완료

### 성민

- asset별 시계열 격리
- timestamp canonicalization
- deterministic ordering
- Feature naming
- prediction horizon label
- active failure 구간 제외
- leakage 방지
- Feature Schema 생성

### 우수

- 관련 contract test가 CI에서 실행되도록 연결

### 완료 조건

> 동일 입력에서 deterministic Feature / Label이 생성되고 CI가 통과한다.

---

## Step 3. Model Training / Artifact Publish 완성

### 성민

- 학습
- 평가
- metrics
- Model Artifact 6-file 생성
- immutable / atomic publish
- checksum / provenance
- Artifact publish test

### 호범

- 실제 Backend loader에서 사용할 샘플 Artifact 검토

### 우수

- publish → schema validation CI 연결

### 완료 조건

> 실제 Model Artifact 1개가 생성되고 Backend 쪽에 넘길 수 있다.

---

## Step 4. Backend Artifact Loader / Runtime Inference 구현

### 호범

- Artifact load
- manifest validation
- checksum validation
- current observation
- history requirement
- runtime predict
- status 계산
- unavailable 처리

### 성민

- 계약상 불일치가 있는 경우에만 수정

### 우수

- Artifact publish → Backend load round-trip CI 연결

### 완료 조건

> 성민이 만든 Artifact를 호범 Backend가 독립적으로 읽고 inference한다.

---

## Step 5. Product Result Artifact / Evidence API 완성

### 호범

- Product Result Artifact
- Evidence
- provenance
- Product API
- DB persistence/query

### 성민

- API Contract와 실제 구현 간 차이 검토

### 광우

- Closed-loop에서 소비할 결과 연결

### 우수

- Objects / Operations 화면 연결 준비
- contract CI 연결

### 완료 조건

> 동일 Result / Evidence를 API, UI, Closed-loop가 공통으로 소비할 수 있다.

---

## Step 6. Ontology Closed-loop 최소 구현

### 광우

대표 시나리오:

```text
Risk Event
→ Evidence
→ Recommendation
→ Decision
→ TOOL_REPLACEMENT
→ MaintenanceAction
→ MaintenanceEvent
→ Equipment State
→ Activity
```

### 호범

- 필요한 Backend API/service 지원
- persistence 연결

### 우수

- Operations UI에 Action 흐름 연결

### 완료 조건

> 한 개 CNC Event에 대해 Closed-loop 1회가 실제로 완료된다.

---

## Step 7. Frontend 4개 화면 최종 연결

### 우수

```text
Overview
→ Objects
→ Operations
→ Executive Brief
```

를 실제 Backend 데이터로 연결한다.

### 호범 / 광우

- UI에서 발견된 API 계약 오류만 수정

### 완료 조건

> 화면 간 동일 자산 / Event / Result / Evidence가 일관되게 연결된다.

---

## Step 8. Executive Brief 정적 보고서 구현

### 우수

먼저 LLM 없이 구조화된 보고서를 완성한다.

```text
Result
Evidence
Decision
Action
Activity
        ↓
Deterministic Executive Brief
```

### 완료 조건

- 같은 데이터 → 같은 보고서
- Dashboard와 숫자 일치
- Evidence trace 가능
- LLM 없이 항상 생성 가능

---

## Step 9. LLM 기반 동적 Executive Brief 구현

### 우수

정적 보고서 구조를 grounding source로 사용한다.

```text
Structured Executive Brief
        ↓
Prompt
        ↓
LLM
        ↓
Natural-language Executive Brief
```

### 완료 조건

- 숫자 hallucination 없음
- Evidence에 없는 내용 생성 금지
- 정적 보고서와 의미 불일치 없음
- LLM 실패 시 deterministic fallback

---

## Step 10. End-to-End CI 연결

### 우수

다음 전체 흐름을 자동화한다.

```text
Generator
→ Model Artifact
→ Backend Load
→ Runtime Inference
→ Product Result / Evidence
→ Decision / Action
→ Frontend
→ Executive Brief
```

### 각 담당자

CI 실패가 자기 영역이면 자기 PR에서 수정한다.

### 완료 조건

> main 기준 핵심 E2E gate가 green이다.

---

## Step 11. 공개 배포 환경 검증

### 우수

```text
Vercel
→ Render
→ Neon
```

실제 환경에서 검증한다.

### 확인 항목

- 로그인
- Overview
- Objects
- Operations
- Closed-loop Action
- Executive Brief
- LLM Report
- fallback
- logout

### 완료 조건

> 로컬이 아닌 공개 URL에서 핵심 데모 전체가 동작한다.

---

## Step 12. 최종 발표 시나리오 고정

최종 시나리오는 하나로 고정한다.

```text
1. Overview에서 CNC 위험 상승 확인
2. Objects에서 센서 / probability / top factor 확인
3. Operations에서 Evidence 확인
4. What-if / Recommendation 확인
5. 관리자 Decision
6. TOOL_REPLACEMENT Action 생성
7. Maintenance 완료 처리
8. Activity / Ontology state 반영 확인
9. Executive Brief 생성
10. LLM 기반 동적 보고서 확인
```

---

# 5. 프로젝트 공통 작업 규칙

## Rule 1. 새로운 아키텍처 제안 기준

다음 질문 하나로 결정한다.

> **이 작업을 하지 않으면 최종 E2E 데모가 동작하지 않는가?**

- Yes → 지금 처리
- No → Parking Lot

---

## Rule 2. 역할 경계

```text
성민 = 모델과 계약을 만든다
호범 = 모델을 제품 결과로 만든다
광우 = 결과를 실제 Action으로 되돌린다
우수 = 모든 결과를 사용자 제품과 보고서로 완성한다
```

---

## Rule 3. 계약과 구현을 분리

계약 작성자가 모든 구현까지 소유하지 않는다.

예:

```text
성민
Backend API 계약 작성
        ↓
호범
소비자 검토
        ↓
호범
Backend 구현
```

---

## Rule 4. UI와 Report는 별도 데이터 생산자가 아니다

Frontend / Report는 Backend Product Result / Evidence를 소비한다.

```text
Backend Product Result / Evidence
        ├─ Dashboard
        ├─ Operations
        └─ Executive Brief
```

같은 데이터를 서로 다른 방식으로 표현한다.

---

## Rule 5. LLM은 Truth Producer가 아니다

```text
Structured Data = 사실
LLM = 표현
```

LLM이 실패해도 서비스와 보고서는 동작해야 한다.

---

# 6. 최종 팀 완료 정의

프로젝트 완료는 네 사람이 각자 PR을 merge하는 것이 아니다.

다음 하나의 흐름이 공개 환경에서 동작해야 완료다.

```text
Canonical V3.1
→ Feature / Label
→ Model Training
→ Model Artifact
→ Backend Runtime Inference
→ Product Result / Evidence
→ Ontology Decision / Action
→ Maintenance State
→ Dashboard
→ Executive Brief
→ LLM Dynamic Report
```

그리고 이 전체 흐름을 CI / E2E / 배포 환경에서 재현할 수 있어야 한다.

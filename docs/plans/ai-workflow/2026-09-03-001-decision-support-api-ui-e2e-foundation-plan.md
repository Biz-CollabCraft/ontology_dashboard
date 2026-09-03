---
title: Operational Decision Support API UI E2E Foundation Plan
type: feat
status: planned
date: 2026-09-03
---

# Operational Decision Support API UI E2E Foundation Plan

## Summary

이 문서는 이미 구현된 read-only Operational Decision Support vertical slice를 실제 FastAPI와 기존 MVP UI에
최소 연결하고, 브라우저에서 API, service, SQLite materialization, reload/reuse, 권한, 무부작용까지
검증할 수 있는 E2E 기반을 만드는 실행 계획이다.

새 운영 제품이나 별도 Agent 화면을 추가하는 계획이 아니다. 현재 프로젝트 규모에 맞춰 기존
설비 상세 화면의 AI 검토 영역을 확장하고, 실제 MES/CMMS/WMS/QMS 대신 현재 검증된 synthetic/SQLite
context를 사용한다.

PR 160 최신 커밋까지 반영된 realtime maintenance closed-loop는 실행 상태의 권위로 유지한다.
Operational Context Agent는 이 상태를 읽을 수 있지만 WorkOrder, MaintenanceAction, 설비 제어,
부품 예약, 담당자 배정을 직접 수행하지 않는다.

이 문서는 `2026-09-02-002-operational-domain-extension-plan.md`의 API/UI와 targeted E2E 실행 하위
계획이다. 평가 축과 주장 기준은 `2026-09-01-004-feat-agent-workflow-stability-evaluation-plan.md`,
발표 흐름과 시각 증거는 `2026-09-03-002-ai-solution-engineer-presentation-frame-plan.md`를 따른다.
실제 수치는 candidate SHA와 artifact가 고정된 최종 평가 보고서만 정본으로 사용한다.

## Goal

다음 한 경로를 재현 가능한 E2E로 증명한다.

```text
사용자 로그인과 scope 확정
  -> 설비 상세 선택
  -> Decision Support Brief 요청
  -> FastAPI authorization/CSRF/rate limit
  -> BoundedOperationalDecisionAgent
  -> SQLite operational context read ports
  -> Relation Resolver
  -> deterministic Impact Simulation
  -> temporal revalidation
  -> immutable brief materialization
  -> UI 표시와 reload/reuse
  -> WorkOrder/command side effect 0
```

## Current Baseline

### Verified

- Production Order/WIP/Alternative Capacity synthetic contract와 SQLite read port
- Maintenance Window/Part/Technician readiness contract와 관계 해석
- Quality/Lot/Delivery 관계와 blocker
- deterministic Impact Simulation
- fixed request identity와 domain version/freshness/as-of 검증
- stale context 차단과 immutable materialization
- Agent Review Summary의 FastAPI, frontend API, SQLite, Playwright 경로
- PR 160 realtime maintenance closed-loop 안정화
- service/SQLite reliability 11개 시나리오
- live LLM B1/B2/B3와 120-run quality evaluation

### Not Yet Verified

- Operational Context Agent의 public HTTP API
- Decision Support Brief의 실제 UI consumer
- browser -> API -> Agent -> SQLite -> UI 전체 경로
- 현재 후보 SHA에 대한 Decision Support Playwright E2E
- 실제 MES/CMMS/WMS/QMS 연결

## Scope Decision

### In Scope

1. 기존 operational request/result/brief/materialization contract 재사용
2. 기존 MVP router에 read/materialize API와 안정성 평가·감사용 run-log API 추가
3. composition root에서 현재 SQLite/fixture read ports 주입
4. 기존 설비 상세 dialog에 compact Decision Support panel 추가
5. manager materialize와 engineer read-only 권한 분리
6. source classification, freshness, gap, relation, option comparison 표시
7. API integration test와 Playwright E2E 3개
8. E2E artifact에 candidate SHA, run ID, 실행 시각 기록
9. 기존 Agent Review와 PR 160 closed-loop 회귀 검증
10. 확장 구현과 Decision Support 안정성 평가 완료 후, Closed-loop 연동까지 완료된 후보를 대상으로 하는 최종 통합/E2E 안정성 평가

### Out of Scope

- 실제 MES/CMMS/WMS/QMS/ERP/APS 연결
- 새로운 독립 Agent 화면 또는 채팅 UI
- LangGraph, graph database, vector database
- 자동 최적 행동 선택
- AI의 WorkOrder/MaintenanceAction 생성
- 설비 정지 명령, 부품 예약/출고, 기술자 배정
- E2E에서 실제 유료 LLM 호출
- 장시간 soak, p99 SLO, production load test
- 모든 운영 도메인의 CRUD UI
- `decision-support-workflow-runs`를 일반 사용자용 업무 화면이나 Closed-loop 제어 화면으로 노출

## Architecture Boundary

| Layer | Owns | Must Not Own |
|---|---|---|
| Product Result/Evidence | 고장 판단과 근거 identity | 운영 context에 의한 재판정 |
| Operational read ports | 생산·정비·재고·품질 snapshot | command와 상태 mutation |
| Relation Resolver | 기존 ID 관계 연결과 gap/conflict | 새로운 운영 사실 생성 |
| Impact Simulation | versioned formula와 조건 비교 | 최적 행동 추천 |
| Bounded Agent | allowlist 조회 순서와 수집 결과 | scope 선택과 unrestricted tool call |
| Operational Brief | 사실·관계·선택지 설명 | 계산값 변경과 자동 승인 |
| FastAPI | 인증, scope, CSRF, rate limit, materialization | 도메인 truth 재해석 |
| UI | 상태·gap·source·비교 표시와 명시적 refresh | 정상값 합성 또는 자동 실행 |
| Evaluation observability | bounded 실행 trajectory와 안정성 평가 증거 | 업무 Decision·Closed-loop 상태·사용자 Action |
| Closed-loop | 사용자 승인 뒤 실행 상태 | AI 결과의 무조건 실행 |

PR 160의 realtime maintenance timeline과 Decision Support materialization timeline을 하나로 합치지 않는다.

- realtime maintenance timeline: 실제 WorkOrder/MaintenanceAction lifecycle
- operational brief timeline: 읽은 context version과 brief materialization 이력

UI에서는 같은 설비 상세 안에 표시하되 서로 다른 제목과 source를 유지한다.

## API Contract

기존 MVP API 패턴을 유지한다.

### GET cached brief

```http
GET /api/objects/{asset_id}/decision-support-brief
  ?project_id={project_id}
  &workspace_id={workspace_id}
  &evidence_snapshot_id={evidence_snapshot_id}
  &decision_as_of={timestamp}
  &role={role}
```

- permission: 기존 read permission
- materialized brief가 없으면 `202`
- GET은 Agent 실행이나 LLM 호출을 시작하지 않는다.
- 응답은 `brief: null`과 structured trace/reason을 반환할 수 있다.

### POST materialize or refresh

```http
POST /api/objects/{asset_id}/decision-support-brief
  ?project_id={project_id}
  &workspace_id={workspace_id}
  &evidence_snapshot_id={evidence_snapshot_id}
  &decision_as_of={timestamp}
  &role={role}
  &trigger=manual_materialization|ui_manual_regeneration
```

- permission: dedicated `agent.review.materialize` 또는 별도 동등 권한
- CSRF와 rate limit 필수
- identity는 principal과 route/query에서 확정하고 Agent가 선택하지 않는다.
- 같은 identity/context version/policy version은 기존 brief를 reuse한다.
- refresh 중 context version이 바뀌면 이전 결과를 저장하지 않는다.

### GET workflow runs — operational stability evaluation and audit only

```http
GET /api/projects/{project_id}/decision-support-workflow-runs
  ?asset_id={asset_id}
  &status=running|completed|partial|failed
  &limit=20
```

이 API는 여러 운영 맥락을 수집해 AI Brief를 생성하는 bounded Operational Workflow가 예상된
도메인만 조회했는지, 실패를 격리했는지, stale 결과를 차단했는지 평가하는 관측 surface다.
제품 사용자가 운영 판단이나 정비 상태를 처리하는 API가 아니며 별도 Closed-loop 상태 머신도 아니다.

- primary consumer: stability evaluator, regression test, `tenant_admin` audit tooling
- permission: `admin.audit.read`
- 기본 MVP 사용자 화면에는 노출하지 않는다.
- GET은 새 workflow, context 조회, LLM 호출 또는 materialization을 시작하지 않는다.
- raw chain-of-thought를 저장하거나 반환하지 않는다.
- stage, called tool, reason code, source version, retry/fallback, latency, reuse와 temporal validation만 반환한다.
- RecommendationDecision, WorkOrder, MaintenanceAction, MaintenanceEvent, `available_actions`를 생성·변경·합성하지 않는다.
- Closed-loop Activity timeline 또는 realtime maintenance lifecycle의 정본으로 사용하지 않는다.
- 이 API가 없어도 Brief GET/POST와 기존 Closed-loop 업무 흐름은 정상 동작해야 한다.

### Response Shape

새 평면 schema를 다시 만들지 않고 기존 `OperationalDecisionBrief`와 materialization 결과를 API
response envelope로 감싼다.

```json
{
  "brief": {},
  "trace": {
    "status": "completed",
    "reason": null,
    "reused": false,
    "workflow_run_id": "ODR-...",
    "context_version_set": {},
    "temporal_validation": "passed"
  }
}
```

`unknown`, `not_connected`, `not_calculable`, `partial_with_gaps`를 null 또는 0으로 정규화하지
않는다.

## Backend Implementation

### B1. API schema and authorization

- request query enum과 response envelope 추가
- project/workspace/asset/evidence identity 검증
- role allowlist와 principal scope 검증
- CSRF/rate limit 적용
- malformed timestamp와 future `decision_as_of` 차단
- GET cache-only contract 고정

### B2. Application service facade

Router가 Agent와 repository를 직접 조립하지 않도록 MVP application service에 다음 facade를 둔다.

- `cached_decision_support_brief(...)`
- `decision_support_brief(...)`
- `decision_support_workflow_runs(...)`

Facade는 기존 Agent, brief composer, materialization 함수를 호출하고 exception을 stable API reason
code로 변환한다.

### B3. Composition root

- current demo project에서는 SQLite operational context ports 주입
- 실제 external adapter가 없으면 source classification을 `synthetic` 또는 `not_connected`로 유지
- PR 160 closed-loop repository는 read-only snapshot consumer로만 연결
- Agent registry에 Closed-loop command port를 등록하지 않음

### B4. Persistence and reuse

가능하면 기존 operational materialization 저장 계약을 사용한다. 새 table이 필요한 경우에도 다음만
저장한다.

- request identity
- context version set
- simulation policy version
- brief snapshot
- structured trajectory
- status/reason/timestamps

동일 key에 대한 active run은 repository atomic guard로 하나만 허용한다.

## UI Implementation

새 페이지를 만들지 않고 기존 선택 설비 상세 dialog의 AI 검토 영역 아래에
`운영 판단 지원` panel을 추가한다.

### Required Sections

1. **상태**
   - complete / partial_with_gaps / unavailable
   - observed/retrieved/as-of
2. **왜 지금 확인하는가**
   - Evidence 기반 위험과 운영 영향의 분리된 설명
3. **관계**
   - 설비 -> 생산오더/WIP
   - 정비 액션 후보 -> 필요 부품 -> 재고/예약
   - 정비 액션 후보 -> 필요 기술 -> 담당자 가용성
   - lot -> WIP -> order -> delivery
4. **선택지 비교**
   - 지금 정지 / 계획 정비 / 제한 운전
   - 계산 가능 여부, assumptions, formula version
5. **Gap과 blocker**
   - quality hold, missing relation, stale/not-connected context
6. **출처**
   - synthetic/connected classification과 source refs
7. **명시적 갱신**
   - manager만 enabled
   - engineer는 저장 결과 read-only

### UI Rules

- 없는 수치를 0으로 표시하지 않는다.
- `not_calculable`을 비활성 추천으로 표현하지 않는다.
- 가장 좋은 선택을 강조하거나 자동 선택하지 않는다.
- WorkOrder 생성 버튼을 이 panel에 추가하지 않는다.
- Closed-loop action panel과 시각적·문구상 경계를 유지한다.
- 모바일에서는 관계를 graph canvas가 아니라 순서형 relation list로 표시한다.

## Test Strategy

### Contract and unit

- response schema round-trip
- unknown/not-connected/not-calculable 보존
- role별 truth는 같고 wording/visible sections만 다름
- relation source/version metadata 보존
- option value를 UI adapter가 재계산하지 않음

### API integration

FastAPI `TestClient`와 격리 SQLite를 사용한다.

1. manager POST -> 200 -> brief/run 저장
2. 동일 GET -> 같은 brief ID와 context version reuse
3. engineer GET 허용, POST 403
4. CSRF 누락 POST 차단
5. project/workspace/asset scope mismatch 차단
6. context version mismatch 시 stale brief 저장 차단
7. timeout/malformed/not-connected가 distinct reason으로 반환
8. 호출 전후 WorkOrder/MaintenanceAction/command count 동일
9. PR 160 realtime maintenance 상태가 brief에 의해 변경되지 않음

### Playwright E2E

전체 제품 E2E를 늘리지 않고 다음 3개만 추가한다.

#### E1. Manager materialize and reload reuse

```text
manager 로그인
  -> 설비 상세
  -> 운영 판단 지원 요약 생성
  -> API 200과 panel 표시
  -> 새로고침
  -> GET으로 같은 brief reuse
  -> 중복 workflow run 없음
  -> WorkOrder/command count 변화 없음
```

#### E2. Engineer read-only

```text
engineer 로그인
  -> 저장된 brief 조회
  -> source/gap/option 표시
  -> 갱신 버튼 disabled
  -> Closed-loop mutation 없음
```

#### E3. Partial context and safe UI

```text
quality hold 또는 external not-connected fixture
  -> partial_with_gaps 표시
  -> not_calculable 선택지 확인
  -> 임의 수치와 추천 없음
  -> 기존 realtime maintenance 화면은 계속 동작
```

E2E provider는 제어 가능한 deterministic/fake adapter를 사용한다. 실제 provider 연결 확인은 기존
별도 live smoke가 소유한다. 이 세 시나리오는 확장 구현 중 회귀를 막는 targeted E2E 기반이며,
Closed-loop까지 연결된 최종 통합/E2E 안정성 평가를 대신하지 않는다.

## Final Integration and E2E Stability Evaluation

최종 통합/E2E 안정성 평가는 다음 순서를 모두 충족한 뒤에만 수행한다.

```text
Operational Decision Support 확장 구현 완료
  -> 확장 후보의 독립 안정성 평가 완료
  -> Closed-loop 담당 경계의 연동 완료
  -> 통합 후보 SHA 고정
  -> 전체 통합/E2E 안정성 평가
```

최종 통합 경로는 다음을 검증한다.

```text
Model Artifact
  -> Generator Runtime Prediction
  -> Backend Product Result / Evidence
  -> Evidence Packet
  -> AI Brief와 작업 요청 추천
  -> Human Decision
  -> Closed-loop Maintenance 실행
  -> gen_data post-maintenance Overlay
  -> Generator 재예측
  -> 새 Product Result / Evidence
  -> Evidence Packet과 AI Brief 재생성
```

### 책임 경계

이 최종 평가가 Decision Support 구현자 한 명에게 전체 시스템 구현 책임을 부여하지 않는다.

- 각 도메인 소유자는 자신의 input/output contract, deterministic fixture, failure signal을 제공한다.
- Decision Support 소유 범위는 Evidence Packet부터 AI Brief와 작업 요청 추천까지다.
- `gen_data`는 post-maintenance Observation/Overlay 생성, Generator는 feature와 재예측을 소유한다.
- Closed-loop는 사용자 승인 이후 Maintenance 상태와 orchestration을 소유한다.
- 통합/E2E 담당은 고정된 후보 SHA와 환경에서 경계를 연결하고 전체 결과를 수집한다.
- AI는 실제 WorkOrder를 자동 생성하거나 Maintenance를 자동 승인하지 않는다.

### 최종 안정성 시나리오

1. 정상 경로: 최초 예측부터 사람 판단, 정비, 재예측, Evidence/Brief 재생성까지 완료
2. temporal 경로: Evidence 또는 운영 context version 변경 시 이전 Brief 폐기·재생성
3. cold-start 경로: 정비 전 history 비혼합, 요구 이력 전 `warming_up`, 충족 후 재예측
4. failure isolation: source, feature, model, delivery 실패가 무한 관측 대기로 숨지 않음
5. lineage 경로: `maintenance_event_id`, session, branch, history segment가 최종 Brief까지 보존
6. 권한 경로: AI 추천 이후 Human Decision 없이 WorkOrder/Maintenance side effect가 발생하지 않음
7. 복구 경로: worker 재시작과 at-least-once redelivery 후 중복 Result/Brief가 생성되지 않음

Closed-loop 연동 전에는 Model Artifact부터 AI Brief/작업 요청 추천까지의 Decision Support E2E만
검증 완료로 표시한다. `gen_data -> 재예측 -> Evidence Packet 재생성`을 포함하지 않은 결과를
전체 Closed-loop 통합 E2E 완료로 주장하지 않는다.

## E2E Evidence Contract

`.last-run.json`만으로 최종 증거를 주장하지 않는다. 평가 artifact에 다음을 기록한다.

```json
{
  "run_id": "operational-e2e-...",
  "candidate_sha": "...",
  "recorded_at": "...",
  "mode": "playwright_local_isolated_sqlite",
  "tests": {
    "manager_materialize_reuse": "passed",
    "engineer_read_only": "passed",
    "partial_context_safe_ui": "passed"
  },
  "side_effects": {
    "work_order_delta": 0,
    "maintenance_action_delta": 0,
    "command_delta": 0
  }
}
```

Playwright trace/screenshot은 실패 시에만 보존하고, token·비용·실제 외부 연결은
`not_measured`로 기록한다.

## Implementation Units and Commits

### U1. Public API facade

- router, API schema, authorization, cache-only GET, materializing POST
- API integration tests
- commit: `feat: expose operational decision brief api`

### U2. Frontend API and compact panel

- typed frontend client
- existing asset detail panel consumer
- role/read-only/gap/source/option rendering
- component tests
- commit: `feat: show operational decision context in mvp`

### U3. Targeted E2E foundation

- Playwright 3 scenarios
- run ID/candidate SHA result artifact builder
- release gate 또는 별도 targeted command
- commit: `test: add operational decision vertical slice e2e`

### U4. Candidate verification

- backend contract/integration regression
- frontend unit/lint/build
- targeted Playwright E2E
- Agent Review Summary regression
- PR 160 realtime closed-loop regression
- final implementation note
- commit: `docs: record operational decision e2e evidence`

### U5. Decision Support stability evaluation

- 확장 구현 후보 SHA 고정
- API/UI/Agent 반복 안정성, temporal validation, retry/fallback 평가
- 실제 Closed-loop 미연결 항목은 `not_measured`로 유지
- commit: `test: evaluate decision support stability`

### U6. Closed-loop integration gate

- Closed-loop 담당 산출물과 `gen_data`/Generator 재예측 경계 연결
- 진행률·blocked 상태와 post-maintenance lineage 확인
- 각 소유자의 component/integration test 결과 수집
- commit은 담당 경계별 저장소와 소유권에 따라 분리

### U7. Final integration/E2E stability evaluation

- 통합 후보 SHA와 외부 저장소 revision 고정
- 최초 예측부터 정비 후 Evidence Packet/AI Brief 재생성까지 전체 경로 실행
- 정상, cold-start, failure isolation, lineage, 권한, 재시작 시나리오 평가
- 결과와 미측정 범위를 최종 evidence artifact에 기록
- commit: `test: evaluate integrated decision support closed loop`

각 단위는 독립 테스트 후 커밋한다. U7은 U1~U5와 Closed-loop 연동 U6이 완료된 뒤에만 시작한다.

## Verification Commands

```bash
ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 PYTHONPATH=systems/backend:systems/generator .venv/bin/pytest -q   tests/test_operational_decision_agent.py   tests/test_operational_context_sqlite.py   tests/test_operational_decision_brief.py   tests/test_operational_decision_materialization.py   tests/test_mvp.py   tests/test_maintenance_loop_application.py   tests/test_live_predictive_maintenance.py
```

```bash
cd systems/frontend
npm test -- --run
npm run lint
npm run build
npx playwright test e2e/mvp-decision-support.spec.ts --project=chromium
```

최종 후보에서만 전체 `mvp-frontend-convergence.spec.ts`를 한 번 실행한다.

## Completion Gates

- public GET/POST/run API가 실제 app router에 포함됨
- GET이 lazy materialization을 시작하지 않음
- POST에 permission, CSRF, rate limit 적용
- UI가 실제 API response를 소비함
- reload 후 동일 version brief reuse
- role별 권한 분리
- source/freshness/as-of/gap/not-calculable 표시
- 관계와 simulation 결과를 UI가 재계산하지 않음
- stale context 결과 저장 차단
- WorkOrder/MaintenanceAction/command delta 0
- PR 160 realtime closed-loop 회귀 없음
- Playwright 3개 통과
- E2E artifact에 run ID와 candidate SHA 존재
- 실제 external source가 없으면 not-connected/synthetic 표기
- 실제 LLM, MES/CMMS/WMS/QMS 효과를 E2E 결과로 주장하지 않음
- Decision Support 확장 구현 및 독립 안정성 평가 완료
- Closed-loop 연동 완료와 각 소유 경계의 component/integration 증거 존재
- 최초 예측부터 정비 후 Evidence Packet/AI Brief 재생성까지 최종 통합/E2E 안정성 시나리오 통과
- Closed-loop 연동 전 결과와 최종 통합 결과를 별도 evidence state로 구분

## Stop Conditions

다음 상황이면 범위를 확대하지 않고 구현을 중단해 재검토한다.

- API를 위해 기존 domain contract를 복제해야 하는 경우
- UI가 새 독립 페이지나 graph engine을 요구하는 경우
- Operational Agent가 Closed-loop command port를 요구하는 경우
- relation 표시를 위해 KG 도입이 필요하다고 가정하는 경우
- E2E 안정화를 위해 실제 provider 호출이 필수가 되는 경우
- PR 160 realtime lifecycle과 brief materialization lifecycle이 혼합되는 경우

## Follow-up and Evaluation Order

평가와 통합은 다음 순서를 바꾸지 않는다.

1. U1~U4 Operational Decision Support 확장 구현과 targeted E2E 기반 완료
2. U5에서 현재 8개 Gold fixture의 120-run 1.0과 B3 0.6979 차이 및 대표 4개 사례 검토
3. U5 Decision Support 독립 안정성 평가 완료와 후보 SHA 고정
4. U6 Closed-loop 담당 경계 연동 완료
5. U7 전체 통합/E2E 안정성 평가 수행과 최종 후보 revision 고정
6. 확장 구현이 실제 사용자 가치가 있을 때만 운영 Gold set 추가
7. 실제 external adapter가 생길 때만 external integration/soak 평가

U5까지는 본 계획 소유 범위의 안정성을 판정할 수 있다. U6이 미완료이면 U7은
`blocked_by_integration`으로 기록하며, 이를 Decision Support 구현 실패로 간주하지 않는다.

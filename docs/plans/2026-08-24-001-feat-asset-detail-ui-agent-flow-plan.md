---
title: "Asset Detail UI/UX And Agent Workflow Plan"
type: feat
status: active
date: 2026-08-24
depends_on:
  - "PR #110 Asset Criticality Modeling Plan"
  - "feat/asset-detail-viewmodel-fixture-contract"
  - "Closed-loop Product Consumption Contract"
  - "Closed-loop Runtime Overlay Contract"
---

# Asset Detail UI/UX And Agent Workflow Plan

## Summary

Asset detail 후속 작업은 agent workflow를 먼저 붙이는 방향이 아니라,
Objects / Operations / Report의 화면 책임을 먼저 정리한 뒤 agent를 얕은 coordination
layer로 얹는 순서로 진행한다.

이번 계획의 기준은 다음 세 가지다.

1. fixture clean contract의 `AssetDetailViewModel` shape를 UI와 agent input의 기준으로 삼는다.
2. Objects는 canonical inspection surface, Operations는 governed human decision surface,
   Report는 grounded narrative surface로 분리한다.
3. Agent는 read-only review packet과 draft를 만들 수 있지만 risk, criticality,
   `review_priority`, authorization, WorkOrder/MaintenanceAction state, replay session
   의미를 소유하지 않는다.

## Fixture Baseline

이 계획은 fixture 기준 브랜치의 `40e37b1` 이후 계약을 전제로 한다.

```text
features[].current = { observed_at, value, quality_status }
features[].history = { source_ref, points[] }
history.points[] = { observed_at, value, quality_status }
```

UI와 agent는 이 계약을 다음처럼 소비한다.

- `current`는 ViewModel snapshot boundary의 현재 관측 객체다.
- `history.points[]`는 current instant보다 이전인 이력만 담는다.
- composer, fixture adapter, frontend adapter, agent input builder는 current를 history에 병합하지 않는다.
- 차트 표시에서 current point가 필요하면 presentation-only point로 렌더링하고 계약 데이터를 변경하지 않는다.
- timezone-aware instant 기준으로 current/history timestamp를 비교한다.
- 같은 instant의 충돌 관측은 한쪽을 임의 우선하지 않고 contract/test에서 드러내야 한다.
- `history.source_ref`는 이력 envelope의 공통 출처다. point마다 speculative source enum을 만들지 않는다.
- baseline 계산은 명시된 baseline/history input만 사용한다. current를 조용히 baseline에 섞지 않는다.

Fixture baseline의 검증 상태:

- backend contract/composer/MVP focused tests는 fixture 기준에서 통과한 것으로 기록한다.
- frontend typecheck, adapter regression, browser E2E는 이 계획의 후속 검증 대상이다.
- PR #110 문서의 criticality/context/review-priority 계획은 이 fixture shape를 기준으로 해석한다.

## Architecture Decision

채택 방향:

```text
AssetDetailViewModel
  -> Objects canonical inspection
  -> Operations governed decision
  -> Report grounded narrative
  -> Agent coordination draft, later and read-only first
```

소유권은 다음처럼 고정한다.

| 대상 | Canonical owner | UI 역할 | Agent 역할 |
|---|---|---|---|
| `risk.status_grade` | Diagnosis Runtime/model policy | 표시 | 설명만 가능 |
| `features[].current` | AssetDetailViewModel composer | 현재 관측 표시 | 입력으로만 소비 |
| `features[].history` | AssetDetailViewModel composer | 이력/trend 표시 | 입력으로만 소비 |
| `asset.criticality` | equipment/project context | 표시와 gap 표시 | 읽기만 가능 |
| `maintenance_context` | backend composition/read model | Objects context | 요약만 가능 |
| `operation_context` | backend composition/read model | Objects context | 요약만 가능 |
| `review_priority` | backend composition/policy | 정렬과 이유 표시 | 재계산 금지 |
| `available_actions` | backend authorization projection | Operations action renderer | 소비만 가능 |
| Recommendation disposition | authorized human + Closed-loop Domain | 승인/보류/반려 UI | draft만 가능 |
| WorkOrder/MaintenanceAction state | Closed-loop Domain | persisted state 표시 | 변경 금지 |
| `simulation_session_id` | Diagnosis Runtime/replay runtime | opaque reference 표시 가능 | 해석 금지 |

## Screen Responsibilities

| 화면 | 사용자 질문 | 정본으로 보여줄 것 | 축약할 것 | 넘길 것 |
|---|---|---|---|---|
| Overview | 지금 무엇부터 봐야 하나? | backend `review_priority` 순서, data-quality hold, 최신 snapshot | risk + criticality + reason 1줄 | 상세 evidence, action form |
| Objects | 이 설비가 왜 위험한가? | risk, current/history, top factors, criticality, context, gaps, provenance | 현재 recommendation 상태 1줄 | decision form |
| Operations | 지금 사람이 무엇을 결정해야 하나? | recommendation state, `available_actions`, Decision/WorkOrder/MaintenanceAction state, Activity | evidence review packet | full sensor/factor explorer |
| Report | 어떻게 공유할까? | grounded narrative, current decision/action state, limitations, evidence links | 핵심 fact strip | action controls, KPI 복제 |
| Ontology Workbench | 관계를 더 탐색할까? | typed references와 lineage | 선택 객체 context | PdM 핵심 workflow 대체 |

### Objects

Objects는 canonical Asset inspection owner다.

구성:

1. Asset header: asset identity, risk badge, `review_priority`, data-quality state.
2. Why This Asset: risk / criticality / context를 분리한 세 줄.
3. Current Evidence: `features[].current`, `features[].history`, top factors, threshold, gaps.
4. Context Snapshot: `maintenance_context`, `operation_context`, missing source warnings.
5. Work Link: current recommendation/action state 1줄과 Operations deep link.
6. Source And Limits: provenance, `source_ref`, warnings, owner domain.

Objects가 하지 않는 일:

- WorkOrder approval form 렌더링.
- frontend에서 criticality나 `review_priority` 계산.
- current/history 병합으로 baseline 또는 source truth 변경.

### Operations

Operations는 governed human decision surface다.

구성:

1. Queue: backend `review_priority`와 backend action state를 그대로 사용.
2. Decision Packet: risk, criticality, context, limitation을 2-4줄로 요약.
3. Governed Action: Recommendation disposition, `available_actions`, disabled reason.
4. State Strip: Decision, WorkOrder, MaintenanceAction persisted ID/state.
5. Activity/Audit.
6. Objects link: full evidence로 이동.

Operations가 하지 않는 일:

- Top factors chart와 full provenance 반복.
- WorkOrder ID, recommendation state, permission 계산.
- agent draft를 Activity 완료 사실로 자동 승격.

### Report

Report는 grounded narrative surface다.

구성:

1. Situation.
2. Operational impact.
3. Current recommendation.
4. Human decision/action state.
5. Next review.
6. Limitations and evidence links.

Report가 하지 않는 일:

- canonical sensor/factor explorer 역할.
- action control 렌더링.
- Event 하나로 aggregate KPI를 암시.
- `report.actions[]`를 executable available action으로 해석.

## UI/UX Changes

### Remove Or Reduce Duplication

| 현재 반복 | 조치 |
|---|---|
| Objects와 Operations의 recommendation 상세 반복 | Objects는 1줄 상태, Operations가 decision owner |
| Operations의 Top factors/threshold 상세 | Decision Packet으로 축약하고 Objects 링크 |
| Report의 Top factors/KPI 반복 | narrative + evidence links 중심으로 축약 |
| 세 화면의 recommendation label 혼동 | `시스템 권고`, `최근 사람 결정`, `현재 가능한 액션`으로 라벨 분리 |
| frontend-computed risk/criticality/priority order | backend payload 그대로 사용 |

### New Blocks

이번 구현 후보:

- Review Priority Strip: backend `review_priority.level`, reasons, as_of를 표시.
- Why This Asset: risk / criticality / context를 분리해서 표시.
- Context Snapshot: `maintenance_context`와 `operation_context`를 Objects에 표시.
- Decision Packet: Operations에서 full evidence 대신 2-4줄 검토 패킷 표시.
- Canonical Evidence Link: Operations/Report에서 Objects 동일 snapshot으로 이동.

다음 구현 후보:

- Available Actions Panel.
- Operational State Strip.
- Evidence Reference Drawer.

Agent용 얕은 자리:

- Operations의 governed action 위 또는 Activity 옆에 Coordination Draft block을 둔다.
- Report에는 agent output을 정본 narrative로 자동 반영하지 않는다.

## Frontend Contract Rules

Frontend는 다음 값을 합성하지 않는다.

- `criticality`
- `review_priority`
- WorkOrder ID
- Recommendation state
- permission / authorization
- MaintenanceAction state
- `simulation_session_id`

Adapter 수정 원칙:

- `criticality`는 `low | medium | high | null`을 보존한다.
- missing impact/runtime/downtime은 `0`, `false`, `normal`, `low`로 바꾸지 않는다.
- `review_priority`는 backend block을 그대로 타입화한다.
- `available_actions`는 backend action descriptor를 그대로 사용한다.
- Recommendation, Decision, WorkOrder, MaintenanceAction state는 서로 다른 타입과 라벨로 유지한다.
- `features[].current`와 `features[].history`를 contract 그대로 받는다.
- trend chart가 current point를 렌더링하더라도 contract payload를 변경하지 않는다.

즉시 제거해야 할 adapter anti-pattern:

```text
criticality = status 기반 fallback
probability threshold로 status 재등급화
status + probability + criticality 기반 frontend sortRisk
recommended_action 문자열을 UI decision으로 정규화
estimatedDowntimeMinutes ?? 0
fixture provenance/site/cell 기본값을 사실처럼 채움
```

## Agent Workflow Plan

Agent workflow는 UI 책임이 정리된 뒤 점진적으로 붙인다.

### Stage 0: Prerequisite Stabilization

선행 조건:

- fixture clean contract를 frontend 타입/adapter/browser 경로까지 검증.
- criticality/context/review-priority schema와 composer contract 구현.
- Objects/Operations/Report 중복 정리.
- frontend-side synthesis 제거.
- Backend `available_actions`와 command endpoint 검증 유지.
- `simulation_session_id`는 Diagnosis Runtime 소유, Maintenance는 opaque reference만 보존.

Exit criteria:

- 동일 snapshot의 risk/evidence/context가 화면별로 달라지지 않는다.
- frontend가 `review_priority` 또는 `available_actions`를 합성하지 않는다.
- agent 없이도 detection -> Evidence -> Report -> Recommendation candidate -> human decision 흐름이 동작한다.

### Stage 1: Read-only Review Packet

Input:

- `AssetDetailViewModel`
- Event Evidence Projection
- Report projection
- Recommendation candidate
- Closed-loop read model

Output:

- 현재 위험과 근거 요약.
- criticality / operation / maintenance context 요약.
- evidence gaps와 data-quality warnings.
- canonical Recommendation 설명.
- 사람에게 필요한 확인 질문.
- source/snapshot/limitation metadata.

금지:

- risk grade 재계산.
- `review_priority` 재정렬.
- action/WorkOrder ID 생성.
- Domain mutation 호출.

### Stage 2: WorkOrder Appraisal And Duplicate Review

Workflow A: WorkOrder appraisal

- Input: Recommendation, Evidence, WorkOrder draft/read model, required-field policy.
- Output: 누락 필드, Evidence 불일치, 확인 질문, approval-request 문안.
- Agent는 WorkOrder를 생성하거나 수정하지 않는다.

Workflow B: Duplicate WorkOrder review

- Input: same-scope open WorkOrders, asset/event/evidence lineage, action code, state, time window.
- Output: duplicate 후보, 유사 근거, 결정적 차이, 검토 권고.
- Agent는 중복 확정, 병합, 취소, 재배정을 수행하지 않는다.

### Stage 3: Checklist, Handoff, Approval-request Draft

허용:

- evidence 확인 checklist.
- shift/team handoff summary.
- approval-request draft.
- 확인되지 않은 전제와 limitation.

제한:

- 검증된 procedure/manual source가 없으면 구체적인 수리 절차를 생성하지 않는다.
- 초안은 canonical WorkOrder/Action state로 표시하지 않는다.

### Stage 4: Approval-required Tool Proposal

허용 가능한 초기 tool proposal:

- Recommendation accept/reject/defer 제안.
- WorkOrder 생성 요청 제안.
- WorkOrder 승인 요청 제안.
- note/handoff 기록 제안.

초기 제외:

- MaintenanceAction start/complete.
- shutdown 실행.
- replay 생성/제어.
- `maintenance.replay_requested` 발행.
- `state_patch` 작성.
- bulk transition.

실행 규칙:

- Agent proposal은 pending approval 상태로 멈춘다.
- 사용자가 승인해도 backend command endpoint가 authorization, state, scope, lineage, idempotency를 다시 검증한다.
- backend가 거절하면 agent output은 domain state를 바꾸지 않는다.

## Simulation And Replay Boundary

현재 MVP:

- caller가 replay session selector를 전달한다.
- Diagnosis Runtime public query가 organization/project/workspace scope, session state, Dataset binding, target equipment inclusion을 검증한다.
- Diagnosis Runtime은 canonical `simulation_session_id`를 opaque reference로 반환한다.
- Maintenance와 agent는 session state, dataset id, replay timing, target eligibility를 해석하지 않는다.

향후:

- Product Result/Event 와 Replay Session 사이의 canonical mapping이 생긴 뒤에만
  `resolve_replay_session_for_event(source_event_id)` 같은 event-based resolver를 도입한다.
- Event Evidence Projection은 mutable replay/session state를 소유하지 않는다.

## User-facing Copy Examples

Overview:

- `우선 검토 1 · CMP-S03-L03-01 — 위험도 Critical, 설비 중요도 High, 최근 반복 이벤트 3건`
- `데이터 확인 필요 — 위험 수치를 표시할 수 없어 센서 수집 상태를 먼저 검토해야 합니다.`

Objects:

- `위험도: 향후 24시간 고장 위험이 78%로 Critical입니다. 고장 확정은 아닙니다.`
- `설비 중요도: High — 라인 중단 영향과 장시간 복구 가능성이 등록되어 있습니다.`
- `검토 우선순위: Urgent — 높은 위험도, 높은 설비 중요도, 최근 반복 이벤트가 근거입니다.`
- `정비 맥락: 마지막 정비 12일 전 · 최근 30일 유사 이벤트 3건 · 열린 WorkOrder 있음.`
- `현재 권고는 점검 요청입니다. 실제 결정과 작업 상태는 Operations에서 확인합니다.`

Operations:

- `시스템 권고: 점검 요청`
- `최근 사람 결정: 아직 기록되지 않음`
- `현재 가능한 액션: 점검 승인, 보류, 반려, 메모 추가`
- `이 설비는 위험도 Critical, 중요도 High이며 최근 반복 이벤트가 있어 우선 검토 대상으로 표시되었습니다.`

Report:

- `CMP-S03-L03-01은 현재 Critical 위험 상태이며, 높은 라인 중단 영향과 반복 이벤트 때문에 우선 검토 대상으로 분류되었습니다.`
- `시스템은 점검 요청을 권고했으며, 사람의 최종 결정은 아직 기록되지 않았습니다.`
- `이 요약은 선택 Event의 동일 snapshot을 사용합니다. 센서와 상세 근거는 Objects에서 확인할 수 있습니다.`

Agent draft:

- `초안 · 점검 전 확인 항목: 진동 센서 체결, 최근 정비 후 변화, 열린 WorkOrder 중복 여부.`
- `중복 가능 WorkOrder 1건이 있습니다. 새 작업을 만들기 전에 WO-2026-0142를 검토하세요.`
- `이 내용은 승인 요청 초안이며 작업 상태를 변경하지 않았습니다.`

## Delivery Plan

### PR A: UI/UX Responsibility And Adapter Contract

- frontend contracts에 nullable criticality, contexts, `review_priority`, gaps/warnings 추가.
- adapter 합성 제거.
- Objects를 canonical inspection owner로 재배치.
- Operations를 Decision Packet + governed action 중심으로 축약.
- Report를 narrative + evidence reference 중심으로 축약.
- current/history fixture contract에 맞는 frontend typecheck와 adapter tests 추가.

### PR B: Agent Coordination Research And Read-only Draft Contract

- read-only review packet contract 작성.
- agent input source refs와 limitation metadata 정의.
- mutation 금지 invariant 테스트 또는 문서 가드 추가.
- agent failure가 기존 UI/Report/Closed-loop workflow를 막지 않는 기준 정의.

### PR C: Agent-assisted WorkOrder Review Backlog

- WorkOrder appraisal.
- duplicate WorkOrder review.
- checklist/handoff/approval-request draft.
- HITL approval-required tool proposal은 별도 단계로 분리.

## Verification Plan

Contract and adapter:

- criticality missing -> `null`과 gap/warning 유지.
- missing downtime/runtime/context -> `0`, `false`, `normal`, `low`로 변환되지 않음.
- `review_priority` reason과 order가 backend payload와 동일함.
- recommendation, decision, WorkOrder, MaintenanceAction state가 교차 매핑되지 않음.
- `features[].current`와 `features[].history`가 contract shape 그대로 타입화됨.
- current가 history에 병합되지 않음.

Component:

- Objects에 risk, criticality, context, review priority, gap이 서로 다른 라벨로 표시됨.
- criticality `null`은 `확인 필요`로 표시되고 risk badge는 유지됨.
- Operations에는 full top-factor/provenance 복제 대신 Decision Packet과 canonical link가 표시됨.
- Report는 action control을 렌더링하지 않음.
- Agent draft는 `초안`과 source reference를 표시하고 domain state로 보이지 않음.

E2E:

- Overview -> Objects -> Operations -> Report가 동일 asset/event/snapshot을 유지.
- 화면 간 risk/criticality/recommendation/current decision 문구가 충돌하지 않음.
- backend priority 순서가 유지되고 frontend 재정렬이 없음.
- role별 `available_actions`와 disabled reason이 backend payload대로 표시됨.
- missing criticality/context/history가 explicit unavailable로 표시됨.
- raw producer/JSONL 또는 과거 fixture map-report 생성 로직이 재유입되지 않음.

## Out Of Scope

- Agent가 risk, criticality, review priority, authorization, WorkOrder/MaintenanceAction state를 계산하거나 변경하는 기능.
- MaintenanceAction start/complete, shutdown, replay control, `state_patch` 생성.
- Event Evidence Projection에 replay session state 추가.
- full graph-first PdM UX.
- 새 design system 도입.
- KQL/TSDB/graph DB 성능 비교.
- 구체적인 수리 procedure 생성.

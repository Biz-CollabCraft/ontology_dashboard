---
title: Decision Workspace 사건·관측 분리 최소 개선 계획
date: 2026-09-14
status: draft
type: feat
baseline_commit: 99179fe0d61e04a1256c936fbb8c8b9221365f53
evidence: docs/operations/2026-09-14-decision-case-evidence.md
---

# Decision Workspace 사건·관측 분리 최소 개선 계획

## 목적과 현재 판단

목표는 의사결정 속도·업무 편의를 높이는 것이다. 새로운 CMMS를 만들거나 버튼의 검증을 제거하는 작업이 아니다.

현재는 Product Result의 ID가 사실상 사건 식별자로 사용되고, 저장 시각에서 15분이 지나면 화면의 추천/업무가 함께 차단된다. 같은 event ID를 다시 읽어도 만료가 해소되지 않는다. 이를 아래 원칙으로 바꾼다.

> 관측은 계속 추가하고, 진행 중인 이상 건은 유지한다. 추천은 사용한 근거와 함께 보존하며, 실제 실행은 현재 서버 정책으로 재검증한다.

[증거 문서](../operations/2026-09-14-decision-case-evidence.md)의 E-01~E-04, R-01~R-04를 출발점으로 한다. 외부 제품의 이름이나 구조를 그대로 복제하지 않는다. 이 문서는 계획이며 아래 신규 객체/계약은 구현 완료 상태가 아니다.

## 1. 범위와 유지할 경계

유지:
- 공장 현황→이상 건 선택→Case Workspace.
- 기존 5단계 화면, 차트, 근거 출처/시각, 반응형.
- Decision Action 5개: MONITOR, REQUEST_ADDITIONAL_DIAGNOSIS, REQUEST_INSPECTION, REQUEST_MAINTENANCE, REVIEW_PLANNED_MAINTENANCE.
- 추천/대안 최대 2개. 부품 교체는 정비 작업 범위.
- Decision Agent 1개, read-only 도구, 사용자 검토 후 기존 deterministic backend API 실행.
- 서버 availableActions, 역할/권한, 근거 identity, scope, 중복/업무 상태 검증.
- Product Result 원본 불변, 최초 감지 근거 추적.

이번 범위 제외:
- LLM에 의한 사건 병합·종료·WorkOrder 생성.
- 복합 고장 상관분석, 자동 일정 최적화, 새로운 정비 실행 엔진.
- Reports 확장, 고정 기간의 정상 관측만으로 자동 완료.
- 관측 만료 일괄 해제, 미래 데이터 허용, fixture의 운영 데이터 대체.
- 관련 없는 프론트 재구성, 기존 업무 ID 일괄 변경.

## 2. 최소 데이터 모델과 연결 방식

기존 사건/요청 객체를 먼저 조사해 아래 책임을 충족하면 재사용한다. 그렇지 않을 때만 최소 저장 객체를 추가한다. 이름은 제안이다.

| 개념 | 필요한 정보 | 소유/불변 조건 |
|---|---|---|
| 이상 건 Case | case_id, tenant/project/workspace, asset_id, anomaly_key, 상태, version, opened_at, completed_at, 완료 사유/처리자 | backend가 생성·상태 전이 |
| 관측 연결 CaseEvidence | case_id, artifact_id, 연결 시각/사유, 최초 감지 또는 후속 관측, 연결 정책 버전 | 원본 센서/예측 복제 금지; 동일 연결 중복 방지 |
| 업무 연결 CaseWorkflowLink | case_id, 기존 WorkOrder/inspection/recommendation ID | 기존 owner API·원래 event/evidence lineage 보존 |
| 판단 Revision | case_id, case_version, 사용한 artifact/owner revision 집합, policy_version, 생성 시각, 추천 | 기존 DecisionSession/Proposal에 명시적 연결; 이전 결과 덮어쓰기 금지 |

중요:
- case_id, 기존 event_id, artifact_id를 단순 rename하지 않는다.
- 원래 요청의 event_id를 최신 예측 ID로 바꾸지 않는다.
- 명령이 최신 artifact를 요구하는 경우 기존 API가 받을 근거 계약을 명시적으로 확장한다. case_id를 legacy event_id 자리에 넣지 않는다.
- 최초 감지와 최신 위험 관측의 역할을 분리해 화면과 API 모두 표시한다.
- 예측 observed_at, 업무 recorded/updated_at, 추천 생성 시각, 실제 요청 시각을 구분한다.
- 관측 timestamp만 비교하지 않고 저장된 owner version/내용 변경도 추천 무효화에 반영한다.

## 3. 단순 연결 규칙과 상태

초기 제안:
1. 동일 tenant/project/workspace/설비 내에서만 연결한다.
2. 정확히 일치하는 anomaly_key와 진행 중인 건이 하나일 때 후속 이상 관측을 연결한다.
3. anomaly_key는 기존 rule/고장 유형/부위 식별자에서 deterministic하게 구성한다. 부위가 다른 이상을 합치지 않는다.
4. 명확한 분류 키가 없거나 후보가 여러 개면 자동 병합하지 않고 확인 필요로 남긴다.
5. 완료 후 다시 발생한 이상은 새 건으로 만들고 이전 건을 관련 이력으로 참조한다.
6. 동시 수집·중복 전달은 DB transaction과 idempotency/유일성 제약으로 처리한다.
7. 정상 관측은 같은 설비의 현재 상태/조치 후 확인 근거로 연결할 수 있지만, 동일 이상이 다시 발생했다는 횟수로 계산하지 않는다.

진행 중 반복을 얼마나 오래 같은 건에 연결할지, 장기 미처리 건을 어떻게 다룰지는 정책 확정 항목이다. 무기한 묶거나 임의의 15분 규칙을 넣지 않는다.

최소 저장 상태는 검토 중 / 처리 중 / 확인 대기 / 완료 / 취소 정도를 검토한다. 기존 5단계 화면은 이 상태와 실제 점검·정비 상태에서 투영한다. 별도의 5단계 상태를 중복 저장해 서로 어긋나게 만들지 않는다.

완료는 초기에는 담당자가 근거와 사유를 확인해 처리한다. 열린 작업이 있으면 완료를 막거나, 업무 owner의 명시적 취소/완료 처리를 먼저 요구한다. 센서 정상 복귀와 작업 완료는 별도 사실이다.

## 4. 근거 유효성과 액션 정책

다음은 구현 전에 owner와 확정할 제안이며 현장 안전 기준으로 확정된 값이 아니다. 15분 등 일괄 TTL을 새 기본값으로 채택하지 않는다.

| 판단/업무 | 필요한 근거 | 오래된 센서 관측의 처리 |
|---|---|---|
| MONITOR | 현재 위험을 해석할 관측, 점검 결과/보류 조건 | 오래된 값만으로 정상/안전 판단 금지; 최신 관측 확인 안내 |
| REQUEST_ADDITIONAL_DIAGNOSIS | 부족하거나 충돌하는 근거와 조사 대상 | 신선도 부족 자체가 추가 확인 사유가 될 수 있음; 현재 위험 확정 금지 |
| REQUEST_INSPECTION | 추적 가능한 최초 이상, 현재 업무/중복 상태, 요청 권한 | 최초 이상이 오래됐다는 이유만으로 일괄 차단하지 않음; 필요한 최소 근거는 정책 명시 |
| REQUEST_MAINTENANCE | 유효한 점검 결과, 현재 업무 상태, 작업 범위, 권한 | 센서 시간뿐 아니라 점검 이후 상태 변경·실행 조건을 평가 |
| REVIEW_PLANNED_MAINTENANCE | 점검, 생산 영향, downtime, 정비창, 부품, 인력, 동시 작업 | 자료별 as-of/미확인 표시; 검토 가능과 실제 작업 승인 가능을 구분 |
| 점검 결과 등록 | 배정/작업 상태/대상 일치, 작성 권한 | 최신 센서가 없더라도 해당 점검 기록을 남길 수 있게 검토 |
| 정비 승인·시작 | owner가 정한 최신 작업 조건, 권한, 중복, 낙관적 잠금 | 관련 조건 변경 시 재검토; 추천 클릭이 승인을 대체하지 않음 |

서버가 “추천 가능한가 / 사용자 검토 가능한가 / 실행 가능한가”를 별도로 평가한다. UI는 그 결과를 표시하며 새로운 액션을 발명하지 않는다.

제안하는 평가 결과:
- 상태: actionable / review_required / blocked / unavailable.
- 구조화된 사유 코드와 영향받는 action ID.
- recovery: retry_read / refresh_proposal / review_new_evidence / await_data / request_role_action.
- 기준: case_version, evidence/owner revisions, policy_version.
- 각 사유에는 사용자가 이해할 안내를 연결한다. role 오류와 evidence 만료를 한 문장으로 합치지 않는다.

기존 API 소비자를 조사한 뒤 additive field 또는 명시적 v2 계약으로 도입한다. route/field 이름을 이 문서만으로 확정하지 않는다.

## 5. 재판단과 승인 UX

- 조회 실패: “다시 불러오기”. 같은 조회를 재시도하고 실패 원인을 보존한다.
- 같은 사건의 새 관측/점검 결과: “새 근거로 재판단”. 변경된 근거를 요약하고 새 Proposal을 만든다.
- 관측 미수신: “관측 갱신 대기”. 현재 값으로 판단할 수 없는 범위를 표시하되 무관한 업무까지 잠그지 않는다.
- 다른 이상/완료 후 재발: 별도 건임을 알리고 명시적으로 이동한다.
- 담당 표시: 요청자·실제 수행자·현재 사용자 권한을 구분한다. 서버 command policy와 동일한 역할 정의를 사용한다.

차트는 계속 갱신한다. 사용자가 검토 중인 Proposal은 사용한 근거 묶음을 유지한다. 관련 점검 결과, 위험 등급, 작업 상태, 중요한 계획 조건이 바뀌면 “재검토 필요”를 표시한다. 모든 센서 샘플 도착마다 검토 화면을 초기화하지 않는다.

승인 직전 backend가 예상 case/owner revision과 현재 상태를 비교한다. 불일치하면 명확한 conflict 응답을 주고 다시 검토하게 한다. AI는 mutation을 호출하지 않는다.

## 6. 구현 순서와 완료 조건

### 단계 0 — 계약·정책 확정
- 기존 event/Case 유사 객체, WorkOrder event FK, schema consumer, 권한 매핑 조사.
- 참고: `docs/operations/decision-agent-recommendation-semantics.md`, ADR-004, maintenance service, decision session service.
- E-01/E-02를 재현하는 테스트를 먼저 추가한다.
- 산출물: 객체 재사용/추가 결정, anomaly_key 규칙, 액션 정책표, 변경 소비자 목록.
- 종료 조건: 과거 근거 보존과 현재 실행 검증이 충돌하지 않는 계약을 합의한다.

### 단계 1 — 최소 Case와 관측 연결
- 필요한 경우 PostgreSQL/SQLite 대칭 migration, repository, scope 검증 추가.
- 예측 수신 owner 경로에 멱등적인 연결 단계 추가. 원본 생성 파이프라인을 UI가 읽지 않는다.
- 기존 작업은 원래 event ID를 유지하고 연결 테이블로 Case에 귀속한다.
- 과거 사건을 추측해 한꺼번에 병합하지 않는다. 확인 가능한 legacy 단위로 연결 후 새 관측부터 정책 적용.
- 종료 조건: 같은 이상 반복·다른 이상·완료 후 재발·동시 요청 테스트 통과.

### 단계 2 — 서버 판단 계약 통일
- `decision_session_service.py`, `decision_workflow_context.py`, `decision_tools.py`, `decision_policy.py`에서 case/evidence revision 사용.
- `maintenance/service.py`, `maintenance/decision_context.py`에서 동일한 사실과 액션별 정책 사용.
- `asset_detail_read_adapter.py:data_status`의 신선도는 관측 상태로 유지하고 사건 전체 권한으로 오용하지 않음.
- 원본 schema를 바꾸지 않고 read-model/decision 계약의 소비자를 함께 갱신.
- 종료 조건: 근거 정합성·추천 허용·실행 허용의 차이가 API에 명시적으로 설명된다.

### 단계 3 — Workspace 복구 UX
- `decisionProposalAdapter.ts`, `DecisionProposalPanel.tsx`, `DecisionWorkspaceApplication.tsx`, `decisionWorkspaceModel.ts` 수정.
- 새 관측 연결과 새 사건 이동을 구분; 상태별 복구 버튼; 담당자 표시 수정.
- 관련되지 않은 실시간 업데이트로 Human review가 사라지지 않게 함.
- 종료 조건: 서버 사유와 화면 사유 일치, 최대 2개 Decision Action, 반응형 유지.

### 단계 4 — 검증 및 점진 적용
- 기존 endpoint/URL의 compatibility test와 새 case 경로를 모두 검증.
- 기존 evidence ID를 보존하는 feature flag로 새 경로를 먼저 활성화.
- shadow 비교는 읽기만 수행하고 중복 WorkOrder/Case 생성 경로를 만들지 않음.
- 적용 후 오류 시 새 UI/연결 생성을 중지하되 기존 기록은 유지한다. DB 전체 reset이나 원본 재작성으로 롤백하지 않는다.
- endpoint 완전 전환과 legacy 제거는 별도 결정.

## 7. 필수 검증 시나리오

| ID | 시나리오 | 반드시 확인할 결과 |
|---|---|---|
| T01 | 같은 이상 반복 및 중복 메시지 | 같은 진행 건에 참조 추가; Case/WorkOrder 중복 없음 |
| T02 | 다른 tenant/설비/부위/이상 또는 불명확한 키 | 교차 연결 차단; 애매한 자동 병합 없음 |
| T03 | 미래·지연·역순 관측 | 미래 제외, 지연 관측이 최신 상태를 덮지 않음, 원본 시각 보존 |
| T04 | 15분 이상 지난 진행 건에서 점검 결과 등록 | 단순 TTL로 기록 작업 차단하지 않음; 배정/상태/권한 검증 유지 |
| T05 | 만료 안내에서 복구 버튼 | 같은 실패 반복 대신 명시된 회복 경로로 진행 |
| T06 | 점검 완료→같은 건 재판단 | owner 결과가 반영된 새 Proposal, 이전 근거/추천 보존 |
| T07 | 정상 관측 한 번 도착 | 진행 중 작업을 자동 취소/완료하지 않음 |
| T08 | 완료 후 재발 | 새 건과 이전 건의 관련 이력 추적 |
| T09 | 검토 중 중요한 상태 변경→승인 | 구버전 실행 거절, 재검토 사유 표시; 이중 실행 없음 |
| T10 | 낮은 권한/URL role 조작 | 추천·명령 권한 확대 없음, 요청/수행 담당 표시 일치 |
| T11 | 관련 없는 센서 샘플 갱신 | 차트 갱신, 검토 중 선택 유지 |
| T12 | API 장애/근거 누락 | mock 대체 없음, 명확한 unavailable/retry |
| T13 | legacy URL·진행 중 WorkOrder | 기존 event/evidence 참조로 이력 재조회 가능 |

검증 단계 구분:
1. Unit/contract: frozen clock으로 시간을 진행시켜 검증. 실제 15분 대기나 고정 미래 날짜에 의존하지 않음.
2. Fixture-backed E2E: 1440/768/390, 이상 건→판단 조건→추천→사용자 검토→기존 실행 UI, 가로 넘침 없음.
3. Disposable local DB integration: 실제 API로 요청→담당자 수락/시작→결과 등록→동일 Case 재판단→승인 전 재검증. 데이터는 전용 DB에만 생성.
4. 기존 로컬 DB smoke: 읽기 및 추천 조회만. 최종 업무 mutation 성공으로 집계하지 않음.
5. 현장 적용/LLM 품질 검증은 별도이며 위 통과로 대체하지 않음.

성공 기준:
- 복구 불가능한 ‘다시 판단’ 반복이 T05에서 없어짐.
- 판단/실행 차단 사유에 action과 recovery가 존재하고 UI에 동일하게 표시됨.
- 자동 연결의 교차 scope 오류·중복 생성이 검증 시나리오에서 0건.
- 중요한 변경 후 구버전 승인 성공이 0건.
- 판단 화면 진입→검토 완료의 시간, 클릭 수, API 실패/보류/충돌 사유를 기준 버전과 같은 시나리오에서 측정.
- 성능·업무 시간 개선율은 현재 미측정. 테스트 통과만으로 절감 수치를 만들지 않는다.

## 8. 확정 전 남은 결정

| 항목 | 임시 방향 | 확정 시점 |
|---|---|---|
| 기존 객체 재사용 또는 Case 추가 | 기존 스키마 책임 조사 후 최소 추가 | 단계 0 |
| anomaly_key 구성과 진행 건 연결 기간 | 명시된 rule/유형/부위 기반, 모호하면 자동 병합 금지 | 자동 연결 전 |
| 액션별 신선도·중요 변화 기준 | 센서·점검·계획 데이터별 구분; 일괄 TTL 폐기 여부 검토 | 단계 2 |
| 완료 담당자와 재발 정책 | 명시적 사용자 확인, 재발은 새 건 | 상태 전이 구현 전 |
| 계획 검토/추가 진단/모니터 기록 owner API | 없는 실행 계약은 만들었다고 표시하지 않음 | 해당 mutation 구현 전 |
| 추천 이력 영속화 범위·보관 기간 | 근거 참조/정책/사용자 선택 감사에 필요한 최소 데이터 | 단계 1~2 |

이번 작업의 산출물은 증거와 계획 두 문서다. 제품 코드·DB·배포 변경, commit/push, 개인 memory 갱신은 포함하지 않는다.

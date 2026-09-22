# Decision Workspace 통합 계약 검토

검토일: 2026-09-14. 개인 AI dev 검토 기준을 적용한 로컬 통합 기록이다. 배포·LLM 성능·실제 정비 실행 완료를 의미하지 않는다.

## 1. 참조한 설계·기준

- 개인 AI dev의 Dashboard PR Review Trigger, Review Context, Architecture Risk Register, Verification Notes, Permission Boundary
- docs/ai-code-review-context.md
- contracts/README.md, contracts/schemas/README.md
- docs/operations/decision-agent-recommendation-semantics.md
- docs/operations/local-briefing-environment.md
- 기존 operational decision support 계획과 Product Result / Event Evidence trust boundary
- 원격 기준: origin/codex/decision-agent-mvp `340c1a18` (확인 시 origin/main `f8fca067` 포함)
- 현재 checkout 기준: detached HEAD `5142c8b9`. 원격 변경을 --no-commit으로 병합하고 기존 dirty 변경을 재적용했다. 다른 worktree의 미커밋 수정은 가져오지 않았다.

## 2. 현재 구현과 목표의 차이 및 판정

| 검토 항목 | 발견한 차이 | 조치 / 판정 |
|---|---|---|
| 추천 연결 | 프론트 loadDecisionProposal이 항상 unavailable | 실제 POST/GET DecisionSession 응답을 검증·변환. Verified / Pass |
| 사건 바인딩 | Agent DI가 asset fixture packet을 사용 | 선택된 runtime event와 organization/project/workspace로 조회. Verified / Pass |
| 역할 | 요청 role을 실제 principal 역할과 대조하지 않음 | 생성 시 403 검증 추가. 추천 허용과 mutation 권한 분리. Verified / Pass |
| snapshot·만료 | 프론트 요구 필드가 응답에 없음 | 서버가 원본 packet basis와 5분 만료를 제공. 생성 전후 및 조회 시 source 변화 검사. Verified / Pass |
| 판단 보류 | nullable recommended_action / abstained 미지원 | 추천 없음·보류 사유를 표시하고 실행 버튼 없음. Verified / Pass |
| 실행 연결 | 프론트의 가상 policy_guard execution | 서버가 기존 Maintenance decision_context에서 허용된 실제 command/target만 연결. Verified / Pass |
| 출처 | fact summary/source_refs/owner/as_of 형태 불일치 | 출처·관측 시각을 보존하여 UI 변환. Verified / Pass |
| 산문 grounding | SOP가 없어도 “점검 기준 확인”으로 표현 | 위험 상태 및 제공된 점검 기록 범위로 표현을 제한. 회귀 테스트 추가. Verified / Pass |
| 센서 계약 | composer가 schema에 없는 합성 표시 bands 추가 | 해당 필드 제거, 실제 sensor history와 기존 위험도 시각화 유지. Verified / Pass |
| 진행 단계 | 새 점검 종료/추가 데이터 확인 상태 미매핑 | 5단계 내 해당 상태 매핑. Verified / Pass |
| Session 영속화 | 메모리 저장 | 그대로 메모리이며 만료 정리 추가. DB 영속화 완료 주장 금지. Partially Verified / Risk |
| LLM 판단 | 실행 서버가 deterministic 기본 설정 | LangGraph + deterministic 정책 경로만 실제 검증. LLM 추천 연결/정확성은 Not Proven |

확인된 위험 상태·생산 수치·점검 결과는 producer/owner read model에서 읽는다. 프론트는 미확인 값을 0/정상으로 채우거나 availableActions로 추천을 만들지 않는다. Agent의 추천 허용은 WorkOrder 생성·승인 권한이 아니다.

## 3. 수정 범위

원격 통합 파일과 이번 계약 연결 수정을 구분한다. 다수의 staged 파일은 원격 통합분이며 새로운 frontend 전체 리팩터링이 아니다.

주요 계약 연결 수정:
- systems/backend/app/dependencies.py
- systems/backend/app/operations/decision_session_service.py
- systems/backend/app/operations/decision_support_contract.py
- systems/backend/app/operations/decision_support_agent.py
- systems/backend/app/operations/router.py
- systems/backend/app/operations/asset_detail_view_model.py
- systems/frontend/src/api.ts
- systems/frontend/src/features/operations/api/operationsApi.ts
- systems/frontend/src/features/operations/decision/decisionProposalAdapter.ts
- systems/frontend/src/features/operations/decision/DecisionProposalPanel.tsx
- systems/frontend/src/features/operations/decision/DecisionWorkspaceApplication.tsx
- systems/frontend/src/features/operations/decision/decisionWorkspaceModel.ts
- systems/frontend/src/features/operations/overview/RoleFactoryStandalone.tsx
- 관련 session/DI/fixture isolation/프론트 unit 및 E2E 테스트

기존 runtime cadence 수정, canonical Evidence 차단, workflow panel, 반응형·센서 시각화 변경은 보존했다. 충돌 구간은 원격 병합 11개 파일, stash 재적용 3개 파일에서 조정했다.

## 4. 구현된 흐름

공장 현황 → 사건 선택 → 해당 canonical evidence의 DecisionSession 생성 → 실제 tool call 기록 및 판단 조건 → 추천 1개/대안 최대 1개 → 사용자 검토 → 기존 업무 요청 양식 → 사용자가 최종 승인.

최초 생성 이후 같은 세션은 GET으로 조회한다. 근거 변경·만료·권한 변경은 기존 선택과 요청 양식을 무효화한다. 연결 실패/만료 시 다시 판단할 수 있다. 서버가 단계별 실시간 스트림을 제공하는 것처럼 가짜 진행을 만들지 않는다.

## 5. Closed-loop 연결

- REQUEST_INSPECTION → 서버가 허용한 request_inspection_work_order
- REQUEST_MAINTENANCE → 서버가 허용한 create_operations_manual_recommendation
- backend binding과 현재 detail.availableActions의 action/target/권한이 모두 맞아야 기존 양식으로 이동한다.
- 최종 mutation은 기존 backend API가 재검증한다.
- calculate_maintenance_cost는 정비 비용 분석이며 계획 정비 판단과 동일시하지 않는다.
- 부품 교체는 정비 요청의 작업 범위다.

## 6. 아직 검토 화면에 머무는 부분

MONITOR / REQUEST_ADDITIONAL_DIAGNOSIS / REVIEW_PLANNED_MAINTENANCE는 추천·선택·검토를 지원한다. 해당 결정 기록이나 진단 요청, 계획 확정의 독립 mutation 계약은 구현하지 않았다. 저장·요청 완료로 표시하지 않는다.

계획 검토의 생산 영향·정지시간·작업창·부품·인력·동시 작업 위치는 유지하지만, 없는 운영 데이터를 채워 넣지 않는다. 운영 context 테이블이 추가됐다는 사실만으로 내용이 적재됐다고 표현하지 않는다.

## 7. Unit / 계약 검증

- frontend 전체: 313 passed / 61 files
- 마지막 Decision Workspace 변경 후 focused: 47 passed / 5 files
- backend Decision / 기존 Operational Decision API / architecture: 137 passed, 2 opt-in live tests skipped
- 마지막 session·Agent·권한·architecture: 37 passed
- 병합 후 Artifact ViewModel / 기존 summary / 정책 포함 검사에서 86 passed를 확인했고 나머지 session 문제는 이후 수정·재검증했다.
- fixture DI가 기본 로컬 SQLite DB를 조회하려던 테스트는 명시적으로 격리했다.
- snapshot 없음/불일치, 응답 밖 action, 출처 없는 fact, mutation_attempted, role 위조, 만료, 조사 도중 근거 변화, null 추천을 검사했다.

## 8. Build

TypeScript 및 production build 통과. 초기 JavaScript 260.29 KiB / 310 KiB budget. 기존 factory-status-original의 non-module support.js 번들 경고는 남아 있다.

## 9. E2E

- fixture-backed HTTP contract verification: 2 passed. 프론트 모듈을 교체하지 않고 실제 HTTP transport/decoder를 통과한다.
- real local backend integration: 2 passed. CNC / compressor의 실제 DB 결과로 추천 표시·검토를 확인하고 compressor의 기존 점검 요청 양식까지 확인했다.
- 1440 / 768 / 390에서 horizontal overflow 없음.
- 실제 WorkOrder 생성 버튼은 누르지 않았으며 maintenance mutation request 0개를 확인했다.

## 10. 실제 backend 검증과 fixture 구분

실제 PostgreSQL에서 최신 100개 설비, canonical detail, 위험 이력, manager/engineer 정책 조회 2 tests passed. 두 실제 사건에서 세션 생성·재조회 200 및 같은 session id를 확인했다. 확인 시 CNC는 MONITOR, compressor는 REQUEST_INSPECTION을 반환했고 후자는 기존 업무 대상 binding이 있었다.

이는 로컬 simulation 데이터의 실시간 수집·추론 경로 검증이다. 현장 설비 데이터나 LLM 판단 품질, 최종 업무 mutation, 배포 검증이 아니다.

## 11. 남은 backend 연동 포인트

- DecisionSession / 사용자 선택 이력의 DB 영속화 및 idempotency/concurrent creation
- 조사 중 단계별 비동기 상태/stream 계약
- monitor 기록 / 추가 진단 요청 / 계획 검토 결과의 owner API
- 선택한 사건 시점에 유효한 production/readiness owner 데이터
- configured LLM 모드 및 독립 grounding/정확성 평가
- 최종 승인 mutation은 별도의 disposable DB 시나리오로 검증할 것

## 체크포인트와 실행 상태

기존 dirty/untracked 31개 파일을 tar·binary diff·SHA-256 manifest로 보존했고, stash `43d981c9c76f8a65fd87550fa160a6b75d416a2b`도 삭제하지 않았다. HEAD는 기존 `5142c8b9`, MERGE_HEAD는 `340c1a18`이며 commit/push하지 않았다.

로컬 DB에는 변경 전 pg_dump를 보존한 뒤 0049~0051을 적용했다. Git reset은 DB migration을 되돌리지 않으므로 파일 복구와 DB 복구는 구분해야 한다. 운영 DB/다른 worktree는 변경하지 않았다.

개발 화면은 3101, backend는 8112. 기존 Docker named volume과 저장된 prediction/evidence를 유지한 채 로컬 애플리케이션을 재시작했다.

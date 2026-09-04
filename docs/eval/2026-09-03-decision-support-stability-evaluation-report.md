# Decision Support Stability Evaluation Report

## Candidate

- Candidate SHA: `6bd2f7c2`
- Evaluation date: 2026-09-03
- Overall decision: **passed for local synthetic Decision Support boundary**
- Current-candidate live LLM quality: **not_measured — external transmission approval required**
- Cross-owner Closed-loop E2E: **blocked_by_integration**

## Scope

이 평가는 개인 소유 범위인 `Evidence Packet -> AI Brief와 작업 요청 추천`의 API/UI vertical slice와
그 하위 운영 맥락 수집, 관계 해석, 결정론적 Impact Simulation, 시간 재검증, SQLite 저장 경계를 다룬다.

실제 제조 시스템 연결, 사람 승인 이후 정비 실행, `gen_data` overlay, Generator 재예측은 완료로
주장하지 않는다.

## Context and Decision Quality

| 항목 | 결과 | Evidence State |
|---|---:|---|
| 운영 맥락 시나리오 | 3/3 통과 | Verified synthetic |
| 역할별 truth consistency | 통과 | Verified synthetic |
| 관계 source/version/as-of 완전성 | 통과 | Verified synthetic |
| quality hold의 not-calculable 보존 | 통과 | Verified synthetic |
| part blocker의 계획정비 차단 | 통과 | Verified synthetic |
| 현재 후보 live LLM 품질 | 미측정 | Not measured |
| 사람 usefulness review | 미측정 | Not measured |

LLM 품질과 실행 신뢰성은 하나의 총점으로 합치지 않는다.

## Temporal and Evidence Consistency

총 96-run 시간 fault simulation 결과:

| Arm | Mismatch detection | Stale output block | Simulated stale side-effect allow |
|---|---:|---:|---:|
| A Direct LLM | 0% | 0% | 100% |
| B Evidence Packet + LLM | 0% | 0% | 100% |
| C Current Workflow | 100% | 100% | 0% |

- fresh-state recovery: 8/8
- 운영 맥락 temporal validation: 3/3
- historical replay는 wall-clock이 아니라 고정된 `decision_as_of`를 기준으로 평가
- GS-004 Evidence와 운영 맥락 fixture를 2026-08-01 기준으로 정렬
- 서로 다른 schema의 fixture가 동일 directory glob에 섞이던 문제를 adapter schema guard로 차단

A/B의 side-effect allow 값은 실제 command 실행이 아니라 acceptance boundary simulation이다.
C의 mismatch 탐지와 재조회는 production snapshot guard 로직을 사용한다.

## Execution Reliability

서비스·SQLite 신뢰성 11개 필수 시나리오가 모두 통과했다.

- 정상 Brief와 workflow run 저장
- 동일 identity 저장본 재사용
- active conflict 격리와 stale recovery 구분
- provider fallback 저장
- bounded retry
- timeout과 malformed external response 분리
- snapshot mismatch side-effect 차단
- identity 일치
- 미측정 token/cost의 null-safe 처리
- side-effect count 불변

## API, UI, and E2E

| 계층 | 결과 | Evidence State |
|---|---:|---|
| Backend targeted regression | 83 passed | Verified |
| Playwright targeted | 4 passed | Verified local |
| Browser -> FastAPI -> Agent -> SQLite -> UI | 1 scenario passed | Verified local synthetic |
| Manager 관계·선택지 표시 | 통과 | Verified route-isolated |
| Engineer read-only | 통과 | Verified route-isolated |
| Partial gap/not-calculable | 통과 | Verified route-isolated |

unmocked 시나리오는 실제 FastAPI와 SQLite를 통과한다. 나머지 3개 UI 상태 시나리오는 응답 상태를
고정하기 위해 route-isolated 방식으로 검증했다.

## Failure Isolation

- external timeout: `external_api_timeout`
- malformed response: `external_api_malformed_response`
- 두 실패 모두 해당 domain fact 혼입 없이 격리
- mutation attempts: 0
- generated recommendations: 0
- WorkOrder/MaintenanceAction/command side-effect count: unchanged in reliability scenarios

## Claim Boundary

발표에서 사용할 수 있는 표현:

> 로컬 synthetic 환경에서 Evidence와 운영 맥락의 시점을 고정하고, 실제 API와 SQLite를 거쳐
> Decision Support Brief가 표시되는 경로를 검증했습니다. 96-run 시간 fault simulation에서 전체
> workflow는 mismatch를 100% 탐지하고 stale 저장을 100% 차단했으며, 서비스·DB 장애 시나리오
> 11개도 모두 통과했습니다.

사용하면 안 되는 표현:

- 운영 환경 안정성이 검증됐다
- 실제 MES/CMMS/WMS/QMS가 연결됐다
- AI 정확도 또는 사람 usefulness가 현재 후보에서 검증됐다
- 전체 Closed-loop E2E가 완료됐다
- 생산 손실 또는 다운타임을 줄였다

## Artifacts

These raw JSON outputs are local generated artifacts ignored by Git; regenerate them with the decision-support evaluation scripts when needed.

- `tests/eval/results/operational_decision_support_final-20260903-6bd2f7c2.json`
- `tests/eval/results/decision_support_reliability_20260903_6bd2f7c2.json`
- `tests/eval/results/decision_support_temporal_20260903_6bd2f7c2.json`
- `tests/eval/results/operational_decision_e2e_20260903_6bd2f7c2.json`

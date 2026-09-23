# Decision Workspace durable workflow redesign

작성일: 2026-09-23  
대상 ref: `origin/codex/decision-workspace-integration`  
대상 HEAD: `891f4567542b4a6d1af7fbef0d2f0f3525f98132`

## 결론

현재 구현의 문제는 0.9초 lease가 짧다는 사실 하나가 아니다. HTTP POST가 LangGraph 실행 전체를 동기적으로 붙잡고, 애플리케이션 lease·checkpoint·재개 판단이 한 흐름에 결합되어 있다. 그 결과 heartbeat가 소유권을 잃는 순간 최종화 전 실행 전체가 409로 끝나며, 요청자는 자동 재개 경로를 갖지 못한다.

근본 해결은 다음 계약으로 바꾼다.

> 요청은 durable run을 등록하고, worker가 단계별 checkpoint를 갱신하며, lease가 사라지면 다른 worker가 만료된 checkpoint에서 안전하게 재개한다. 최종 결과만 외부에 게시하고, 모든 evidence/context binding과 mutation 금지는 서버가 판정한다.

lease를 30초로 늘리는 것은 운영 파라미터 보정일 뿐이며, 이 설계의 대체물이 아니다.

## 현재 구조에서 확인된 결함

현재 `DurableDecisionRunner.run()`은 다음을 한 번에 수행한다.

1. PostgreSQL row를 claim한다.
2. parallel tool read를 수행한다.
3. 동기 interpreter를 실행한다.
4. final proposal을 만들고 같은 HTTP 요청 안에서 반환한다.
5. `finally`에서 lease를 release한다.

이 구조에는 네 가지 문제가 있다.

- 긴 interpreter 동안 worker가 계속 lease를 보유해야 한다. heartbeat 오류가 어떤 예외인지 구분하지 않고 즉시 `lost`로 표시한다.
- `interpret` 결과는 interpreter가 끝난 뒤에야 저장된다. 중간에 소유권을 잃으면 graph가 `final`에 진입하기 전에 중단된다.
- repository의 `rowcount=0`은 만료, 다른 owner의 fencing, DB 시계 차이, 일시적 DB 오류를 구분하지 않는다.
- POST가 실행과 결과 전달을 동시에 담당하므로, lease를 잃은 뒤 durable record를 재개하는 별도 scheduler/resumer 계약이 없다.

따라서 이전 P0의 409는 안전한 중단이라는 점은 보여주지만, durable workflow가 끝까지 복구된다는 증거는 아니다.

## 새 상태 머신

API가 보는 상태와 worker가 보는 단계는 분리한다.

| API 상태 | 내부 단계 | 의미 |
| --- | --- | --- |
| `QUEUED` | `created` | 요청과 evidence binding 저장 완료 |
| `RUNNING` | `gather` | tool attempt 예약 또는 실행 중 |
| `RUNNING` | `interpret` | evidence snapshot에 대한 해석 중 |
| `RUNNING` | `finalize` | 서버가 결과와 policy gate를 계산 중 |
| `READY_FOR_REVIEW` | `completed` | proposal 저장 완료, mutation은 수행하지 않음 |
| `ABSTAINED` | `completed` | 근거 부족/정책 차단으로 안전하게 종료 |
| `STALE` | `completed` | context binding 불일치로 게시하지 않음 |
| `RETRYABLE_FAILURE` | `recoverable_error` | lease/transport/일시 DB 문제, resumer 대상 |
| `FAILED` | `terminal_error` | 재시도해도 안전하지 않은 계약 오류 |

허용 전이는 다음뿐이다.

```text
QUEUED
  -> RUNNING:gather
  -> RUNNING:interpret
  -> RUNNING:finalize
  -> READY_FOR_REVIEW | ABSTAINED | STALE
  -> RETRYABLE_FAILURE -> RUNNING:<saved phase>
  -> FAILED
```

각 전이는 단조 증가하는 `revision`을 가진 compare-and-swap로 저장한다. worker는 현재 owner와 revision을 모두 만족할 때만 상태를 갱신할 수 있다.

## API 계약

### POST

`POST /decision-sessions`는 더 이상 긴 LangGraph 실행을 동기로 기다리지 않는다.

- 새 요청: `202 Accepted`, `decision_session_id`, `status=QUEUED`
- 같은 request key가 완료됨: 저장된 결과를 반환하거나 `200`으로 idempotent replay
- 같은 request key가 실행 중: `202`와 현재 상태
- 동일 key의 binding/context가 다름: `409 decision_session_context_changed`

### GET

GET은 저장된 durable record만 읽는다.

응답에 최소한 다음을 포함한다.

- `status`
- `phase`
- `revision`
- `attempt`
- `updated_at`
- `last_heartbeat_at`
- `retry_after`
- 완료 시에만 `proposal`

RUNNING 상태에서는 proposal을 절대 반환하지 않는다. GET은 worker를 대신 실행하지 않는다.

### Worker/resumer

worker는 다음 순서로 동작한다.

1. `QUEUED` 또는 lease가 만료된 `RUNNING` row를 DB clock으로 claim한다.
2. owner token과 revision을 발급받는다.
3. 저장된 phase부터 graph를 재개한다.
4. 각 외부 호출 전후로 attempt ledger와 checkpoint를 저장한다.
5. 완료 결과를 CAS로 게시한다.
6. lease를 정상 해제한다.

별도 resumer가 일정 주기로 만료된 row를 claim한다. 프로세스 재시작은 API 요청 재전송에 의존하지 않는다.

## 저장소 계약

기존 `state_json`은 유지하되, 조회와 fencing에 필요한 필드를 명시적 컬럼으로 승격한다.

- `status`
- `phase`
- `revision`
- `lease_owner`
- `lease_until`
- `last_heartbeat_at`
- `attempt`
- `last_error_code`
- `last_error_at`
- `binding`
- `state_json`
- `result_json`
- `updated_at`

필수 repository 연산은 다음과 같다.

- `create_or_get(request_key, binding)`
- `claim(worker_id, now)`
- `renew_lease(worker_id, expected_revision)`
- `save_checkpoint(worker_id, expected_revision, phase, state)`
- `publish_result(worker_id, expected_revision, result)`
- `mark_recoverable_error(worker_id, expected_revision, code)`
- `load_for_read(identity)`

각 연산은 결과를 예외 문자열로 표현하지 않고 명시적 결과로 반환한다.

- `CLAIMED`
- `ALREADY_COMPLETED`
- `BUSY`
- `FENCED`
- `LEASE_EXPIRED`
- `TRANSIENT_DB_ERROR`

`FENCED`는 즉시 중단한다. `TRANSIENT_DB_ERROR`는 lease가 아직 유효한지 확인할 수 없으므로 외부 side effect를 더 실행하지 않고 `RETRYABLE_FAILURE`로 남긴다. 임의의 DB 예외를 곧바로 “정상 lease 상실”로 취급하지 않는다.

DB 시계는 claim, renew, save에서 모두 사용한다. 진단을 위해 각 실패 시점에 DB `clock_timestamp()`, 읽은 `lease_until`, `lease_owner`, expected revision을 구조화해 기록한다.

## 단계별 checkpoint

### Gather

- tool call을 실행하기 전에 `attempt_ledger`에 `reserved`를 저장한다.
- 완료 결과와 `completed_at`을 저장한 뒤에만 다음 tool을 실행한다.
- `reserved`가 남은 채 프로세스가 죽으면 다음 worker가 해당 attempt를 retry한다.
- 이미 완료된 tool result는 source binding이 같으면 재호출하지 않는다.

### Interpret

interpret 시작 직전에 다음 checkpoint를 저장한다.

```json
{
  "phase": "interpret",
  "interpretation_status": "running",
  "input_evidence_binding": "...",
  "provider_request_fingerprint": "..."
}
```

interpreter가 반환하면 결과를 먼저 저장한다.

```json
{
  "phase": "interpret",
  "interpretation_status": "completed",
  "interpretations": [...],
  "provider_response_fingerprint": "..."
}
```

그 후에만 `finalize`로 전이한다. interpreter 중단 시 재개 worker는 같은 request fingerprint와 cache/ledger를 사용해 중복 호출을 판정한다.

### Finalize

finalize는 외부 mutation을 수행하지 않는다.

1. policy gate
2. evidence binding 재검증
3. proposal 계산
4. result payload 저장
5. `READY_FOR_REVIEW` 또는 `ABSTAINED/STALE` 게시

결과 저장과 API 상태 전이는 하나의 CAS transaction으로 묶는다. 저장된 결과가 있으면 이후 replay는 graph를 다시 실행하지 않는다.

## Lease와 heartbeat 정책

- 기능 경로의 lease는 예상 최대 stage 시간보다 충분히 길게 설정한다. 30초는 기본값일 수 있지만 보장값이 아니라 운영 설정이다.
- heartbeat 주기는 `min(lease/3, 5s)`를 유지하되, DB 연결 오류에는 제한된 retry/backoff를 적용한다.
- retry 중에는 새로운 tool/provider 호출을 시작하지 않는다.
- lease owner가 다르거나 revision이 바뀌었으면 fencing으로 확정한다.
- lease 유효성을 판정할 수 없는 상태는 안전하게 `RETRYABLE_FAILURE`로 남기고 resumer가 재획득한다.
- lease stress는 별도 실험으로 유지한다. 0.9초 lease를 정상 내구성 acceptance에 섞지 않는다.

## LangGraph의 역할

LangGraph는 gather, interpret, finalize의 실행 그래프와 단계 관찰을 담당한다. API 상태, evidence binding, lease, retry budget, mutation authorization의 최종 권한은 애플리케이션 저장소에 둔다.

현재처럼 애플리케이션 소유 state를 유지할 경우, LangGraph native checkpointer를 두 번째 진실 공급원으로 추가하지 않는다. native checkpointer를 채택하려면 API 상태 row와 graph state의 commit/recovery 관계를 먼저 정의하고, 이중 저장소 불일치 테스트를 추가해야 한다.

## 구현 순서

1. migration: 명시적 상태/phase/revision/error/heartbeat 컬럼과 attempt ledger 추가
2. repository: typed result, CAS save, owner/revision fencing, DB-clock diagnostics
3. runner: stage checkpoint, transient lease retry, recoverable failure, idempotent provider ledger
4. service/API: POST 등록 `202`, GET durable read, completed replay, context mismatch
5. worker/resumer: queued/expired run claim 및 fresh-process resume
6. tests: state transition/property tests, heartbeat fault injection, fencing, process kill/resume
7. measurement: 30초 lease 기능 P0와 0.9초 lease stress를 분리해 재실행

## Acceptance gate

다음 조건을 모두 만족해야 durable workflow를 통과로 판정한다.

- 10초 synchronous interpreter 3회가 모두 `READY_FOR_REVIEW` 또는 안전한 `ABSTAINED`로 종료
- 동시 GET은 모두 200이며 RUNNING 중 proposal을 반환하지 않음
- 완료 replay는 추가 tool/interpreter/provider 호출 0회
- interpreter 도중 process kill 후 fresh worker가 재개
- 완료된 tool attempt는 재호출하지 않음
- 미완료 attempt는 정책에 따라 정확히 한 번 retry
- old worker의 checkpoint/result 저장은 모두 fencing됨
- evidence packet 변경 시 결과 게시 없이 `STALE` 또는 409
- business digest와 mutation tables는 불변
- DB 일시 오류, heartbeat 오류, lease expiry, fencing이 서로 다른 관찰 가능한 상태를 남김
- API, worker, repository, LangGraph state가 서로 다른 결과를 게시하지 않음

## 보고 범위

이 문서는 설계와 구현 순서를 정의한다. 아직 제품 소스에 이 설계를 적용하거나 P0를 재실행하지 않았다. 이전 측정 결과는 [2026-09-23 measurement report](../eval/2026-09-23-decision-workspace-p0-measurement-report.md)의 실패 증거를 그대로 근거로 사용한다.

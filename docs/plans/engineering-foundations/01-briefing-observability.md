# P0 — Briefing Observability

## 목적

현재 briefing pipeline의 신뢰성 설계를 운영 관점에서 추적 가능하게 만든다.

단순 request log가 아니라 다음 질문에 답할 수 있어야 한다.

- 어떤 Event를 기준으로 briefing을 만들었는가?
- 어떤 Evidence snapshot을 사용했는가?
- 후보 중 무엇이 선택/제외됐는가?
- 기존 briefing을 재사용했는가, 재생성했는가?
- 재생성 이유는 무엇인가?
- LLM/provider 실패가 있었는가?
- fallback 또는 validation이 개입했는가?
- 어느 단계가 latency/cost를 만들었는가?

## 최소 Trace Schema

기존 계약을 침범하지 않는 별도 operational trace로 설계한다.

- trace_id
- project_id / workspace_id
- asset_id
- event_id
- evidence_snapshot_id 또는 equivalent fingerprint
- evidence_candidate_count
- selected_evidence_count
- mandatory_evidence_count / preserved count
- selection policy/version
- generation policy
- cache/reuse decision
- regeneration reason
- model/provider
- prompt/input tokens
- output tokens
- provider latency_ms
- total latency_ms
- validation result
- fallback used
- retry count
- final artifact/report id

민감한 raw prompt/evidence 전문을 tracing 필수값으로 삼지 않는다.

## 계측 경계

다음 단계를 분리 측정한다.

1. event/evidence load
2. evidence selection
3. snapshot/fingerprint validation
4. generation decision
5. provider call
6. output validation
7. persistence
8. read/reuse serving

## 검증 시나리오

- snapshot 동일 → 저장본 재사용
- snapshot 불일치 → 기존 guard 정책 동작
- meaningful change → 재생성
- provider timeout
- parsing/schema validation failure
- deterministic fallback
- mandatory evidence 누락 방지
- 동일 Event 반복 조회

## 결과 표현

기존 evidence-selection/briefing-efficiency 평가와 연결하되, 기존 수치를 새 trace 구현의 결과인 것처럼 재표현하지 않는다.

새로운 계측 후에는 최소 다음을 보고한다.

- cache/reuse rate
- generation rate
- p50/p95 total latency
- provider latency 비중
- token distribution
- validation/fallback frequency

표본이 작으면 절대적인 운영 성능으로 일반화하지 않는다.

## 구현 상태 — 2026-09-20

P0는 기존 `agent_review_workflow_runs.trace_json`과 summary materialization 경로를 확장하는 방식으로 구현했다. Event/Evidence/Decision/Action 제품 계약이나 briefing 출력 schema는 변경하지 않았다.

구현된 operational trace schema는 `briefing-operational-trace-v1.0`이며 다음을 한 lifecycle에 연결한다.

- 생성/조회마다 별도 `trace_id`
- project/workspace/asset/event/snapshot identity와 evidence fingerprint
- evidence 후보/선택/필수/필수 보존 개수와 deterministic selection policy version
- generation policy, generate/reuse/defer 결정, regeneration reason
- provider/model, provider-reported token usage, provider latency
- event/evidence load → evidence selection → fingerprint validation → generation decision → provider → validation → persistence → read/reuse의 단계별 latency
- provider failure / validation failure / generation failure 구분
- fallback 여부와 reason, content repair retry count
- 최종 summary artifact id, workflow run id, summary key
- 저장본 조회 시 과거 생성 token/latency를 현재 조회 비용으로 재계상하지 않음

생성 lifecycle의 최종 operational trace는 `agent_review_workflow_runs.trace_json.observability`에도 저장한다. raw prompt, evidence 전문, API key는 trace 필수값에 포함하지 않는다.

### 검증

다음 검증을 현재 P0 working tree에서 통과했다.

- `tests/test_briefing_observability.py`: 3 passed
- `tests/test_materialization_lease_fencing.py`: 10 passed
- `tests/test_operations.py -k 'agent_review'`: 30 passed
- watcher / scan retry / selected evidence / briefing HTTP / workflow reliability·stability 묶음: 18 passed
- generation-policy의 현재 구현과 일치하는 묶음: 21 passed

`tests/test_agent_review_generation_policy.py` 전체의 나머지 18개 실패는 P0 변경 이전 clean HEAD에서도 동일하게 재현된다. 현행 `cached_agent_review_summary_for_packet()`의 `LATEST_STORED` serving 정책과, exact cache가 무효이면 `None`이어야 한다고 가정하는 해당 테스트들이 서로 충돌한다. P0에서는 이 기존 정책 충돌을 임의 수정하지 않는다.

## 완료 조건

- [x] trace_id 하나로 생성 lifecycle 재구성 가능
- [x] 재사용/재생성 이유 추적 가능
- [x] provider failure와 validation failure 구분 가능
- [x] raw secret/API key 미기록
- [x] 기존 report/product contract 비파괴

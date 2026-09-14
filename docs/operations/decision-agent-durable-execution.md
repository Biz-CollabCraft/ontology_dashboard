# Decision Session 영속 실행 계약

실제 API는 `DurableDecisionRunner`를 사용한다. 최대 3개의 독립 필수 read-only 도구를 병렬 호출하고, 모두 모인 뒤 원문을 한 번에 해석한다. Policy Guard는 기존 deterministic 구현을 유지한다.

## 요청과 재개

`POST /api/objects/{asset_id}/decision-sessions`에 기존 identity query와 함께 `request_id`를 전달한다. request_id는 영문·숫자·밑줄·하이픈 8~128자다.

```text
request_id = 클라이언트가 생성하고 재시도 동안 보관한 고유 ID
```

동일 사용자·역할·identity·request_id의 재요청은 같은 세션을 사용한다. 완료된 상태는 저장 결과를 반환하고, 미완료 상태는 lease를 얻은 뒤 이어간다. request_id를 생략하면 매번 새로운 실행이다.
현재 사용자가 다른 경우에는 같은 클라이언트 키여도 별도 실행이다. GET 권한은 기존 `events.read`와 정확한 identity scope 검증을 따른다.

진행 중이거나 lease가 아직 만료되지 않은 실행은 409 `decision_run_in_progress`다. 서버가 죽으면 기본 30초 lease 만료 후 동일 POST로 재개한다. 서버 시작 시 자동으로 미완료 작업을 재개하는 queue worker는 없다.

현재 서버가 다시 확인한 근거·운영 컨텍스트 fingerprint·모델 및 prompt/policy 버전이 다르면 409 `decision_run_configuration_or_evidence_changed`다. 이 경우 새 요청 ID로 새 판단을 시작해야 한다. 원문의 일부가 변경됐는데 이전 결과를 재사용하지 않는다.

## 저장 항목과 경계

`decision_agent_runs`에 요청, 단계, 완료한 도구 결과, 시도 trace, 남은 예산, 문구 해석, 최종 result를 저장한다. 실행 lease와 fencing token으로 동시 실행과 오래된 writer를 차단한다. 상태 크기 상한은 4MB다.

시도는 호출 **전**에 저장한다. 결과는 도착할 때마다 별도로 커밋한다. 중단 직전 결과를 저장하지 못한 read-only 호출은 다시 실행될 수 있고 예산을 추가로 사용한다. LLM 응답도 저장 전에 중단되면 재호출될 수 있다. 완료한 해석 이후 단계로 재개할 때는 저장 해석을 사용한다.

LangGraph의 단계 실행과 애플리케이션 소유 DB checkpoint를 조합한 방식이다. native LangGraph checkpointer를 사용하는 것은 아니다. 운영 저장소와 MCP tool은 read-only이고, 실행 상태 DB 기록만 추가했다. 어떤 제안도 작업지시·승인 mutation 권한을 갖지 않는다.

`DECISION_AGENT_PLANNER=llm`인 경우 새 API 경로의 필수 조회 목록은 deterministic policy가 정하며 LLM은 수집 이후 추천 ranking에 참여한다. 따라서 engine은 `langgraph+durable+parallel+llm-ranking`으로 표시한다. 기존 직접 `ManufacturingDecisionAgent.run`의 LLM 순차 tool selection 경로는 보존했으나 실제 durable API의 조회 순서를 제어하지 않는다.

[검증과 한계](../eval/decision-durable-2026-09-14/README.md)를 참조한다. 이번 검증은 외부 LLM 호출 없이 진행했으며 프론트 request_id 연결은 포함하지 않았다.


## 인증된 호출자에서 요청 키 보관

`scripts/decision_session_client.py::create_or_resume_session`은 인증된 httpx.Client와 CSRF header를 전달받는다. 호출 전에 request_id를 로컬 상태 파일에 저장하고, 네트워크 오류 또는 진행 중/lease 상실 409만 제한된 횟수로 재시도한다. 기본 8회, 시도 사이 5초이며 설정 변경·근거 변경 409, 인증 오류 등은 즉시 반환한다.

같은 서버·사용자·asset·params에는 같은 state_path를 재사용한다. 다른 판단을 시작할 때는 새 state_path를 사용한다. 상태 파일은 0600 권한이며 request_id, scope hash, 완료 session_id만 담고 인증 정보와 쿠키는 저장하지 않는다. 프론트에는 아직 이 호출이 연결되지 않았다.

```python
# client는 로그인된 httpx.Client이며 headers는 기존 CSRF 헤더다.
result = create_or_resume_session(
    client=client, asset_id=asset_id, params=identity_query,
    actor_id=current_user_id, state_path=Path("decision-request.json"),
    headers=headers,
)
```

[실제 미완료 HTTP 복구 증거](../eval/decision-durable-2026-09-14/http-client-recovery.json): 첫 조회 커밋 후 두 번째 조회에 지연을 주입하고 HTTP 응답을 잃은 상태에서 서버를 kill했다. 새 서버와 새 클라이언트가 저장된 request_id로 같은 세션을 복구했다. 첫 결과 1개 재사용, 총 시도 3회, 재시도 예산 3→2, 이후 재요청 응답 동일, 도메인 13개 테이블 동일. 테스트 lease만 0.5초로 줄였으며 운영 기본 30초는 변경하지 않았다. LLM 비활성화·fixture 근거 검증이다.

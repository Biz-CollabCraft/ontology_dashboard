# 병렬 조회·영속 상태·서버 중단 복구 검증

후속 변경: 아래의 아키텍처 위반 6건은 이후 [의존 경계 정리](../../operations/decision-agent-architecture-cleanup-2026-09-14.md)에서 해결했다. 이 문서의 수치와 등록 hash는 원래 평가 시점의 기록이다.

검증일: 2026-09-14. 기준 HEAD: `d59aaca2d760cf46d26881875a926d3199222ef1` + 현재 미커밋 변경.
프론트, 도메인 mutation, 외부 MCP transport는 수정하지 않았다.

## 결과

독립적인 필수 조회를 최대 3개 병렬 실행하고, 완료 결과마다 DB에 저장하도록 실제 Decision Session API를 연결했다.
추천은 모든 필수 조회가 끝난 뒤 수행한다. 완료되지 않은 조회가 있으면 추천을 보류한다.
서버를 강제 종료한 뒤 같은 요청 ID로 재요청하면 저장된 상태에서 이어간다.

| 검증 | 결과 | 범위 |
|---|---|---|
| 집중 회귀 검사 | 94 passed | 신규 복구·동시성, 세션 API, DI, 텍스트 해석, 기존 구조 평가, 아키텍처 검사기 단위 테스트 |
| 기존 계약·정책·도구·MCP·migration 검사 | 72 passed | 기존 read-only 경계와 호환성 |
| PostgreSQL 복구·fencing 검사 | 2 passed | 실제 임시 PostgreSQL, 별도 OS 프로세스 kill/restart |
| HTTP 서버 재시작 | 통과 | 실제 loopback HTTP + PostgreSQL, LLM 비활성화 |
| 도메인 테이블 변경 | 0 | 관련 13개 테이블의 전체 행 해시 비교 |
| 새 구조 평가 | 60/60 기대 결과 일치 | 10가지 가정 시나리오 × 3회 × 직렬/병렬, 고정 문구 분류 응답 |
| 정책 밖 추천·승인 우회·mutation | 0/60 | 고정 응답을 사용한 구조 평가 |

합계 테스트 **168 passed**. 전체 repository 아키텍처 검사는 별도로 FAIL이다. 검사기 단위 테스트 통과를 repository 구조 검사 통과로 표현하지 않는다.

## 병렬 시간 비교

동일한 durable runner에서 worker 수만 1과 3으로 바꿨다. 각 조회에 100ms 지연을 넣었고, 양쪽 모두 측정 전 1회 예열했다.
정상 2개 조회와 정비 3개 조회 각각 arm별 3회 평균이다. 전체 평가 동안 SQLite 저장·lease heartbeat도 실제 수행했다.

| 시나리오 | 직렬 worker=1 | 병렬 worker=3 |
|---|---:|---:|
| 정상, 독립 조회 2개 | 0.227초 | 0.128초 |
| 정비, 독립 조회 3개 | 0.336초 | 0.119초 |

병렬 방식은 초기에 충돌을 발견해도 이미 시작한 다른 조회를 마저 수행한다. 따라서 즉시 보류할 수 있었던 순차 경로보다 조회 수가 늘 수 있으며, 이번 비교는 동일한 전체 필수 조회를 수행하는 직렬 arm과의 비교다.

이것은 **100ms 주입 지연 하에서의 실행 구조 효과**다. live backend 응답 속도나 Luna 모델 성능 수치가 아니다.
첫 예비 측정은 초기 로딩 비용을 포함했다. 원본은 `/private/tmp/decision-durable-eval-20260914`에 남겼고, 본 표에는 예열 조건을 등록한 최종 실행만 사용했다.

- 최종 등록 binding: `a87e0e5185d9f205f6c002c03e27200e30db7dd28c9eeb032187b2da58b65c57`
- 입력, 코드 SHA, arm 및 예열 조건: [registration.json](registration.json)
- 개별 60회 결과 및 집계: [results.json](results.json)
- 원격 API 호출: 0회. 토큰: 측정 대상 아님.
- 직렬·병렬 각각 고정 분류기 호출 15회. 완료 상태 재사용은 추가 분류 호출 없이 검사했다.
- 기존 `early_measurement` 시나리오는 뒤의 부정 문구와 충돌하는 잘못된 gold였으므로 제외했다. 원본 평가를 수정하거나 정상 정답으로 재사용하지 않았다.
- 새 `late_explicit_conflict`는 앞의 추가 측정 요구와 뒤의 명시적 충돌을 모두 읽은 뒤 보류하는지 검사한다. 고정 분류기 검사이므로 Luna가 모호한 모순을 잘 해석한다는 증거는 아니다.

## 복구 검증

### 프로세스 강제 종료

SQLite와 PostgreSQL 각각 별도 OS 프로세스를 실행했다. 첫 조회 결과의 DB 커밋을 확인하고 두 번째 조회를 대기시킨 상태에서 프로세스를 kill했다.
lease 만료 후 새 프로세스로 동일 세션을 재개했다.

- 첫 조회 실행: 전체 1회. 저장 결과 재사용.
- 두 번째 조회 실행: 중단 전 1회 + 복구 후 1회.
- 총 시도 기록: 3회. 재시도 예산: 3 → 2.
- 최종 `REQUEST_INSPECTION`, human approval 필요, mutation 없음.
- 살아 있는 실행은 heartbeat로 lease 유지. 동시 claim 거절.
- 만료된 이전 token의 save와 release는 새 실행을 덮어쓰거나 잠금을 풀 수 없음.
- 해석 결과 커밋 직후 중단을 주입한 별도 검사에서는 분류기를 추가 호출하지 않고 최종 추천을 만들었다.

### 실제 HTTP 서버 재시작

동일한 임시 PostgreSQL을 유지한 채 HTTP 서버를 kill하고 새 프로세스로 시작했다.
GET 세션 응답과 같은 request_id의 POST 전체 응답이 재시작 전과 같았다.
CSRF 미제공 403, 잘못된 snapshot 409, 비로그인 401도 확인했다.

- [HTTP 증거](http-proof.json): 관련 13개 테이블 전후 해시 및 결과.
- [정리 증거](http-cleanup.json): 임시 DB 제거와 서버 종료 확인.
- fixture 설비 근거를 사용했으며 LLM은 비활성화했다.
- 실제 Luna/OpenAI 전송을 포함한 이번 검증은 자동 승인 심사에서 구체적인 payload 전송 승인 부족 사유로 거절되어 실행하지 않았다. 키를 로딩하거나 전송하지 않는 로컬 검증으로 진행했다. 기존 Luna 평가를 이번 복구 검증으로 대신 표시하지 않는다.

## 남는 한계와 판단

1. DB 상태 저장·잠금·복구는 애플리케이션 구현이다. LangGraph는 `gather → interpret → final` 흐름을 실행한다. native PostgresSaver를 사용하거나 LangGraph 자체가 정확도를 높였다는 주장은 하지 않는다.
2. 복구는 **동일 request_id 재요청**으로 시작한다. 서버 기동만으로 모든 미완료 작업을 재개하는 background worker는 없다. 프론트는 이번 범위에서 변경하지 않았으므로 호출자가 request_id를 보관해야 한다.
3. 기본 lease는 30초다. 프로세스 중단 직후 만료 전 재요청은 409를 받을 수 있다. 이미 진행 중인 요청에도 같은 응답을 반환한다.
4. 도구 결과 저장 직전 끊기면 read-only 호출이 중복될 수 있다. 시도/예산은 복구 후에도 보존한다. exactly-once 외부 호출을 보장하지 않는다.
5. LLM 응답을 받았으나 저장 전 중단된 경우 LLM 호출이 반복될 수 있다. 저장된 해석은 재사용하지만 LLM 요청 자체의 외부 중복 방지는 없다.
6. 메모리는 같은 identity/actor/request 안의 실행 상태다. 다른 사건이나 사용자 사이에서 판단 기억을 공유하지 않는다. 모델·프롬프트·정책·운영 컨텍스트 버전·서버 근거가 달라지면 같은 요청의 재개를 거절한다. 수집시각 `evidence_context.relation_retrieved_at`만 근거 해시에서 제외한다.
7. 원문 간 모호한 충돌 해석은 여전히 Luna v4의 알려진 한계다. 이번 구조 검증은 그 의미 해석 정확도를 재평가하지 않았다.
8. 저장 상태의 retention/삭제 작업과 다중 서버 장기 부하, DB 자체 장애·복구, 실제 원격 MCP latency는 이번 측정에 포함하지 않았다.
9. 전체 아키텍처 검사에는 기존 HEAD에도 존재하는 위반 6건이 남아 있다: `filesystem_briefing.py`의 diagnosis router import 2건, `decision_llm_planner.py` 및 `decision_text_interpreter.py`의 httpx/infra provider import 각 2건. 신규 저장소/runner가 이 경계 위반을 추가하지는 않았다.

판단: 독립 조회 병렬화와 재시작 후 상태 보존의 효과는 확인됐다. LangGraph 자체의 우위나 LLM 판단 정확도 우위와 분리해서 설명한다. 다음 실사용 연결은 호출자의 request_id 보관·409 재시도 처리이며, 모델 프롬프트를 다시 점수에 맞춰 수정할 근거는 이번 평가에 없다.

## 재현

```bash
python3 -m pytest -q -p no:cacheprovider tests/test_decision_durable_runner.py tests/test_decision_session_api.py tests/test_decision_text_di.py
# PostgreSQL은 기존 테스트의 TEST_POSTGRES_* 설정과 임시 DB 생성 권한이 필요하다.
python3 -m pytest -q -p no:cacheprovider tests/test_decision_durable_postgresql.py
PYTHONPATH=systems/backend:ml/src:. python3 scripts/evaluate_decision_durable.py --output-dir /tmp/new-durable-eval --prepare
PYTHONPATH=systems/backend:ml/src:. python3 scripts/evaluate_decision_durable.py --output-dir /tmp/new-durable-eval
```

## 주요 변경 파일

- `systems/backend/app/operations/decision_durable_runner.py`: 병렬 조회, 결과별 checkpoint, 예산 보존, 전체 근거 후 해석, 최종 결과 재사용.
- `systems/backend/app/operations/decision_run_store.py`: 저장·잠금 인터페이스.
- `systems/backend/app/infra/db/decision_run_repository.py`: SQLite/PostgreSQL 저장소, DB 시각 기반 lease와 fencing.
- `systems/backend/migrations/{sqlite,postgresql}/0052_decision_agent_runs.sql`: 실행 상태 테이블과 scope index, PostgreSQL RLS.
- `systems/backend/app/operations/decision_session_service.py`, `router.py`, `app/dependencies.py`: 실제 API/DI 연결, request_id, 영속 GET.
- `systems/backend/app/operations/decision_support_agent.py`: 운영 컨텍스트 fingerprint 전달 필드. 기존 직접 run 경로는 비교 및 호환성을 위해 유지.
- `tests/test_decision_durable_*.py`, `test_decision_session_api.py`, `test_decision_text_di.py`: 복구·API·DI 검사.
- `scripts/evaluate_decision_durable.py`: 고정 조건 구조 비교.

커밋·푸시하지 않았다. 기존 미커밋 LLM·gold·prompt 변경은 유지했다.

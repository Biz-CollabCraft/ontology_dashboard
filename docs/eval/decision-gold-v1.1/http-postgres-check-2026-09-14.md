# 실제 HTTP·PostgreSQL 연결 검증 — 2026-09-14

**통합 검증에서 입력 예산 처리 결함을 발견했다. 추천 경로는 통과로 판정하지 않는다.** 연결·권한·세션 재조회·읽기 전용 경계는 확인했다.

## 환경과 범위

현재 Decision Agent worktree의 app.main을 실제 uvicorn 서버로 localhost 임의 포트에 실행했다. 기존 로컬 PostgreSQL 컨테이너의 55432 포트에 이 검증만의 od_agent_http_ 임시 DB를 만들고 정상 migration과 참조/로그인 데이터 seed 경로를 사용했다. 서버의 dependency를 테스트 구현으로 대체하지 않았다. 기본 provider의 HTTP 전송 결과를 관찰해 모델명·설정·사용량만 기록했다.

모델은 실제 OpenAI gpt-5.6-luna, 프롬프트 v4, low, 4096, temperature 생략이다. Asset/Product Evidence는 애플리케이션의 기존 fixture 경로다. PostgreSQL에는 스코프가 맞는 owner context snapshot이 없어 not_connected/missing이 노출됐다. 따라서 실제 운영 데이터의 추천 검증이 아니라 **실제 HTTP + PostgreSQL 연결/빈 owner read + fixture 자산 근거 + 실제 모델 호출** 검증이다.

## 확인 결과

| 확인 | 결과 |
|---|---|
| HTTP 로그인 | 200 |
| CSRF 없는 생성 요청 | 403 |
| 정상 Decision Session 생성 | 두 번 모두 200, 단 최종 결과는 오류 기반 보류 |
| 실제 모델 요청 | 2회 모두 HTTP 200, 응답 모델 gpt-5.6-luna |
| engine | langgraph+text-llm |
| Session GET | 200, POST의 session 내용과 일치 |
| 잘못된 evidence snapshot | 409, 추가 모델 호출 없음 |
| 비인증 Session GET | 401, 추가 모델 호출 없음 |
| Human-in-the-loop | human_approval_required=true |
| Agent mutation | mutation_attempted=false |
| 도메인 DB 변경 | 두 번째 POST/GET 전후 13개 closed_loop/operational_context 테이블의 행 수·내용 해시 동일 |
| 정리 | 검증 서버 종료, 임시 DB 삭제 및 부재 확인 |

Decision Session은 프로세스 메모리에 저장된다. GET 성공은 PostgreSQL 세션 영속화나 재시작 후 보존을 뜻하지 않는다. 로그인 등의 인증 상태 쓰기와 도메인 데이터 변경은 구분했다. 점검/생산 owner 데이터가 채워진 정상 추천 시나리오, 명시적인 근거 충돌로 인한 정상 보류, 프론트 UI 흐름은 아직 통과 증거가 없다.

## 재현된 결함

대상 CNC-S04-L02-03의 get_asset_condition과 get_inspection_context가 각각 문구 13개를 반환한다. 합계 26회 등장하지만 서로 다른 원문은 12개, 전체 길이는 2,436자다.

첫 도구 호출의 텍스트는 실제 Luna로 해석되고 세션 cache에 들어간다. 두 번째 도구 이후 collect_excerpts가 누적 결과의 출처별 등장 횟수 26개를 세면서 16개 제한을 넘겼다고 거부한다. cache의 중복 해석 방지가 적용되기 전에 실패한다.

- text_interpretation_errors: text_batch_budget_exceeded
- recommendation_gate_reason: text_interpretation_unverified
- recommended_action: null

이는 Luna의 의미 판단 한계나 정당한 근거 충돌 보류가 아니라 **같은 문구의 여러 출처와 모델에 새로 보낼 고유 문구를 구분하지 못한 예산 검사 문제**다. 초기 HTTP 응답을 저장한 뒤 로컬 collector로도 동일 오류를 재현했다. 새 모델 호출 없이 재현 결과: 13+13회 등장, 고유 문구 12개.

다음 수정은 단순히 제한을 늘리는 것이 아니라 출처별 근거를 보존하면서 고유/미해석 문구의 LLM 예산과 수집 자체의 메모리 한도를 구분하는 것이다. 수정 후 동일 재현 입력의 회귀 검사와 HTTP 흐름을 다시 확인해야 한다. 이번 요청은 확인 작업이므로 아직 수집기나 Agent 로직을 수정하지 않았다.

## 증거

- [HTTP 생성과 재조회·DB 전후 해시](http-postgres-check-2026-09-14/http-db-check.json)
- [첫 번째 응답](http-postgres-check-2026-09-14/initial-response.json)
- [로그인·CSRF·재조회](http-postgres-check-2026-09-14/initial-http-check.json)
- [입력 예산 오류의 로컬 재현](http-postgres-check-2026-09-14/budget-reproduction.json)
- [실제 모델 응답·설정](http-postgres-check-2026-09-14/model-calls.json)
- [임시 DB 정리 확인](http-postgres-check-2026-09-14/cleanup.json)

증거 JSON은 기존 git 제외 규칙에 따라 로컬 보존 상태다. API key, DB password, 로그인 cookie는 기록하지 않았다. 최초 계획의 자격증명 파일 저장은 자동 승인 검토에서 거부되어 실행되지 않았고, 메모리 내 자격증명 사용과 명시적 정리 방식으로 검증을 완료했다. 기존 서버·DB·프론트는 변경하지 않았다. commit/push하지 않았다.

# 중복 문구 예산 처리 수정과 HTTP 재검증

2026-09-14 확인한 text_batch_budget_exceeded 결함을 수정했다. 같은 원문이 여러 도구에서 돌아와도 고유 텍스트 예산에서는 한 번만 계산하고, 도구·field_path·source_refs·as_of는 등장한 출처별로 모두 보존한다. 모델 해석과 세션 캐시는 기존 SHA256 키를 사용한다.

## 유지한 한도

- 개별 문구: 최대 4,000자.
- 수집된 고유 문구: 최대 16개, 합계 12,000자. 이미 해석된 원문도 이 세션 결과 집합의 고유 예산에 포함하므로 세션 예산을 무한 확대하지 않는다.
- 별도 출처 수집 한도: 5개 bounded tool 기준 최대 80개 텍스트 후보 필드, 합계 60,000자. 중복 문구의 과도한 반복도 차단한다.
- 후보 필드를 미리 리스트로 복제하지 않고 순차 순회하며 초과 시 거부한다. 수집 실패는 기존 오류 보류 경계를 유지한다.
- 출처 없는 중복 문구도 거부한다. 중복 제거가 provenance 검증을 우회하지 않는다.

## 검증

관련 테스트 90 passed. 26개 출처/12개 고유 원문/모델 호출 1회/캐시 재사용/전체 locator 보존을 확인하는 회귀 테스트를 추가했다. 17개 고유 문구, 고유 길이 초과, 81개 반복 필드, 중복 길이 초과, 중복 출처 누락도 각각 차단함을 검사했다. 저장된 이전 HTTP 실패 응답을 새 수집기로 그대로 읽어도 정상 처리됐다.

새 격리 PostgreSQL DB와 현재 worktree의 실제 uvicorn 서버로 동일 자산 CNC-S04-L02-03을 두 번 검증했다. 정상 application dependency를 사용했으며 모델 응답은 실제 Luna다.

| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| 도구별 문구 / 고유 문구 | 13+13 / 12 | 동일 |
| 해석 근거 보존 | 두 번째 도구에서 수집 실패 | 26개 출처 유지 |
| text_interpretation_errors | text_batch_budget_exceeded | 빈 배열 |
| recommendation_gate_reason | text_interpretation_unverified | null |
| 추천 | null | REQUEST_INSPECTION (두 번 모두) |
| 모델 호출 | 첫 도구 해석 후 실패 | 세션당 1회, 두 번째 도구는 cache 재사용 |

로그인 200, CSRF 미제공 403, Session POST/GET 200 및 session 내용 일치. 잘못된 snapshot 409, 비인증 GET 401이며 부정 요청은 추가 모델 호출을 만들지 않았다. 사람 승인 필요=true, mutation_attempted=false. 두 번째 요청 전후 13개 closed_loop/operational_context 테이블 행 수와 내용 해시가 같았다.

검증 서버를 종료하고 임시 DB 삭제 및 부재를 확인했다. 기존 서버·DB·프론트는 변경하지 않았다.

## 증거와 범위

- [HTTP 응답·DB 전후 해시](http-budget-fix-2026-09-14/http-db-check.json)
- [첫 요청 응답](http-budget-fix-2026-09-14/initial-response.json)
- [로그인·CSRF·재조회](http-budget-fix-2026-09-14/initial-http-check.json)
- [실제 모델 요청·응답 설정](http-budget-fix-2026-09-14/model-calls.json)
- [DB 정리 확인](http-budget-fix-2026-09-14/cleanup.json)

원문은 애플리케이션의 합성 fixture 자산 근거이고, PostgreSQL owner snapshot은 비어 있는 상태다. 이 검증은 수집기 결함 수정과 실제 HTTP·DB read·Luna·정책 연결 증거다. 운영 정답 정확도, 정상 owner snapshot이 모두 채워진 업무 시나리오, 화면 검증, 세션의 DB 영속화 증거가 아니다. 세션은 메모리 저장이다.

v4 프롬프트·모델 설정·JSON 출력 계약·Policy Guard는 변경하지 않았다. 기존 의미 분류 회귀와 조건부/복합 지시 한계는 유지한다. 데이터 라벨이나 과거 모델 평가 점수를 변경하지 않았다. JSON 증거는 git의 기존 제외 규칙에 따라 로컬 보존하며 commit/push하지 않았다.

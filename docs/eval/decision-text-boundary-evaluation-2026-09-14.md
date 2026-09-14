# 문구 과해석 경계 수정 및 PostgreSQL 확인 — 2026-09-14

## PostgreSQL 정정

PostgreSQL 환경이 없다는 앞선 설명은 부정확했다. `ontology-backend-integration-pg`는 127.0.0.1:55432, `ontology-standalone-page-pg`는 127.0.0.1:63542에서 실행 중이며 모두 연결을 받았다. 테스트 helper는 TEST_POSTGRES_PORT가 없으면 5432를 확인해 skip했다. 연결을 맞춘 뒤 현재 Python에 psycopg가 없는 것도 확인했다.

저장소에 선언된 psycopg/psycopg_pool을 `/private/tmp/decision-postgres-deps`에만 준비하고 55432의 별도 임시 DB에서 기존 검사 176개를 실행해 모두 통과했다. 기존 DB 데이터나 컨테이너 설정은 변경하지 않았다. 이는 PostgreSQL 통합 검사이며, LLM 합성 평가가 live backend 성능이라는 의미는 아니다.

## 수정

- 정보 누락과 측정 요구를 분리했다. LLM은 information_missing 및 measurement_status(required/not_required/optional/not_stated/unclear)를 출력한다. 서버가 required에서만 measurement_required를 산출한다. 정보 누락만으로 진단 요청을 만들지 않는다.
- required는 실제 원문에 포함된 measurement_evidence 구절을 요구한다. 전체 원문과 출처도 보존한다. 누락/원문 밖 구절은 batch 오류로 기록하고 보류하며 cache에 게시하지 않는다. 구절 일치가 의미의 정확성을 보장하지는 않는다.
- 기본 service는 LangGraph + LLM 문구 해석 + deterministic 추천이다. LLM_PROVIDER가 활성화되어야 문구 해석을 사용한다. DECISION_AGENT_PLANNER=llm으로 기존 LLM 도구 선택/ranking을 실험할 수 있다. 잘못된 mode, offline provider와 llm mode 조합은 명시적으로 오류 처리한다.
- Policy Guard, read-only 도구, Human-in-the-loop 경계를 유지했다. 프론트/도메인 실행/migration은 수정하지 않았다.

## 평가 설계

기존 11문장은 수정용 회귀 세트로 취급했다. 별도로 작성한 한영 24문장과 정답을 실행 전에 고정했다. 정보 누락/명시적 요구/부정/선택 사항/충돌/해결된 충돌/불명확함을 포함하며 유사 문장의 의미를 바꾼 쌍으로 구성했다.

manifest: `tests/fixtures/decision_text_holdout_v1.json`
SHA256: `cbcdd3fa68979aab6c173d2fddb302d579074bad50f6ea98773ad356990039a7`

수정 전후 각각 24문장 × 3회, 동일 순서로 8문장씩 API 요청했다. 합성 텍스트만 OpenAI gpt-4o-mini로 보냈다. gold/행동/정답은 모델 입력에 포함하지 않았다. 수정 전은 푸시 기준 340c1a18의 interpreter, 수정 후는 미커밋 v2 interpreter다. 모델 결과 확인 뒤 이 세트에 맞춰 프롬프트를 재수정하지 않았다.

이것은 동일 작성자가 만든 새 합성 세트다. 독립 전문가 평가나 실제 사용자 데이터가 아니며, 반복 72건은 독립 문장 72개가 아니다. 이제 결과를 확인했으므로 향후 개선의 완전히 새로운 holdout이라고 다시 주장할 수 없다.

## 결과

| 지표 | 수정 전 | 수정 후 |
|---|---:|---:|
| 기존 3개 flag 모두 일치 | 48/72 | 69/72 |
| 측정 요구 오탐 / 요구 없는 문장 | 18/54 | 0/54 |
| 실제 측정 요구 누락 | 0/18 | 0/18 |
| 충돌 오탐 / 충돌 없는 문장 | 6/60 | 0/60 |
| 실제 충돌 누락 | 0/12 | 0/12 |
| 불명확함 누락 | 0/6 | 3/6 |
| API/구조 검증 오류 행 | 0 | 0 |

추가 필드까지 정확한 비율은 따로 본다: information_missing 62/72, measurement_status 66/72, 다섯 필드 전체 일치 59/72. 69/72를 모든 필드의 정확도로 표현하면 안 된다.

기존 수정용 11문장 × 3회는 33/33이었다. 기존 Agent 7시나리오 × 구성별 1회 확인에서는 규칙만 5/7, LLM 해석+규칙 추천 7/7, LLM 해석+LLM 추천 5/7이었다. 모든 구성에서 허용 도구 경로 일치, 불필요 조회/필수 조회 누락/대체 처리/해석 오류 0이었다. 1회 확인 결과이므로 이전 5회 평가를 대체하는 신뢰도 추정이 아니다.

새 텍스트 평가의 API 요청은 전후 각 9회다. 전체 토큰은 14,516 → 17,071, 8문장 배치 평균 시간은 4.705s → 5.073s였다. 추가 필드로 입력·출력 비용이 늘었다. Agent 단위 지연이나 현장 판단 시간으로 환산하지 않는다.

## 코드 검증

후속 변경의 최종 검사는 PostgreSQL 임시 DB를 포함해 **189 passed, 0 skipped (28.55s)**였다. 신규 테스트는 정보 누락만으로 진단을 요청하지 않는 경계, 출처 구절 검증, 불명확 상태 처리, 기본/실험 mode 연결, 잘못된 설정 거부, 평가 오류와 오탐·누락 분모를 확인한다. `git diff --check`도 통과했다.

## 남은 문제와 다음 판단

한국어 U1의 '추가 확인이 서류 확인인지 재측정 요구인지 의미를 판단할 수 없다'를 information_missing=true, measurement_status=not_stated로 읽어 불명확함을 놓쳤다(3/3). 이 경우 원문은 남지만 자동 사람 검토 보류 경로를 놓칠 수 있다. 모든 proposal의 사람 승인은 유지되지만, 검토 필요성 표시의 정확성이 확보된 것은 아니다.

또한 정보 누락과 의미 불명확함을 혼동하거나, optional을 not_required로 분류하는 오류가 남았다. 측정 요구 오탐이 줄었다는 결론과 불명확함 누락이 늘었다는 한계를 함께 보고해야 한다. 기본 구성 변경은 로컬 코드 변경이며 배포 승인이나 현장 성능 검증이 아니다.

다음 실험은 U1을 개발 회귀 사례로 편입한 뒤 별도의 새 한국어 모호 표현 세트를 고정하고, 불명확함 recall과 불필요 보류를 함께 측정하는 것이다. 현재 세트 정답에 맞춘 반복 수정으로 점수를 높이지 않는다.

## 재현 및 자료

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_text_holdout.py --env-file /path/to/local.env --manifest tests/fixtures/decision_text_holdout_v1.json --iterations 3 --label after --output /private/tmp/text-holdout.json
```

기존 PostgreSQL 테스트는 TEST_POSTGRES_HOST=127.0.0.1, TEST_POSTGRES_PORT=55432와 해당 테스트 계정 설정이 필요하다. 비밀번호는 문서/로그에 기록하지 않는다. PostgreSQL optional dependencies가 설치된 Python을 사용한다.

원시 결과는 기존 Git 제외 규칙에 따라 로컬 보존했다:
- [수정 전](decision-text-boundary-before-2026-09-14.json)
- [수정 후](decision-text-boundary-after-2026-09-14.json)
- [기존 문장 회귀](decision-text-boundary-regression-2026-09-14.json)
- [Agent 흐름 확인](decision-text-boundary-agent-smoke-2026-09-14.json)

# 모호 표현 검증 및 수정 — 2026-09-14

> 모델 범위 정정: 아래는 gpt-4o-mini 평가다. 후속 [4o-mini/Luna 비교](decision-model-comparison-2026-09-14.md)에서는 Luna의 주요 분류가 105/105였고 특정 충돌 오탐·불필요 보류가 재현되지 않았다. 아래 한계를 Luna에 그대로 적용하지 않는다.

## 결과와 범위

새 모호 표현 검증 24문장 × 3회에서 필요한 사람 검토 누락 0/36, 불필요 보류 0/36, 측정 요구 오탐 0/66, 실제 측정 요구 누락 0/6, 응답 오류 0/72였다. 기록한 해석을 실제 LangGraph와 합성 도구로 재생해 72/72에서 기대한 추천/보류 경로를 확인했다. 재생은 추가 live 모델 호출이나 실제 backend 성능이 아니다.

다만 기존 3개 flag 전체 일치는 60/72다. 모호한 지시를 '명시적 근거 충돌'로도 분류한 12건이 남았다. 이 사례들은 이미 의미 확인이 필요해 보류 경로는 맞지만 보류 이유의 분류가 틀렸다. information_missing은 56/72, measurement_status는 45/72다. 주요 경로 72/72를 모든 필드 정확도로 표현하면 안 된다.

기존 11문장 회귀는 27/33이다. 정보 누락만 말하는 E3를 불필요하게 보류한 3건과 모호한 문구 E7에 충돌 flag까지 추가한 3건이 남았다. 원래 33/33이던 회귀보다 나빠진 부분을 숨기지 않는다. 따라서 이번 수정은 모호 표현의 검토 경로 개선이며, 전체 해석 품질 해결이나 배포 준비 완료는 아니다.

## 원인과 변경

1. 모델은 '추가 확인'을 새 측정으로 단정하거나, 명확한 교정 기록 조회를 불명확하다고 읽었다. 설명을 늘린 첫 프롬프트 수정만으로는 개선되지 않았다.
2. 응답에 meaning(record_review/new_measurement/ambiguous_request/ambiguous_other/clear_other)을 먼저 구분하도록 추가했다. 서버는 모호한 meaning을 보류하고, required + new_measurement 조합에서만 측정 요구를 만든다. 원본 tool fact, Policy Guard, Human-in-the-loop는 유지한다.
3. 합성 검증 중 64자리 근거 해시의 마지막 글자 누락을 실제 응답에서 확인했다. API용 짧은 ID를 사용하고 schema에 ID enum 및 정확한 응답 개수를 넣었다. cache 게시 전에 중복/누락/원문 구절을 검증하고 서버가 SHA256 ID를 복원한다.
4. 모델이 선택적인 측정의 정확한 원문을 인용하면 기존 validator가 이를 거부해 전체 묶음이 실패했다. 이제 선택적/불필요 측정의 인용도 정확한 원문이면 보존한다. 인용 여부로 required를 만들지 않는다. 필수 측정 인용 누락과 원문 밖 인용은 계속 거부한다.
5. 기존 복합 문장에서 충돌과 측정 요구 중 한쪽만 읽는 회귀가 있어 모든 절을 읽고 두 항목을 독립적으로 판정하도록 보강했다. 이 과정에서도 위의 세부 분류 오탐이 남았다.

## 평가 설계와 비교 한계

개발용 16문장과 별도 검증용 24문장의 gold를 API 실행 전에 작성·고정했다. 개발에는 기존 U1 실패 문장도 포함했다. 둘 다 같은 작성자가 만든 합성 한영 문장이므로 독립 전문가 평가나 현장 데이터가 아니다. 반복 횟수는 독립 문장 수가 아니다.

- 개발 manifest SHA256: f16845e060d61d6978b3793c4d53aedd12491724fdece3c781e03169aafb33bc
- 검증 manifest SHA256: e7e72df7bc1372aeaa46fd82cb1a32dd6e5def76b9d11f412ee9c139fe43134c

검증 중 연결/validator 실패를 발견해 수정 후 같은 세트를 재실행했다. 이 때문에 마지막 수치를 '한 번도 결과를 보지 않은 독립 holdout'이라고 주장하지 않는다. 문장과 gold는 바꾸지 않았고, 각 단계 raw 및 prompt hash를 남겼다. 최종 코드에 대한 별도 새 검증은 이후 필요하다.

| 평가 | 주요 3 flag 일치 | 검토 누락 | 불필요 보류 | 오류 행 |
|---|---:|---:|---:|---:|
| 개발 수정 전 | 42/48 | 3/24 | 0/24 | 0 |
| 개발 최종 | 27/48 | 0/24 | 0/24 | 0 |
| 검증 수정 전 | 30/72 | 26/28* | 0/28* | 16 |
| 검증 최종 | 60/72 | 0/36 | 0/36 | 0 |
| 최종 단독 입력 1회 | 21/24 | 0/12 | 0/12 | 0 |

*오류 행은 의미 분류 분모에서 제외하고 별도로 실패 집계했다. 전후 분모가 다르므로 26/28을 전체 36개 필요 검토의 누락률처럼 표현하지 않는다. 오류를 보류 정답으로 세지 않았다. 개발 최종의 세부 일치 감소는 모호함을 충돌로 중복 표시한 오탐 때문이다.

## 검증과 작업 상태

원본 출처 보존, 정보 누락/기록 조회의 측정 요구 차단, 모호 의미의 실제 Agent 보류 경로, 짧은 ID 제한과 SHA 복원, optional 인용 보존, 오류를 정답으로 세지 않는 지표를 테스트했다. PostgreSQL 검사는 실행 중인 55432 서버에 별도 임시 DB를 만들고 제거하는 방식으로 실행했다.

프론트, 도메인 mutation, DB migration은 변경하지 않았다. 이전 작업의 미커밋 변경을 유지했다. 이번 수정은 commit/push하지 않았다.

최종 관련 테스트는 **197 passed, 0 skipped (16.78s)**이며 `git diff --check`도 통과했다.

## 재현 자료

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_text_holdout.py --env-file /path/to/approved.env --manifest tests/fixtures/decision_text_ambiguity_holdout_v1.json --iterations 3 --label validation --output /private/tmp/ambiguity.json
```

단독 입력은 --batch-size 1 --iterations 1로 실행한다. 모델은 승인된 OpenAI gpt-4o-mini, 데이터는 작성된 합성 문장뿐이다. raw는 기존 Git 제외 규칙대로 로컬 보존한다. interpreter-before 스냅샷은 로컬 재현용이다.

- [개발 수정 전](decision-ambiguity-dev-before-2026-09-14.json)
- [개발 최종](decision-ambiguity-dev-final-2026-09-14.json)
- [검증 수정 전](decision-ambiguity-holdout-before-2026-09-14.json)
- [검증 최종](decision-ambiguity-validation-final-2026-09-14.json)
- [단독 입력](decision-ambiguity-single-final-2026-09-14.json)
- [기존 회귀](decision-ambiguity-diagnostic-final-2026-09-14.json)
- [Agent 재생](decision-ambiguity-agent-replay-2026-09-14.json)
- [해시 누락 재현](decision-ambiguity-id-probe-2026-09-14.json)
- [선택적 인용 재현](decision-ambiguity-shape-probe-2026-09-14.json)

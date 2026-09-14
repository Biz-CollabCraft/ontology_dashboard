# 수정한 골드 초안의 모델 비교 — 2026-09-14

사람 검수 전 **제안 라벨과의 일치도**다. 검증된 골드 정확도, 실제 공장 정확도, live backend 성능으로 해석하지 않는다. Luna는 행동에 영향을 주는 세 판단에서 더 잘 일치했지만 모든 의미 항목에서 우세하지 않았다.

입력: 정답 유도 문구 5건 제거 후 평가 분할 24개 중 20개 × 모델별 3회 = 총 120개 응답. 미정 D05-03, D05-04, H05-03, H05-04는 제외했다. 개발 분할은 평가하지 않았다. F03/F05/F06의 3개 family이며 60개 독립 사례가 아니다. 모두 warning_no_inspection 정책 배경이다.

| 지표 | 4o-mini | Luna |
|---|---:|---:|
| 충돌·측정 필요·모호함 3항목 동시 일치 | 47/60 (78.3%) | 60/60 (100%) |
| 의미·정보 누락·측정 상태까지 6항목 동시 일치 | 38/60 (63.3%) | 33/60 (55%) |
| 의미 분류 | 53/60 | 56/60 |
| 정보 누락 | 58/60 | 44/60 |
| 측정 상태 | 44/60 | 50/60 |
| 충돌 과잉 판정 / 음성 응답 | 10/48 | 0/48 |
| 모호함 과잉 판정 / 음성 응답 | 3/48 | 0/48 |
| 측정 필요 과잉 / 누락 | 0/48, 0/12 | 0/48, 0/12 |
| 필요한 사람 검토 누락 | 0/24 | 0/24 |
| 불필요한 사람 검토 | 1/36 | 0/36 |
| LangGraph 재생의 제안 행동 제약 일치 | 59/60 | 60/60 |
| 응답 오류 / JSON 형식 재시도 | 0 / 0 | 0 / 0 |
| API 요청 수 | 9 | 9 |
| 평균 배치 지연 | 3.520초 | 6.173초 |
| 총 토큰 | 12,881 | 15,468 |

지연은 4~8문장 배치 한 번의 측정값이며 단일 Decision Session 지연이 아니다. 가격·운영 비용은 측정하지 않았다.

## 관찰과 다음 판단

- 4o-mini는 지시의 모호함을 근거 충돌로 추가 해석했다. D03-04/H03-04 등에서 나타났다. D05-02의 세 번째 실행에서는 필요한 측정 요청을 모호함으로도 판정해 진단 제안 대신 보류했다.
- Luna는 새 측정이 필요하거나 현재 의견이 충돌하면 정보가 누락된 것으로 넓게 해석하는 경향을 보였다. D03-01, D05-02, D06-01, H05-02 등이 해당한다. 제안 라벨은 명시적인 자료 누락만 true로 두었다. 정의와 라벨에 대한 사람 검수 전에는 전부 모델 오답이라고 확정하지 않는다.
- 두 모델 모두 `not_stated`와 `unclear`, `optional`과 `not_required` 등 세부 경계에서 불일치가 있다. 결과를 보고 라벨·프롬프트를 변경하거나 추가 재실행하지 않았다.
- 현재 제안 라벨 기준으로 Luna는 행동 제약에 더 잘 맞았지만, 전체 의미 정확도 우위를 입증하지는 못했다. 다음 단계는 정보 누락과 측정 상태의 라벨 기준 검수다. 기본 서버 모델 설정은 변경하지 않았다.

## 검증 범위

실제 OpenAI 모델 호출 결과다. 요청 모델은 gpt-4o-mini / gpt-5.6-luna, 응답 모델은 gpt-4o-mini-2024-07-18 / gpt-5.6-luna였다. 4o-mini temperature=0, Luna reasoning_effort=low 및 temperature 생략, 최대 출력 토큰 4096. 같은 입력·JSON schema 해시를 9쌍에서 확인했고 실행 전후 소스 해시가 일치했다. 각 모델에 원문과 식별자만 전달했으며 제안 라벨은 전달하지 않았다.

저장된 120개 해석 결과를 합성 read-only tool과 실제 LangGraph에 재생했다. 사람 승인 필요와 mutation 미시도, 정책상 허용 action 범위가 120개 모두 유지됐다. 단일 추천 action의 정답 순위는 채점하지 않았으며, tool path 정확도·불필요한 도구 호출·실제 DB 기반 추론 성능은 이번 모델 비교에서 측정하지 않았다. PostgreSQL 격리 회귀 테스트를 포함한 209 passed는 별도의 구현 검증이다.

사람 검수 상태는 48개 모두 pending이며 정식 release/export는 계속 차단된다. 후보 JSON의 model_calls_on_this_dataset=0은 작성 당시의 고정 스냅샷 값이며, 현재 누적 실행 수를 뜻하지 않는다. 이번 실행 기록은 아래 파일을 기준으로 한다.

## 실행 증거

- [고정 입력·설정·소스 해시](draft-comparison-2026-09-14/registration.json)
- [모델 응답·요청 수·토큰·지연](draft-comparison-2026-09-14/comparison.json)
- [불일치 상세와 LangGraph 재생](draft-comparison-2026-09-14/audit-and-replay.json)

실행 기준 커밋: f9a94d7a43cb626a5c0206747fd60722f8a3fe28.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --prepare --allow-draft --gold-dataset tests/fixtures/decision_gold/v1/candidates.json --output-dir /private/tmp/new-draft-comparison
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --run --allow-draft --gold-dataset tests/fixtures/decision_gold/v1/candidates.json --env-file /path/to/approved.env --output-dir /private/tmp/new-draft-comparison
```

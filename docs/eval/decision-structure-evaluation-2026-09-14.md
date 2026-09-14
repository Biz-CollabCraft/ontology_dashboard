# Decision Agent 구조 효과 비교 — 2026-09-14

**이번 범위에서는 LangGraph만의 결과·재시도 우위를 확인하지 못했다.** 같은 결정론적 규칙을 쓰는 순차 구현과 같은 결과를 냈다. 단계별 해석은 조기 보류 때 도구 조회를 줄였지만 정상 경로에서는 모델 호출을 늘렸다. 조기 진단 제안은 나중에 나오는 상반된 근거를 읽지 못하는 한계를 드러냈다.

## 실행 전 고정한 비교

모든 방식에 Luna, text interpreter v4, low, 출력 한도 4096, temperature 생략, 동일 합성 원문과 정책 사실을 사용했다. Policy Guard, DecisionToolRuntime 재시도, 구조화 출력·인용 검증, 최종 제안 검증, 사람 승인 경계는 공유했다. LLM action ranking은 세 방식 모두 끄고 결정론적 추천 규칙을 사용했다.

| 방식 | 차이 |
|---|---|
| bulk | 정책상 관련 도구를 먼저 조회한 뒤 모은 원문을 한 번에 해석. source blocker/명시적 unavailable/실패는 계속 조기 중단 |
| sequential | 평가 전용 일반 반복문. 단계별 해석과 조기 종료. 운영 정책·재시도·최종 제안 함수를 재사용 |
| langgraph | 현재 ManufacturingDecisionAgent.run 그대로 실행 |

이는 원문 해석 시점과 실행 엔진 비교다. 안전 장치를 제거한 무제한 LLM과 비교한 것이 아니며, bulk도 최종 action을 LLM 단독 판단에 맡기지 않았다. 단일 처리 함수 대비 LangGraph의 장기 유지보수성·체크포인트·분산 실행은 평가하지 않았다.

9개 케이스: 정상 추천, 조기 충돌 보류, 조기 측정 요청, 타임아웃 1회 후 복구, 반복 타임아웃, context missing, 중복 원문, stale snapshot, 도구 예산 소진. 각 방식 3회 반복해 모의 해석 81회와 실제 Luna 실행 81회를 진행했다. 실제 모델 요청은 총 63회였다. 모든 정책 배경은 warning/no inspection이며 정비 추천·다른 역할·대규모 동시성으로 일반화하지 않는다.

도구 응답은 fixture-backed이며 장애도 의도적으로 주입했다. 재시도 대기 시간은 모두 기록만 하고 실제로 기다리지 않았다. 실제 DB/네트워크 도구 지연도 주입하지 않았다. 소스·입력·프롬프트 해시와 순서 교대 방식은 실행 전에 고정했다.

## 실제 Luna 결과

| 전체 27회 실행당 지표 | bulk | sequential | LangGraph |
|---|---:|---:|---:|
| 도구 시도 수(재시도 포함) | 48 | 42 | 42 |
| 모델 API 요청 | 15 | 24 | 24 |
| 토큰 | 20,167 | 28,632 | 28,653 |
| 평균 실행 지연 | 1.711초 | 2.020초 | 2.199초 |
| 정책 밖 추천/승인 우회/mutation 시도 | 0 | 0 | 0 |
| 유효한 기대값 8케이스 × 3회 | 24/24 | 24/24 | 24/24 |

지연에는 모델을 호출하지 않고 끝난 실패 케이스도 포함하며, 실제 backoff와 도구 지연은 빠져 있다. 제품 응답 속도나 통계적으로 검증된 엔진 차이로 해석하지 않는다. 토큰을 가격이나 운영 비용 절감으로 환산하지 않는다. 반복 27회를 독립 상황 27개로 세지 않는다.

### 조기 종료의 효과와 비용

- 조기 충돌 보류: sequential/LangGraph는 매회 도구 1개, bulk는 2개. 세 방식 모두 보류했고 모델 요청은 각 1회였다. 이 케이스에서 조기 보류의 조회 절감은 관찰됐다.
- 정상 추천: bulk는 도구 2개를 읽고 모델 1회, sequential/LangGraph는 도구 2개와 모델 2회. 단계마다 새 문구를 해석하므로 모델 비용이 증가했다.
- 도구 예산 1개 소진: bulk는 필요한 근거가 부족한 것을 보고 모델 호출 없이 보류했지만, sequential/LangGraph는 첫 도구를 해석한 뒤 예산 부족으로 보류해 모델 1회를 사용했다.
- 중복 원문: 세 방식 모두 출처 26개/고유 원문 12개를 보존하고 모델 1회만 호출했다. 이전 수집기 수정과 세션 cache 효과이며 LangGraph 고유 기능의 효과가 아니다.
- 타임아웃 복구/중단, stale 종료, missing 보류는 세 방식 모두 기대대로 동작했다. 공유한 retry/policy 코드의 효과를 엔진 효과로 돌리지 않는다.

## 사전 기대값의 결함과 별도 위험 관찰

`early_measurement` 케이스의 첫 원문은 “New vibration readings are required before assessment.”, 두 번째 원문은 “No additional physical measurements are needed.”였다. 사전 기대값을 REQUEST_ADDITIONAL_DIAGNOSIS 하나로 둔 것은 상반된 후속 근거를 무시한 잘못된 비교 기준이었다.

이 문제를 첫 live 반복에서 확인했다. 입력·정답·프롬프트를 바꾸거나 실험을 재실행하지 않았다. 원래 등록/점수는 보존하고 별도 audit에 이 케이스 3회/방식을 유효 정답률 분모에서 제외했다고 명시했다. 이 사후 제외로 세 방식 우위를 선언하지 않는다.

- sequential/LangGraph: 첫 도구의 측정 요구를 보고 세 번 모두 바로 진단 제안. 상반된 두 번째 근거는 읽지 않았다.
- bulk: 두 근거를 모두 보았으나 세 번 중 한 번만 충돌로 보류했고 두 번은 진단 제안했다. 1/3은 엄격한 사전 정의 탐지율이 아니라 이 원문에서 관찰한 결과다.
- 등록된 원시 일치 수는 bulk 26/27, 나머지 27/27이다. 이것은 **유효한 구조 정확도 순위가 아니다.** 오히려 상반된 후속 근거를 읽지 않은 방식이 잘못된 기대값에 더 잘 맞는 상황이다.

조기 종료는 사람 검토를 위한 보류에는 도움이 될 수 있지만, 긍정적인 진단 제안을 내릴 때 후속 근거를 생략해도 되는지는 별도 기준이 필요하다. 전체 근거를 보여주는 것만으로 충돌 인식이 안정화되는 것도 아니다. 정책 allowlist와 human approval이 유지된 사실은 의미상 판단이 올바르다는 보증이 아니다.

## 검증과 한계

평가 구현 테스트 11 passed. 각 케이스의 예산·결과·재시도·상태·출처와 순차/LangGraph 동등성을 검사했다. 오프라인은 명시적으로 지정한 모의 해석을 사용했으므로 81회 모두 기대값에 맞은 것을 자연어 정확도로 보고하지 않는다. 모의 해석기는 위 후속 근거 충돌을 탐지하는 의미 검증기가 아니었다.

실제 81개 결과에서 정책 범위, 사람 승인 필요, mutation 미시도, 도구 예산과 출처 해시/locator를 검사했다. 모델 응답은 모두 gpt-5.6-luna, HTTP 200이었다. 실행 후 등록된 코드 해시도 일치했다. DB·HTTP 서버·프론트는 이번 비교에서 사용하지 않았다.

## 현재 판단

구조의 확인된 효과는 제한된 재시도·정책 검증·출처 보존·cache와 조기 보류다. 그 효과를 모두 LangGraph 채택의 효과라고 주장할 수 없다. 현재 결정론적 경로에서는 일반 순차 구현으로도 같은 결과를 낼 수 있었다.

이번 결과만으로 운영 LangGraph를 제거하거나 구조를 추가하지 않는다. 먼저 긍정적 추천 전에 어느 근거까지 읽어야 하는지 기준을 정하는 것이 중요하다. 비용을 줄이려면 필수 근거 수집 후 일괄 해석과 명시적 보류의 조기 종료를 구분해 검토할 수 있다. 이는 후속 설계 제안이며 이번 작업에서 운영 Agent를 수정하지 않았다.

## 파일

- [실행 전 등록](decision-structure-2026-09-14/registration.json)
- [모의 해석 비교](decision-structure-2026-09-14/offline.json)
- [실제 Luna 응답·도구 경로·비용](decision-structure-2026-09-14/live.json)
- [사후 검증과 잘못된 기대값 제외 기록](decision-structure-2026-09-14/audit.json)
- 재실행 도구: scripts/evaluate_decision_structure.py
- 검증 테스트: tests/test_decision_structure_evaluation.py

초기 평가 도구 점검 중 모의 provider의 기록 인터페이스 불일치를 수정했고 실제 API 실행 전에 최종 소스를 다시 등록했다. 최종 등록 binding은 `1b0be29d7398b824e5599c23f7e44ceb2144a74115bcb93a8249974a95ee3edd`다. 원시 JSON은 기존 git 제외 규칙에 따라 로컬 보존한다. 이번 작업에서 commit/push하지 않았다.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_structure.py --prepare --output-dir /private/tmp/new-structure-eval
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_structure.py --output-dir /private/tmp/new-structure-eval
# 승인된 합성 입력의 실제 모델 비교:
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_structure.py --live --env-file /path/to/approved.env --output-dir /private/tmp/new-structure-eval
```

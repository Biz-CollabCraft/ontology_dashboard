> 과거 실험 기록: 작성 당시 코드·프롬프트·입력·채점 조건의 결과입니다. 현재 demo의 검증 결과나 모델 선정으로 해석하지 않습니다. 개인 경로는 당시 산출물 위치이며 새 체크아웃에 포함되지 않을 수 있습니다. [흡수 범위와 재실행](evaluation-experiments-absorption-20260908.md)

# GPT-5 mini·GPT-5.6 Luna 추가 비교

Evidence: 실제 OpenAI API 응답, 고정 합성 fixture 8개 × 모델별 2회 × 3모델 = 48회. 운영 DB는 사용하지 않았다.

- 시작: 2026-09-07T11:22:52.553531+00:00
- 완료: 2026-09-07T11:30:43.932594+00:00
- 사전 기준에 따른 선택: **gpt-4o-mini-2024-07-18**

| 모델 | 원출력 자동 점수 | 직접 통과 | fallback 후 제공 점수 | 중앙 응답시간 | p95 | 16회 추정 비용 |
|---|---:|---:|---:|---:|---:|---:|
| GPT-4o mini | 0.920139 | 16/16 | 0.920139 | 5.022초 | 5.840초 | $0.019860 |
| GPT-5 mini (low) | 0.937500 | 15/16 | 0.937500 | 10.217초 | 14.304초 | $0.054079 |
| GPT-5.6 Luna (low) | 0.913194 | 16/16 | 0.913194 | 6.794초 | 8.117초 | $0.032433 |

## 해석과 제한

- 품질 하한 0.80, 기준 모델 대비 허용 하락 0.05, 직접 통과 하한 100%, 모델별 2회 반복을 호출 전에 고정했다. 통과 후보 중 uncached 단가 기반 평균 비용을 최소화하고 p95를 차선 기준으로 사용한다.
- 이전 실험과 system prompt, 입력 packet/context, 출력 schema, 3역할 gold는 동일하다. GPT-4o mini도 이번에 16회 새로 실행했다.
- GPT-5 mini와 Luna는 reasoning_effort=low, temperature 생략. GPT-4o mini는 temperature=0, 추론 설정 없음. 공통 max_completion_tokens=4096, timeout=90초. 동일 모델 설정이라고 주장하지 않는다.
- 첫 비교의 비용 60.8% 차이는 GPT-4.1 mini와의 비교다. 이번 새 후보 비교에 그대로 적용하면 안 된다.
- 자동 점수는 필수 사실·역할 표현 포함과 금지 표현 검사를 합산한 proxy다. 사람의 자연스러움·유용성·판단시간 평가는 미실시다.
- 직접 통과는 raw editable JSON schema 및 merge 이후 grounding 계약을 모두 통과한 비율이다. 제품 merge보다 raw schema 평가가 엄격할 수 있다. fallback 점수를 모델 성능으로 사용하지 않는다.
- 비용은 provider 사용량에 공식 uncached input/output 단가를 적용한 추정이다. 출력 token에는 provider가 보고한 reasoning token이 포함될 수 있다. 실제 청구·cached 할인 대사는 하지 않았다.
- 응답시간은 transport와 provider 내부 schema 재시도를 포함한다. p95는 기존 harness 유한표본 계산이며 장기 tail 보장이 아니다.
- Luna는 문서와 계정에서 확인한 gpt-5.6-luna ID를 사용했다. 별도의 날짜 snapshot이 없으므로 불변 버전을 보장하지 않는다. 각 응답의 반환 model ID와 usage detail은 transport_metadata에 보관했다.

## 거절 이유

- GPT-4o mini: 없음
- GPT-5 mini (low): EVT-GS-002 / 반복1: editable_contract_failed
- GPT-5.6 Luna (low): 없음

## 실제 사용량

| 모델 | 입력 tokens | 출력 tokens | 총 tokens |
|---|---:|---:|---:|
| GPT-4o mini | 101252 | 7787 | 109039 |
| GPT-5 mini (low) | 101236 | 14385 | 115621 |
| GPT-5.6 Luna (low) | 101236 | 10155 | 111391 |

## 보관 및 재현

- registration.json: 사전 기준, 설정, 입력 binding hash
- frozen-inputs.json: 실제 packet/context/system prompt/schema/gold
- comparison.json: 원출력 prose, 수락/거절, fallback, 실제 usage·응답시각·모델별 설정
- batch-*.json 및 checkpoint-*.json: 중간 응답 보관
- manifest.json: 산출물과 실행 코드 SHA-256
- 같은 질문의 실제 문장 비교는 natural-language-samples.md 참조. 모델의 평가용 원문이며 채택된 제품 문구가 아니다.

검증: 비교 harness 및 모델별 요청 설정 테스트 47 passed. 제품 런타임의 기본 모델/프롬프트/생성 정책은 수정하지 않았다. 커밋·푸시 없음.

단가·모델 근거: [GPT-5 mini](https://developers.openai.com/api/docs/models/gpt-5-mini), [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini).

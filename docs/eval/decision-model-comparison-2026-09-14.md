# Decision Agent 문구 해석 모델 비교 — 2026-09-14

## 결론

동일한 현재 프롬프트·응답 schema·합성 입력으로 비교했을 때 주요 분류 품질은 Luna가 우수했다. 기존 4o-mini의 충돌 오탐과 불필요 보류는 이번 Luna 평가에서는 재현되지 않았다. 따라서 이전 오류를 Luna나 시스템 전체의 불가피한 한계로 일반화하지 않는다. 다만 추가 필드의 오분류, 제한된 사례 수와 응답 시간의 한계는 남는다.

## 실제 사용한 모델과 조건

- 요청 gpt-4o-mini → API 응답 gpt-4o-mini-2024-07-18. temperature=0.
- 요청 gpt-5.6-luna → API 응답 gpt-5.6-luna. reasoning_effort=low, temperature 미지정.
- 공통: api.openai.com/v1/chat/completions, max_completion_tokens=4096, timeout=90초, strict JSON schema. 모델별 지원 설정이 다르므로 모든 sampling 설정이 동일하다고 주장하지 않는다.
- .env에서 자격 증명과 endpoint만 읽는다. LLM_MODEL은 사용하지 않고 비교 모델을 코드에서 명시한다. 응답 모델이 요청과 다르면 실패 처리한다. 응답 모델, finish reason, 토큰, 입력/schema 해시를 기록한다.

Luna는 기존 scripts/run_pr167_extended_comparison.py, scripts/run_luna_120_stability.py 및 .env.example에서 확인했다. 앞선 평가가 4o-mini였던 원인은 실제 .env에 남아 있던 과거 값을 재사용하고 새 평가 도구에 4o-mini 제한을 넣은 것이다. 이번 결과를 기존 4o-mini 기록 위에 덮어쓰지 않았다.

## 고정한 평가 범위

모호 표현 24개 + 기존 회귀 11개 = 35개 문장을 모델별 3회, 총 210개 분류로 비교했다. suite별 8문장 이내로 묶고 두 모델의 실행 순서를 교대했다. 등록 이후 프롬프트나 gold를 변경하지 않았다. 15쌍 모두 실제 전송 입력과 schema 해시가 동일함을 확인했다.

binding: `689aa5c80eee21bfbdfeb2e7dd54a686a31997517908fd35f3301437d94a224f`

현재 문구 해석과 deterministic 추천 조합의 비교이며, LLM action ranking 전체나 운영 backend 지연을 재평가한 것은 아니다. 기존에 수정·평가에 사용한 합성 문장을 재사용하므로 독립 holdout이나 실제 현장 정확도가 아니다. 현재 프롬프트는 과거 4o-mini 결과를 보며 수정된 상태이며 모델 간 비교 중에는 고정했다.

## 결과

| 지표 | 4o-mini | Luna |
|---|---:|---:|
| 주요 세 flag 전체 일치(충돌/측정 요구/불명확함) | 87/105 (82.9%) | 105/105 (100%) |
| 모호 표현 suite의 주요 flag 일치 | 60/72 | 72/72 |
| 기존 회귀 suite의 주요 flag 일치 | 27/33 | 33/33 |
| 근거 충돌 오탐 | 15/99 | 0/99 |
| 필요한 사람 검토 누락 | 0/45 | 0/45 |
| 불필요한 사람 검토 보류 | 3/60 | 0/60 |
| 측정 요구 오탐 / 실제 요구 누락 | 0/93, 0/12 | 0/93, 0/12 |
| 응답 처리 오류 | 0/105 | 0/105 |
| 정보 누락 여부 일치(추가 gold 있는 suite만) | 48/72 | 66/72 |
| 측정 상태 세부 분류 일치(추가 gold 있는 suite만) | 45/72 | 59/72 |
| 실제 LangGraph 경로 재생 일치 | 102/105 | 105/105 |
| API 요청 / HTTP 요청 / JSON object 재시도 | 15 / 15 / 0 | 15 / 15 / 0 |
| 전체 토큰 | 21,155 | 25,093 |
| 평균 배치 응답 시간 | 3.320초 | 9.823초 |

Luna의 105/105는 세 가지 주요 분류만의 일치다. 모든 출력 필드가 100%라는 뜻이 아니다. 각 모델은 35개 문장을 반복했으며 105개 독립 사례가 아니다. 측정 상태 추가 gold가 없는 기존 회귀 suite는 해당 필드 정확도 분모에서 제외했다.

API 응답 시간은 3개 또는 8개 문장의 묶음 단위이며, 사용자 화면 응답 시간으로 환산하지 않는다. Luna는 이 조건에서 약 2.96배 느렸고 전체 토큰은 약 18.6% 많았다. 가격표를 새로 검증하지 않았으므로 비용 우열은 계산하지 않았다.

기록된 모델 출력을 실제 LangGraph와 합성 read-only 도구로 재생했다. 모든 210건에서 human approval required 및 mutation_attempted=false를 확인했다. 새 live 모델 호출이나 실제 DB를 통한 추론이 아니므로 재생 증거로 구분한다.

## 품질 판단과 남은 확인

Luna low를 다음 버전의 평가 기준으로 삼는 것이 타당하다. 현재까지의 특정 충돌 오탐/불필요 보류는 '4o-mini에서 관찰, Luna 비교에서는 미재현'으로 표시한다. 정보 누락과 측정 상태 세부 분류, 독립 새 사례, 실제 화면에서의 원문 확인 흐름은 아직 한계/미검증이다.

이번 작업은 비교 평가만 수행했다. 실제 .env, 배포 서버, 기본 provider 설정은 변경하지 않았다. 앱 런타임에 Luna를 적용할 때는 LLM_MODEL뿐 아니라 reasoning_effort=low 등 평가 조건도 일치하는지 별도로 확인해야 한다. API의 모델 이름 기록은 외부 서비스의 내부 weights가 영구 고정됨을 보장하지 않는다.

PostgreSQL 임시 DB를 포함한 관련 코드 테스트는 **200 passed, 0 skipped (24.06s)**이고 `git diff --check`도 통과했다. 프론트·도메인 mutation·commit/push는 수행하지 않았다.

## 재현

모델 비교는 `scripts/evaluate_decision_model_comparison.py`를 사용한다. 이전 evaluate_decision_text_interpreter.py와 단일모델 도구의 4o-mini 실행 기록은 역사적 평가이며, 현재 모델 비교에 그대로 사용하지 않는다.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --prepare --output-dir /private/tmp/new-model-comparison
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --run --env-file /path/to/approved.env --output-dir /private/tmp/new-model-comparison
```

등록 이후 소스·입력·설정 hash가 달라지면 실행을 거부한다. 완료된 배치는 재호출하지 않고 이어서 실행한다. 원시 결과는 기존 Git 제외 규칙대로 로컬 보존한다.

- [등록된 입력·프롬프트·설정·소스 hash](decision-model-comparison-registration-2026-09-14.json)
- [요청·응답 모델과 원시 비교 결과](decision-model-comparison-comparison-2026-09-14.json)
- [LangGraph 재생](decision-model-comparison-agent-replay-2026-09-14.json)

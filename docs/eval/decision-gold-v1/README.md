# Decision Agent 골드셋 v1 — 사람 검수 대기

**현재 산출물은 골드셋 초안이며, 검수된 정답셋이 아니다.** 합성 48사례 중 44개에 정답을 제안하고 조건부/생략된 지시 4개는 미정으로 남겼다. 사람 검수 0/48, 모델 호출 0건이다. 실제 점검 문구는 제공되지 않아 사용하지 않았다.

## 먼저 검수할 문서

1. [라벨 기준과 품질 검증 절차](rubric-and-protocol.md)를 확인한다.
2. [개발용 원문 24개](review-development.md)와 [평가 후보 원문 24개](review-evaluation.md)를 가능하면 정답 제안 없이 독립적으로 판단한다.
3. [정답 제안서](annotation-proposals.md)와 대조하고, 이견을 기록한다. 특히 D05-03, D05-04, H05-03, H05-04는 기준 결정이 필요하다.
4. 합의된 정답과 검수자를 데이터에 기록한 뒤 최종 평가 후보를 확정한다. 평가 후보를 보고 프롬프트를 수정했다면 해당 세트는 개발/회귀로 이동시키고 새 평가 후보를 준비한다.

동일한 문장 틀을 다른 장비에 적용한 사례들은 하나의 family로 묶었다. F01/F02/F04는 개발용, F03/F05/F06은 평가용이며 각 24개다. 분할 단위는 6개 family이므로 48개 완전히 독립 상황으로 주장하지 않는다. 원문 근접 중복과 분할 적절성도 사람이 검수해야 한다. 작성자가 양쪽 내용을 봤으므로 작성자에게 블라인드인 세트도 아니다.

## 데이터와 고정 상태

데이터: `tests/fixtures/decision_gold/v1/candidates.json`
현재 파일 SHA256: `a65b3dd75543e7e93601d0a5ce0346cef2736bb412f76d3ba6f9fe26c48ab284`

각 사례에는 source/ref, 배경과 정책상 허용 action, 제안 라벨, 행동 제약, 원문 근거, 검수 질문, 검수자/검수 시각/승인한 내용 해시 필드가 있다. `pending`은 검수 완료가 아니다. 수정하면 내용 hash를 다시 계산하고 기존 승인을 재검수해야 한다. hash는 정답의 정확성이나 검수자의 자격을 보증하지 않는다.

검수 완료 전에 최종 평가용 export를 거부한다. 자동 승인·정답 자동 확정 기능은 없다. --export-dir 경로가 이미 있으면 이전 버전을 덮어쓰지 않는다.

```sh
python3 scripts/validate_decision_gold.py tests/fixtures/decision_gold/v1/candidates.json
python3 scripts/validate_decision_gold.py tests/fixtures/decision_gold/v1/candidates.json --release-check
# 전체 검수와 미정 사례 조정 이후에만 성공한다.
python3 scripts/validate_decision_gold.py tests/fixtures/decision_gold/v1/candidates.json --export-dir /private/tmp/reviewed-decision-gold-v1
```

현재 구조 검사: 오류 0. 미검수/미정 release 차단: 48건. 골드셋·모델 비교 관련 검사 테스트: 14 passed. 이 수치는 골드 정답의 정확도나 모델 품질 점수가 아니다.

## 이전 결과 취급

Luna 105/105와 4o-mini 87/105는 이전 합성 사례에서의 탐색적 비교다. 이 새 초안에 대한 결과가 아니다. 최종 비교는 정답 검수·확정 후에만 진행한다. 새 초안으로 모델 추론이나 추가 프롬프트 튜닝은 실행하지 않았다.


## 검수 후 모델 비교 연결

모델 비교 도구에도 검수 검사를 연결했다. `--gold-dataset`을 지정하면 데이터 전체의 검수·미정 상태를 먼저 검사하고, 통과한 경우에만 evaluation 분할을 사용한다. 현재 초안은 --prepare 단계부터 거부되므로 API 호출까지 진행되지 않는다. 이 연결도 오프라인으로 검증했다.

```sh
# 모든 검수가 끝난 다음 실행한다. 지금은 실패하는 것이 정상이다.
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --prepare --gold-dataset tests/fixtures/decision_gold/v1/candidates.json --output-dir /private/tmp/reviewed-gold-comparison-v1
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_model_comparison.py --run --gold-dataset tests/fixtures/decision_gold/v1/candidates.json --env-file /path/to/approved.env --output-dir /private/tmp/reviewed-gold-comparison-v1
```

등록 후 정답·프롬프트·소스가 바뀌면 모델 호출을 거부한다. --gold-dataset을 생략한 기존 실험은 과거 35문장 탐색 비교이므로 이 골드셋 평가로 보고하면 안 된다.

## 명시적인 초안 평가

사용자가 요청한 탐색 비교에는 `--gold-dataset ... --allow-draft`를 prepare/run 양쪽에 명시한다. 이 경우 평가 분할 24개 중 제안 라벨이 있는 20개만 비교하고, 미정 4개 ID를 등록 파일에 남긴다. 결과는 검수 전 제안 라벨과의 일치도이며 검증된 골드 정확도가 아니다. 검수 상태와 release/export 차단은 유지한다. 기본 모드는 계속 사람 검수를 요구한다.

# Decision Agent recommendation semantics — v2

DecisionAction은 사람에게 제안할 다음 검토 행동이다. 정비·설비 정지·발주·예약·승인을 실행하지 않는다. Policy Guard의 허용 목록 안에서만 추천하며 모든 proposal은 human approval required를 유지한다.

| Action | 의미 | 의미하지 않는 것 |
|---|---|---|
| MONITOR | 현재 관찰을 이어간다 | 추가 측정 요구가 해결됨, 위험 없음 보장 |
| REQUEST_ADDITIONAL_DIAGNOSIS | 부족한 측정·진단 근거를 보강하도록 요청한다 | 점검이나 정비 실행 |
| REQUEST_INSPECTION | 현장 물리 점검을 요청한다 | 점검 결과가 이미 확보됨 |
| REQUEST_MAINTENANCE | 담당자에게 정비 필요성 검토를 요청한다 | 즉시 정지, 작업 승인, 자원 확보 |
| REVIEW_PLANNED_MAINTENANCE | 생산 영향·일정·정비 창·자원 조건을 비교 검토한다 | 일정 확정 또는 작업 실행 가능 보장 |

정비 필요성이 확인되면 두 정비 관련 action 모두 타당할 수 있다. 일정과 자원 제약이 있을 때 계획 검토를 우선할 수 있지만, 정비 요청 자체를 오답으로 단정하지 않는다. 납기 압박은 설비 긴급도가 아니며, 전량 예약은 이번 정비의 예약 소유 관계가 아니다.

## 근거와 보호 경계

- `recommendation_blockers`: 근거 제공자가 명시한, 추천 전에 사람이 해소해야 하는 사유 목록. 일반 `limitations` 및 실행 준비 문제인 `blocking_reasons`와 구분한다. 서버가 추천을 보류하고 원인·source refs를 남긴다. LLM이 이 필드를 생성하거나 갱신하지 않는다.
- 신규 blocker는 packet 또는 maintenance-readiness context에서 읽는다. 기존 fixture에는 빈 배열이 기본이다. 운영 DB나 센서 producer가 이 값을 생성하는 통합은 이번 변경에 포함하지 않는다.
- `additional_measurement_required=true`: 출처가 추가 측정 필요성을 명시한 경우 진단 보강을 선택할 수 있다. unknown이나 자연어의 단어만으로 true를 만들지 않는다.
- 조회 결과가 available이 아니면 추천을 보류한다. 일반 limitation만으로 모든 추천을 차단하지 않는다.
- 정비 창 부적합·예약 소유 관계 미확인·가용 재고 부족·납기 압박은 양쪽 proposal의 uncertainties에 보존한다.

## 도구 선택과 진단 기록

현재 policy의 판단 범위에 필요한 도구만 후보로 제공한다. 점검 미확인 사건은 condition/inspection, 정비 사건은 maintenance/production/readiness, 점검 완료 후 관찰은 condition이다. LLM은 후보 안에서 조회 순서를 선택한다. 명시적 보류 또는 충분한 추가 측정 근거가 있으면 단축 경로로 끝난다. 이는 서버가 범위를 제한한 설계이며 자유로운 도구 발견을 평가하는 구조가 아니다.

LLM 응답 schema에도 남은 도구 enum을 반영한다. 남은 필수 조회가 없으면 종료용 API를 부르지 않는다. 조기 종료·잘못된 도구 선택은 기록하고 deterministic 조회로 진행한다. 실패·전체 호출 예산 소진은 종료하며, retry도 전체 tool call 한도를 넘기지 않는다.

`DecisionSession.planner_errors`는 fallback 원인을 담고 `recommendation_gate_reason`은 근거 보류 원인을 담는다. 기존 engine 문자열만으로 순수 LLM 성공이라 판정하지 않는다. 두 필드는 기본값이 있어 기존 session 입력과 호환된다. 기존 service는 session을 메모리에 보관하므로 DB 영속화로 표현하지 않는다.

## 평가 해석

- 허용 답 일치와 선호 답 일치를 따로 기록한다. 허용 답 확대 자체는 모델 개선이 아니다.
- 서버의 blocker 보류 성공은 LLM의 충돌 이해 성공으로 집계하지 않는다.
- 이전 입력·정답 기준은 raw artifact manifest로 그대로 재생할 수 있다. 새로운 기준의 점수를 이전 기준과 직접 비교하지 않는다.
- 이 해석은 현재 제품의 명시적 구현 기준이다. 독립 현장 전문가가 확정한 최적 행동이나 새로운 holdout 성능을 뜻하지 않는다.

## 자연어 해석 계층

`StructuredTextEvidenceInterpreter`는 source의 문자열을 별도 해석하며 원본 `recommendation_blockers`나 `additional_measurement_required`를 수정하지 않는다. `DecisionSession.text_interpretations`에는 `origin=llm_interpretation`, 원문 전체, tool/field/source/as-of, conflict/measurement/uncertain flag를 보존한다. 원문은 모델이 재작성하지 않고 서버가 근거 ID로 결합한다. 구조·출처 일치는 해석의 의미적 정확성을 증명하지 않는다.

명시적 source blocker가 우선하며, 해석된 충돌/불확실성은 사람 확인을 위해 보류한다. 해석된 추가 측정 요구는 기존 policy가 허용할 때 낮은 신뢰도의 추가 진단 제안으로 연결한다. 해석 오류는 `text_interpretation_errors`에 기록하고 보류한다. 결과를 confirmed_facts로 승격하지 않는다.

현재 LLM 설정이 활성화된 service는 planner와 text interpreter를 모두 연결한다. `ManufacturingDecisionAgent(planner=None, text_interpreter=...)`는 텍스트 해석만 LLM에 맡기는 별도 구성이며 순수 deterministic이 아니다. 평가의 `text-comparison`은 이 구성을 구분하고 텍스트 API/추천 API/전체 token을 분리 기록한다.

[기존 입력 재평가 및 오탐 기록](../eval/decision-text-interpretation-evaluation-2026-09-14.md)을 참고한다. 이 구현은 제공된 문구의 명시적 의미를 추출하며, 여러 독립 원천을 통합해 새로운 충돌을 발견하는 시스템은 아니다.

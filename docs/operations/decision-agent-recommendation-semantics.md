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

LLM 설정이 활성화된 service의 기본 구성은 `ManufacturingDecisionAgent(planner=None, text_interpreter=...)`이다. LangGraph가 조회와 종료를 관리하고, LLM은 문구를 해석하며, deterministic 규칙이 추천을 선택한다. 순수 deterministic은 아니다. `DECISION_AGENT_PLANNER=llm`을 명시하면 기존 LLM 도구 선택·액션 ranking 실험 구성을 사용한다. 기본값은 `deterministic`이고 알 수 없는 설정이나 offline provider와 llm planner의 조합은 오류로 거부한다. 평가의 `text-comparison`은 이 구성을 구분하고 텍스트 API/추천 API/전체 token을 분리 기록한다.

[기존 입력 재평가 및 오탐 기록](../eval/decision-text-interpretation-evaluation-2026-09-14.md)을 참고한다. 이 구현은 제공된 문구의 명시적 의미를 추출하며, 여러 독립 원천을 통합해 새로운 충돌을 발견하는 시스템은 아니다.


## 정보 누락과 측정 요구 분리 (2026-09-14 후속)

원문 해석은 `information_missing`와 `measurement_status`를 별도로 출력한다. status는 `required`, `not_required`, `optional`, `not_stated`, `unclear` 중 하나다. 서버는 `required`에서만 기존 `measurement_required=true`를 산출한다. `unclear`는 불확실성으로 보류하며 정보 누락만으로 진단을 요청하지 않는다.

`required` 응답은 `measurement_evidence`에 원문에 실제 존재하는 구절을 포함해야 한다. 필수 측정의 인용 누락·빈 문자열·원문 밖 구절은 전체 batch를 거부하고 캐시에 게시하지 않는다. 선택적 측정이나 불필요한 측정의 정확한 원문 인용도 보존할 수 있지만, 인용의 존재만으로 측정 요구를 만들지 않는다. 이 검사는 출처 연결만 확인하며, 부정어나 조건을 잘못 해석하는 문제까지 증명하지 않는다. 전체 원문도 계속 보존한다. 기존 session의 추가 필드는 기본값으로 역호환한다.

[후속 평가와 PostgreSQL 재검증](../eval/decision-text-boundary-evaluation-2026-09-14.md)에 개선과 남은 불확실성 누락을 함께 기록했다. 실제 배포·현장 검증 완료를 뜻하지 않는다.


## 모호 표현 분류 후속 (2026-09-14)

`meaning`은 record_review/new_measurement/ambiguous_request/ambiguous_other/clear_other를 구분한다. 의미가 모호하면 기존 사람 검토 보류 경로를 사용한다. `measurement_required`는 status=required이면서 meaning=new_measurement일 때만 true다. 기록 조회만으로 측정 요구를 만들지 않는다. 의미나 충돌 분류는 여전히 모델의 해석이며 확정 사실이 아니다.

API에는 배치 내부의 짧은 ID(e0 등)와 그 enum/개수 제약을 제공한다. 서버는 응답의 중복·누락을 검증한 뒤 원본 SHA256 ID로 복원하므로 cache와 source locator는 바뀌지 않는다. 모델이 해시 한 글자를 빠뜨려 전체 batch가 실패하는 문제를 줄인다.

[모호 표현 평가 결과](../eval/decision-text-ambiguity-evaluation-2026-09-14.md)는 검토 경로 정확도와 세부 분류 오류를 분리한다. 모호 표현을 충돌로도 표시하는 오탐과 기존 정보 누락 문구의 불필요 보류가 남아 있어 배포 완료나 전체 의미 해석 해결을 주장하지 않는다.


## 모델별 품질 근거

[4o-mini/Luna 비교](../eval/decision-model-comparison-2026-09-14.md)에서 주요 세 flag는 4o-mini 87/105, Luna low 105/105였다. 기존의 특정 충돌 오탐/불필요 보류는 4o-mini 관찰이며 Luna에서는 미재현이다. 정보 누락/측정 상태 세부 분류는 Luna에서도 완벽하지 않다. 평가 결과와 실제 runtime 설정은 별개이며 이번 비교는 .env나 배포 설정을 변경하지 않았다. 모델 비교는 명시적 모델과 응답 모델 검증이 있는 evaluate_decision_model_comparison.py를 사용한다.

## 선택한 기준 버전

2026-09-14 사용자 승인으로 [Luna + text interpreter v4](decision-agent-luna-v4-baseline.md)를 로컬 Decision Agent 기준으로 선택했다. deterministic planner와 policy/human approval 경계는 유지하며, 세부 의미·조건부/복합 지시 한계는 해당 문서에 고정한다. 과거 평가 결과는 각 당시 설정의 증거로 보존한다.

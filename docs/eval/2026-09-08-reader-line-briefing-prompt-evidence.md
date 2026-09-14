> 과거 실험 기록: 작성 당시 코드·프롬프트·입력·채점 조건의 결과입니다. 현재 demo의 검증 결과나 모델 선정으로 해석하지 않습니다. 개인 경로는 당시 산출물 위치이며 새 체크아웃에 포함되지 않을 수 있습니다. [흡수 범위와 재실행](evaluation-experiments-absorption-20260908.md)

# Reader-Line AI Briefing Prompt Evidence

2026-09-08 기준. 상태: **프롬프트·표시 개선 적용 / 로컬 검증 완료 / 운영 배포·실제 DB 저장 미검증**.

## 문제

Luna 기반 역할별 브리핑은 사실 경계는 대체로 유지했지만, 발표 화면에 그대로 쓰기에는 표현 문제가 남았다.

- "운영 스냅샷", "계획 가정"처럼 내부 분류에 가까운 단어가 노출됐다.
- `maintenance_recommended`, `outcome` 같은 원천 코드가 본문으로 새는 위험이 있었다.
- 불릿과 근거 번호가 화면에서 시선을 끌어, 독자가 판단 문장보다 표식에 먼저 반응했다.
- 보전 화면 리플레이에서 AI 브리핑은 승인된 작업요청을 말하지만 주변 카드가 `작업지시 없음`으로 보이는 캡쳐 불일치가 있었다.

## 적용한 프롬프트 기법

- **Reader framing**: 역할 이름을 제삼자로 부르지 않고, 선택된 역할 사용자가 바로 읽는 문장으로 작성하게 했다.
- **Current-state first**: 첫 줄에 현재 승인 상태와 남은 결정을 먼저 쓰게 했다.
- **Evidence-bound wording**: 기록된 점검 결과, 작업요청 승인 상태, 승인 시각, 시작·완료 기록 부재를 분리해 쓰게 했다.
- **Missing-value phrasing**: "스냅샷 없음" 대신 실제 재고 수량, 작업 가능 시간, 담당자 배정처럼 누락된 값과 그 값이 막는 결정을 직접 쓰게 했다.
- **No invented operations**: 재고 수량, 담당자, 발주 시각, 도착 예정일, 실행·완료 상태를 입력 없이 만들지 못하게 했다.
- **Lead-time distinction**: 조달 예상 기간은 소요 기간으로만 표현하고, 납기나 도착일로 바꾸지 않게 했다.
- **Citation token separation**: 모델 원문에는 `[[ref:번호]]` 토큰을 유지하되, 화면에서는 번호 없는 `근거` 접기로만 보이게 했다.
- **Presentation rendering**: UI는 불릿 목록이 아니라 문장 줄을 단락처럼 표시한다. 줄 구분은 유지하고 불릿 점과 근거 번호는 제거했다.
- **Deterministic decision flow**: 코드가 `decision_flow`를 먼저 만들고, 프롬프트는 그 순서를 따라 자연어로만 엮게 했다. 구조는 고정하되 케이스별 내용은 입력 근거에 따라 달라진다.

프롬프트 버전은 `agent-review-summary-prompt-v3.2-threshold-to-decision`이다.

## 코드 변경 범위

- `systems/backend/app/operations/agent_review_summary_provider.py`
  - 역할별 quote를 3~5개 짧은 문장 줄로 유도한다.
  - 내부 표현(`스냅샷`, `계획 가정`, `데모`, `합성 데이터`, `outcome`, `maintenance_recommended`)을 재작성 대상으로 검사한다.
  - citation catalog에 없는 근거 토큰을 거부한다.
- `systems/backend/app/operations/agent_briefing_review.py`
  - "승인 여부가 아니라 착수 시점" 같은 정상 부정문을 승인 미확인으로 오판하지 않게 수정했다.
  - `build_decision_flow`를 추가해 위험 요인, 점검 대상, 점검 결과, 작업요청, 실행 기록 공백, 준비 공백, 생산 판단을 결정론적 순서로 정렬한다.
- `systems/frontend/src/standalone/briefFormat.js`
  - `**굵게**`와 ISO 8601 기록 시각의 표시 변환을 유지한다.
  - 근거 토큰은 안전한 텍스트 접기로만 표시하고, 번호는 화면에 노출하지 않는다.
  - 여러 근거가 있어도 한 문장 줄당 `근거` 접기 하나로 합친다.
- `systems/frontend/factory-status-original/index.html`
  - AI 브리핑 표시를 `<ul>/<li>` 목록에서 문장 줄 블록으로 바꿨다.

## Decision Flow v1

관계가 많아도 브리핑이 유기적으로 보이지 않던 원인은 모델이 근거를 문장 단위로 나열했기 때문이다. 이를 줄이기 위해 backend가 `decision_flow`를 결정론적으로 산출한다. 이 구조는 출력 문장이 아니라 prompt payload의 중간 근거 정렬이다.

고정된 순서는 다음과 같다.

```text
현재 상태 → 원인 관계 → 확인된 기록 → 남은 공백 → 다음 판단
```

승인 작업요청 캡쳐 케이스에서는 다음 chain이 생성된다.

```text
risk_factors_exceed_sop
→ inspection_targets_identified
→ inspection_result_recorded
→ work_order_approved
→ execution_not_confirmed
→ readiness_gap
→ production_decision
```

이 구조는 다음 경계를 코드에서 먼저 잡는다.

- 승인된 작업요청이 있으면 현재 단계는 `approved_work_order_pending_start`가 된다.
- 점검 결과와 작업요청은 같은 자산·이벤트·기준 시각에 맞을 때만 current evidence로 사용한다.
- 시작·완료 기록이 없으면 `execution_not_confirmed`를 넣어 실행 완료 주장을 막는다.
- 실제 재고 수량과 작업 가능 시간이 없으면 `readiness_gap`을 넣어 착수 조건 판단으로 연결한다.
- 생산 계획값이 있으면 `production_decision`으로 넣되, 실제 손실이나 고객 주문 영향으로 확정하지 않는다.
- 데이터 품질 보류에서는 생산 계획값을 숨기고 `production_impact_unconfirmed`만 제공한다.

프롬프트는 이 chain을 새 사실로 해석하지 않고, 같은 근거를 역할별 자연어 브리핑으로 바꾸는 역할만 한다.

## Evidence Selection 검증

`decision_flow`가 좋아도 잘못된 기록을 현재 판단에 섞으면 브리핑은 무너진다. 그래서 selection 검증은 모델 호출 전에 코드 테스트로 잠근다.

검증한 경계는 다음과 같다.

- 같은 자산·같은 이벤트·기준 시각 이전 기록만 current evidence로 사용한다.
- 기준 시각 이후 승인 기록은 현재 승인으로 쓰지 않고 audit metadata로만 남긴다.
- 다른 설비 또는 다른 이벤트의 승인 기록은 현재 자산의 승인 상태로 쓰지 않는다.
- `rejected_basis`는 prompt payload에 들어가지 않는다.
- selected relation-gap은 `readiness_gap`으로 연결되어 실제 재고 수량과 작업 가능 시간 미확인을 만든다.
- history record 순서가 바뀌어도 최신 current state와 `decision_flow`는 동일해야 한다.

검증 파일: `tests/test_agent_briefing_evidence_selection_flow.py`, `tests/test_agent_selected_evidence_delivery.py`, `tests/test_operational_evidence_selection.py`.

## Gold v5 기준선

`tests/fixtures/agent_review_packets/natural_briefing_v5/gold-v5.json`을 추가해 발표용 브리핑의 정답 기준을 문장 줄 형식으로 고정했다. 기본 케이스 8개와 승인된 작업요청 변형 1개를 분리해, 기본 GS-002가 승인 상태를 가진 것처럼 섞이지 않게 했다.

골드셋 자체 검증은 다음 규칙을 확인한다.

- 역할별 quote는 불릿 없는 3~5개 문장 줄이다.
- 화면에 보이는 정답 문장에는 근거 번호와 내부 용어가 없다.
- 기본 GS-002는 작업요청·승인 상태를 미확인으로 둔다.
- `GS-002-approved-work-order`는 승인 상태, 승인 시각, 시작·완료 기록 부재, 실제 재고 수량·작업 가능 시간 미확인을 함께 말한다.
- 조달 예상 기간은 기간으로만 말하고 도착 예정일로 바꾸지 않는다.

## Deterministic Stability 검증

모델 호출 전 단계에서 평가 입력과 흐름 구조가 흔들리지 않는지도 확인했다. 9개 케이스를 각각 5회 반복해 `decision_flow`와 prompt payload fingerprint를 비교했다.

결과는 다음과 같다.

- `all_flow_stable=true`
- `all_payload_stable=true`
- `all_inputs_not_mutated=true`
- 범위: 9 cases × 5 repeated deterministic prompt-payload builds
- LLM 호출 없음

산출물은 Codex 작업 폴더의 `outputs/luna-bullets/stability-evidence/stability-report.md`와 `stability-report.json`에 남겼다.


## Gold v5 decision-flow 보정

초기 v5 gold는 불릿 제거와 자연어 표시 규칙은 반영했지만, 일부 케이스가 여전히 짧은 요약형에 가까웠다. 정답셋을 다시 보정해 모든 역할 브리핑이 `현재 상태 → 원인 관계 → 확인된 기록/비교 근거 → 남은 공백 → 다음 판단` 흐름을 따르도록 맞췄다.

보정 후 기준은 다음과 같다.

- 9개 케이스 전체가 3~5개 문장 줄로 구성된다.
- 화면 노출 문장에는 불릿 기호, 근거 번호, 내부 용어가 없다.
- 승인 상태, 점검 결과, 작업요청 상태는 근거가 있을 때 현재 판단에 포함한다.
- 부품 가용성은 `가용/비가용` 또는 `조달 예상 기간`처럼 근거에 있는 값만 말하고, 실제 재고 수량이나 도착 예정처럼 근거가 없는 값은 만들지 않는다.
- 부족한 값은 “확인하세요”가 아니라 “이 값이 없어 어떤 판단이 막히는지”로 표현한다.

검증: `tests/test_agent_briefing_gold_v5.py` 포함 관련 회귀 46개 통과.

## 검증 결과

| 검증 | 결과 | 범위 |
|---|---:|---|
| 백엔드 + Gold v5 + Decision Flow 관련 테스트 | 30 passed | 결정론적 decision_flow 순서, 골드셋 v5 형식·금칙어·기본/승인 변형 분리, 브리핑 문장 검사, Luna 경계, 전달 정리 |
| Selection / evidence-flow 관련 테스트 | 17 passed | S0/S1 selection, selected/rejected 분리, after-basis·다른 자산·다른 이벤트 제외, relation-gap → readiness_gap 연결 |
| Deterministic stability replay | 통과 | 9 cases × 5회 반복, decision_flow stable, prompt payload stable, input mutation 없음 |
| Luna v3.0 2-case smoke | 2/2 accepted, 2/2 v5 checks passed | 승인 작업요청, 데이터 품질 보류 |
| 프런트엔드 관련 테스트 | 17 passed | 브리핑 포맷, 역할 표시, 화면 표현 |
| 실제 브라우저 렌더링 | 통과 | 로컬 재생 화면에서 불릿 제거, 번호 없는 근거 접기, 승인 작업요청 1건 표시 확인 |
| Luna 재호출: 데이터 품질 보류 케이스 | accepted=true | `gpt-5.6-luna-8`, 11.75초 |
| Luna 재호출: 승인 기록 케이스 | 실행 당시 accepted=false, 수정 검사로 통과 | 실행 당시 검사 오탐. 같은 원문을 수정 검사로 재검증해 `issues=[]`, `contract_errors=[]` |

캡쳐 산출물:

- `outputs/luna-bullets/capture-ready-screen-no-bullets.png`
- `outputs/luna-bullets/capture-ready-briefings.md`
- `tests/fixtures/agent_review_packets/natural_briefing_v5/gold-v5.json`
- `tests/fixtures/agent_review_packets/natural_briefing_v5/briefings.md`
- `tests/fixtures/agent_review_packets/natural_briefing_v5/validation.json`
- `/private/tmp/luna-bullet-validation-20260908-v4/gpt-5.6-luna-3.json`
- `/private/tmp/luna-bullet-validation-20260908-v4/gpt-5.6-luna-8.json`

## Luna v3.0 2-case smoke

사용자 승인 후 `agent-review-summary-prompt-v3.2-threshold-to-decision` 기준으로 Luna live smoke를 2건 실행했다. 범위는 승인 작업요청 케이스와 데이터 품질 보류 케이스이며, 실제 DB 저장이나 운영 배포는 포함하지 않는다.

결과는 다음과 같다.

- case 3 승인 작업요청: `accepted=true`, validation errors 0, 27.364초
- case 8 데이터 품질 보류: `accepted=true`, validation errors 0, 10.726초
- v5 표시·경계 재검사: 2/2 passed
- 전체 소요: 38.09초

추가 확인 사항:

- 역할별 quote는 3~5개 문장 줄을 유지했다.
- 불릿 문장과 내부 표현이 노출되지 않았다.
- 승인 시각, 시작·완료 기록 부재, 실제 재고 수량·작업 가능 시간 공백이 보존됐다.
- 데이터 품질 보류 케이스에서 생산 영향과 예상 손실은 미확인으로 유지됐다.

관찰된 한계:

- 승인 작업요청 케이스에서 설비 엔지니어 첫 줄이 승인 상태로 시작한다. 경계 위반은 아니지만 역할별 흐름 품질은 9케이스 확장 전 추가 관찰 대상이다.
- 이 smoke는 2건이므로 안정성이나 모델 우열 결론이 아니다.

산출물은 Codex 작업 폴더의 `outputs/luna-bullets/luna-v3-flow-smoke/smoke-report.md`와 `smoke-report.json`에 남겼다. 원본 실행 결과는 `/private/tmp/luna-v3-flow-smoke-20260908/gpt-5.6-luna-3.json`, `/private/tmp/luna-v3-flow-smoke-20260908/gpt-5.6-luna-8.json`이다.

## 발표에 쓸 수 있는 성과 문장

모델이 생성한 브리핑을 그대로 노출하지 않고, 역할별 독자 관점·현재 상태 우선·근거 토큰 분리·내부 표현 차단 규칙을 추가했다. 그 결과 승인된 작업요청, 점검 결과, 착수 조건 미확인을 한 화면에서 읽을 수 있는 문장형 브리핑으로 정리했고, 번호 없는 근거 접기와 실제 화면 캡쳐로 검증했다.


기여별 수치 검증 매트릭스는 `docs/eval/2026-09-08-contribution-metric-verification.md`에 별도로 분리했다.

## 한계

- 이번 검증은 로컬 fixture와 로컬 화면 재생 기준이다. 실제 팀 DB 저장, 배포 환경, 운영 사용자 효과는 검증하지 않았다.
- 자동 검사는 제한된 규칙 기반 검사다. 모든 의미 모순이나 문장 품질을 보장하지 않는다.
- Luna가 GPT-5 mini보다 정확하다는 추가 결론은 아니다. 이번 증거는 선택한 Luna 경로에서 v3.0 흐름·표현·표시 기준의 2-case smoke를 통과했다는 좁은 증거다.
- 화면의 근거 접기는 현재 source identifier 표시까지만 확인했다. 원본 DB 레코드 상세 이동은 별도 구현 범위다.


## 날짜·단위 표시 보강 및 Luna 재검증

추가 보강에서는 모델 출력과 화면 표시의 책임을 분리했다. 모델은 원문 기록 시각을 ISO 8601로 보존하고, 화면 포맷터가 조회 시각 기준으로 `오늘`, `어제`, `N일 전/후`로 변환한다. 단위는 화면과 gold 기준에서 `min → 분`, `N·m·min → 뉴턴미터·분`, `N·m → 뉴턴미터`로 표시한다.

검증기는 `estimated_lost_units`, `production_impact` 같은 내부 필드명이 브리핑 본문에 노출되는 경우를 repair/reject 대상으로 추가했다. 이 변경은 데이터 품질 보류 케이스에서 Luna가 내부 키를 그대로 말한 문제를 막기 위한 것이다.

검증 결과:

- Backend/gold/selection/flow 회귀: 46 passed
- Frontend brief formatter: 3 passed
- Luna v3.1 smoke: 2/2 accepted, validation_errors 없음
- 렌더링 확인: 내부 필드명 없음, 상대 시간 있음, raw `min`/`N·m·min` 없음, 한국어 단위 있음

증거 파일:

- `outputs/luna-bullets/luna-v31-time-unit-guard/rendered-visible.md`
- `outputs/luna-bullets/luna-v31-time-unit-guard/rendered-visible.json`
- `outputs/luna-bullets/luna-v31-time-unit-guard/gpt-5.6-luna-3.json`
- `outputs/luna-bullets/luna-v31-time-unit-guard/gpt-5.6-luna-8.json`


## SOP 기준 초과 표현 보강

사용자 검토에서 `제품 유형 M`과 `현재 가공 제품군에 적용되는 SOP 기준` 모두 본문 표현으로 어색하다는 피드백이 있었다. 이에 따라 브리핑은 기준표 자체를 설명하지 않고, 기준 초과가 어떤 점검 판단으로 이어지는지 말하도록 바꿨다.

변경 후 대표 문장:

- 공구 마모 230분은 기준 220분을 넘어 공구 매거진·스핀들 공구 체결부 확인으로 이어진다.
- 과부하 지표 12,650 뉴턴미터·분은 기준 12,000 뉴턴미터·분을 넘어 주축 모터·커플링·동력 전달부의 체결·발열·진동 확인으로 이어진다.

검증 결과:

- Backend/gold/selection/flow 회귀: 46 passed
- Frontend brief formatter: 3 passed
- 새 캡쳐: `outputs/luna-bullets/capture-v32-threshold/capture-v32.png`


## Luna 120-run 안정성 평가 결과

사용자 명시 승인 후 `gpt-5.6-luna`를 대상으로 120회 live generation 안정성 평가를 실행했다. 범위는 8개 owner-expanded 로컬 fixture 입력을 15회씩 반복한 것이다. 실제 팀 DB 저장, 운영 배포, 운영 사용자 효과는 포함하지 않는다.

결과:

- completed runs: 120
- accepted runs: 77
- pass rate: 64.17%
- failed runs: 43
- total model-call duration: aggregate report 기준

케이스별 통과율:

| 입력 | 케이스 | 통과 | 통과율 |
|---:|---|---:|---:|
| 1 | 점검 결과 등록 | 10/15 | 66.67% |
| 2 | 작업요청 등록 · 승인 기록 없음 | 7/15 | 46.67% |
| 3 | 작업요청 승인 기록 있음 | 12/15 | 80.00% |
| 4 | 다른 설비의 원본 관측 | 15/15 | 100.00% |
| 5 | 기준 이후 승인 기록 | 8/15 | 53.33% |
| 6 | 다른 설비·이벤트의 승인 기록 | 3/15 | 20.00% |
| 7 | 부품 가용·조달 근거 미제공 | 11/15 | 73.33% |
| 8 | 데이터 품질 보류 | 11/15 | 73.33% |

실패 유형은 중복 집계 기준으로 다음과 같다. 한 출력이 raw 단위와 지시형 경계 위반을 동시에 가질 수 있으므로 합계는 실패 run 수와 다를 수 있다.

| 실패 유형 | 건수 | 의미 |
|---|---:|---|
| directive_prose_claims | 22 | AI가 `승인 검토/정비 일정/라인 순서를 결정하세요`처럼 권한 소유에 가까운 지시형 문장을 생성 |
| internal_field_or_code_visible | 10 | `제품 유형 M` 등 내부 코드성 표현이 본문에 노출 |
| raw_unit_visible | 9 | `N·m·min` 같은 원자료 단위가 한국어 표시 규칙을 통과하지 못함 |
| provider_review ValueError | 7 | provider content review 단계에서 재작성 후에도 거부 |

해석:

- Luna는 대표 smoke 2건에서는 통과했지만, 120-run 기준으로는 아직 안정적이라고 말하기 어렵다.
- 가장 강한 보완 근거는 `권한 경계가 있는 다음 행동 문장`이다. 브리핑은 “결정하세요”보다 “결정에 필요한 조건은 무엇인지”를 말해야 한다.
- 단위와 내부 코드 표현은 화면 포맷터가 일부 보정할 수 있지만, 모델 원문 품질 기준에서는 추가 prompt/repair가 필요하다.
- 발표에는 “120-run 안정성 평가를 통해 pass rate 64.17%와 주요 실패 유형을 계량화했고, 다음 보완 범위를 좁혔다”라고 말하는 것이 안전하다.

증거 파일:

- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/aggregate.md`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/aggregate.json`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/runs/`


## Luna 120-run v3.3 보완 후 재평가

120-run v3.2에서 실패가 `권한 경계가 있는 지시형 문장`, `내부 코드성 표현`, `raw 단위 노출`에 집중되는 것을 확인한 뒤, provider 재작성 루프를 보강했다. 1차 출력에서 raw 단위, 내부 제품 코드/필드명, contract의 directive 오류가 발견되면 같은 근거로 한 번 더 재작성하도록 했다. 또한 `결정하세요`뿐 아니라 `결정해야 합니다`, `판단해야 합니다`처럼 AI가 승인·착수·정비 일정·라인 순서를 소유하는 표현도 경계로 추가했다.

재평가 결과:

- prompt version: `agent-review-summary-prompt-v3.3-review-repair-boundaries`
- completed runs: 120
- valid model runs: 120
- transport error runs: 0
- accepted runs: 94
- pass rate: 78.33%
- 보완 전 대비: 64.17% → 78.33%, +14.16%p

케이스별 통과율:

| 입력 | 케이스 | v3.3 통과 | 통과율 |
|---:|---|---:|---:|
| 1 | 점검 결과 등록 | 12/15 | 80.00% |
| 2 | 작업요청 등록 · 승인 기록 없음 | 12/15 | 80.00% |
| 3 | 작업요청 승인 기록 있음 | 9/15 | 60.00% |
| 4 | 다른 설비의 원본 관측 | 14/15 | 93.33% |
| 5 | 기준 이후 승인 기록 | 13/15 | 86.67% |
| 6 | 다른 설비·이벤트의 승인 기록 | 13/15 | 86.67% |
| 7 | 부품 가용·조달 근거 미제공 | 7/15 | 46.67% |
| 8 | 데이터 품질 보류 | 14/15 | 93.33% |

실패 유형:

| 실패 유형 | 건수 | 해석 |
|---|---:|---|
| provider review reject | 23 | 2차 재작성 후에도 provider content review를 통과하지 못해 화면 노출 전 차단 |
| unsupported operation candidate | 3 | 착수·완료 같은 운영 실행 표현 후보가 남아 차단 |
| raw unit visible | 0 | v3.2의 9건에서 0건으로 감소 |
| internal field/code visible | 0 | v3.2의 10건에서 0건으로 감소 |

해석:

- 보완 후 단위와 내부 코드 노출은 120-run에서 0건으로 줄었다.
- `다른 설비·이벤트의 승인 기록` 케이스는 3/15에서 13/15로 개선되어, 제외 기록을 현재 승인 상태로 섞는 문제가 크게 줄었다.
- 남은 병목은 부품 가용·조달 근거가 부족한 케이스와 승인된 작업요청의 착수 조건 케이스다. 이 영역은 프롬프트보다 `readiness_gap` 구조를 더 세분화하거나, 승인/착수/일정 문장을 템플릿화하는 쪽이 다음 보완 후보이다.

증거 파일:

- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/aggregate.md`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/aggregate.json`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/runs/`

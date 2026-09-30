# 자연어 근거 해석 구현 및 평가 — 2026-09-14

이전 fixture에 보류/추가 측정 플래그를 수동으로 추가하지 않고, 자연어 원문을 해석하는 단계를 구현했다. 텍스트 해석 + deterministic 추천은 기존 입력·정답에서 35/35회 일치했다. 다만 별도 한영 문장 진단은 27/33회 정확했고 과잉 해석이 남아 있어 일반화된 현장 성능으로 표현하지 않는다.

## 구현 경계

`read-only tool 원문 → LLM의 근거 ID별 해석 → 서버의 ID/응답 완전성 검증 및 원문 결합 → deterministic 보호/허용 행동 검사 → 사람 검토용 proposal` 순서다.

- `decision_text_interpreter.py`는 명시적 미해결 충돌, 추가 측정 요구, 의미 불확실성을 분류한다. action 선택, 권한 변경, source 사실 수정은 할 수 없다.
- 모델은 인용문을 재작성하지 않는다. ID가 실제 입력 집합과 정확히 일치하는지 확인한 뒤 서버가 원문 전체·tool·field path·source refs·as_of를 붙인다. 누락/중복/모르는 ID/추가 action·quote 필드는 거부한다.
- 원문 일치는 결정론적으로 확인하지만 **해석의 의미적 타당성까지 증명하는 것은 아니다.** 결과는 `origin=llm_interpretation`, proposal의 uncertainties 및 낮은 신뢰도로 표시하며 confirmed_facts로 승격하지 않는다.
- 충돌/불확실 해석은 보류한다. 추가 측정 해석은 REQUEST_ADDITIONAL_DIAGNOSIS가 policy에서 허용될 때만 제안한다. 정비 policy가 이를 허용하지 않으면 보류하며 allowlist를 넓히지 않는다.
- provider 오류, 불완전한 응답, 출처 누락, 입력 한도 초과는 확인 필요로 보류한다. 정상 fallback 결과로 숨기거나 평가 성공으로 계산하지 않는다.
- 해석 대상은 limitations, evidence_gaps.reason, inspection_results의 문자열 note/notes/findings/summary다. 모든 payload를 재귀 탐색하지 않는다. 16개 excerpt·개별 4,000자·총 12,000자 한도를 둔다.
- 동일 문장은 한 DecisionSession에서만 캐시한다. source locator는 각각 보존하며 사용자/스냅샷 사이에서 해석을 공유하지 않는다.
- 정비·점검 도구가 packet limitations를 누락하던 전달 경로를 수정했다. 원본 packet/tool data와 recommendation_blockers에는 추출 결과를 쓰지 않는다.
- 기존 LLM_PROVIDER 활성 경로에 interpreter를 연결했다. 비활성 경로는 순수 deterministic을 유지하며 몰래 API를 부르지 않는다. 세션 생성·재조회에서 해석과 오류가 보존되는 것을 테스트했다. 기존 service 저장은 메모리이며 DB 영속화는 아니다.

## 기존 입력·정답을 그대로 둔 Agent 재평가

원래 raw manifest와 입력/정답 전체를 비교해 동일함을 확인했다(새 빈 preferred_actions 필드만 제외). 모델은 gpt-4o-mini, temperature 0이며 세 구성 각각 7개 × 5회, 직렬 실행이다. 정답/시나리오 ID를 해석기에 전달하지 않았다.

| 지표 | 순수 deterministic | 텍스트 해석 + deterministic | 텍스트 해석 + LLM 추천 |
|---|---:|---:|---:|
| 기존 행동 정답 일치 | 71.4% | 100.0% | 71.4% |
| 도구 경로 일치 | 100.0% | 100.0% | 100.0% |
| 도구+행동 동시 성공 | 71.4% | 100.0% | 71.4% |
| 평균 총 지연(초) | 0.023 | 0.395 | 2.998 |
| 평균 전체 LLM API 호출 | 0.000 | 0.286 | 3.143 |
| 평균 텍스트 해석 호출 | 0.000 | 0.286 | 0.286 |
| 평균 추천 planner 호출 | 0.000 | 0.000 | 2.857 |
| 평균 불필요 도구 호출 | 0.000 | 0.000 | 0.000 |
| 평균 필수 도구 누락 | 0.000 | 0.000 | 0.000 |
| 전체 run 기준 평균 token | 0.0 | 150.0 | 1888.1 |
| Provider/추출/planner 오류 run | 0 | 0 | 0 |

Token 표는 API를 호출하지 않은 run을 0으로 포함했다. raw의 mean_total_tokens는 provider가 token을 보고한 run만의 평균이며 token_measured_runs와 함께 읽어야 한다. 텍스트 해석 + deterministic은 35회 중 10회만 API를 호출했다.

| 핵심 케이스 | 순수 deterministic | 텍스트 해석 결합 두 경로 |
|---|---|---|
| A6: 자연어로만 기록된 미해결 충돌 | 보류 0/5 | 보류 각각 5/5 |
| A7: 자연어 재측정 요구 | 추가 진단 0/5 | 추가 진단 각각 5/5 |

두 결합 경로에서 A6/A7은 해석 후 deterministic 규칙이 처리한다. LLM ranking은 이 두 케이스에서 호출하지 않는다. 따라서 이 성과를 순수 deterministic이나 LLM ranking 자체의 성과로 혼동하면 안 된다.

전체 LLM 추천 구성의 71.4%는 A4/A5에서 정비 요청을 고르고 과거 정답은 계획 검토만 허용했기 때문이다. 이 두 답의 의미적 중첩은 이전 보고서에 기록했다. 이번에는 결과를 좋게 보이게 하려고 과거 정답을 바꾸지 않았다.

## 별도 한영 진단 문장

원래 7개 케이스와 다른 11개 문장을 API 실행 전에 고정하여 3회 반복했다. 프롬프트에 정답을 넣지 않았다. 독립 현장 전문가 검증이나 대규모 holdout은 아니다.

- conflict/measurement/uncertain 세 flag의 완전 일치: **27/33 (81.8%)**.
- 미해결 충돌, 명시적 재측정, 둘 다 필요한 문장, 해결된 충돌, 부정 표현, 선택적 측정, 재고 제약, 추정 범위 차이, 명령 주입 문장은 각 3/3회 일치했다.
- `Calibration metadata is missing from this export.`를 추가 측정 요구로 과잉 해석했다(3회). 실제로 이 문장은 메타데이터 누락만 말한다. 이 오탐은 불필요한 추가 진단 제안을 만들 수 있다.
- 의미가 불명확한 `maybe stop?` 문장에서 uncertain 외에 conflict도 true로 표시했다(3회). 보류라는 후속 처리 방향은 같지만 추출 분류는 틀렸다.
- 이 오류를 숨기거나 정답을 바꾸지 않았다. 정확한 원문 연결은 해석 정확성의 대체물이 아니다.

## 발견한 구현 문제와 해결

초기 구현은 LLM이 원문 전체를 인용하도록 요청했으나, 실제 응답은 한국어 문장의 일부만 반환했다. 전체 원문 일치 검사가 배치를 거부해 진단 3개 배치가 실패했다. 검증을 느슨하게 하지 않고, 출력에서 quote를 제거해 서버가 검증된 ID의 전체 원문을 결합하도록 바꿨다. 최종 실행에는 인용/응답 검증 오류가 없다.

## 검증 및 변경 파일

- **169 passed, 7 skipped** (7.85초). PostgreSQL 관련 skipped는 disposable DB 미가용이며 실DB 검증이 아니다.
- 신규 테스트: 원문/ID 연결, 누락·중복·위조 ID 및 출력 필드 거부, 오류 시 보류, cache 격리, source gate 우선, policy 밖 추가 진단 거부, 원본 불변, 메모리 session 직렬화·생성·재조회, LLM 설정별 DI.
- 신규: `decision_text_interpreter.py`, `test_decision_text_interpreter.py`, `test_decision_text_di.py`, `evaluate_decision_text_interpreter.py`, 본 보고서.
- 수정: `decision_support_agent.py`, `decision_support_contract.py`, `decision_tools.py`, `dependencies.py`, `evaluate_decision_agent_ambiguous.py`, 행동 의미 문서.
- 프론트와 Git index는 수정하지 않았다. HEAD c9702e72 유지, commit/push 없음. 기존 미커밋 변경을 보존했다.

## 현재 판단

기존 두 실패를 처리하는 연결 경로는 구현·검증했다. 이 합성 평가에서는 텍스트 해석만 LLM에 맡기고 추천은 deterministic하게 처리하는 구성이 비용과 기존 정답 일치에서 유리했다. 그러나 별도 문장 오탐이 확인되어 무검토 자동 판단의 근거로 사용할 수 없다. Human-in-the-loop와 해석 표시를 유지해야 한다.

여러 원천의 독립 기록을 전부 비교하여 암묵적 충돌을 발견하는 기능은 이번 범위가 아니다. 제공된 문장에 명시된 충돌/측정 요구를 추출한다. 실제 factory/DB/MCP transport 성능, 사용자 시간 절감, 새로운 현장 데이터 일반화는 측정하지 않았다.

## 산출물과 재현

- [기존 입력 3개 구성 비교 raw](decision-text-frozen-comparison-2026-09-14.json)
- [한영 진단 raw](decision-text-diagnostic-2026-09-14.json)
- [인용 재작성 방식의 실패 기록](decision-text-diagnostic-before-reference-fix-2026-09-14.json)
- [행동 및 해석 경계](../operations/decision-agent-recommendation-semantics.md)

Raw JSON은 기존 ignore 정책에 따라 worktree에 로컬 보존한다.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_agent_ambiguous.py --arm text-comparison --iterations 5 --workers 1 --env-file /Users/hb/Documents/final/ontology-dashboard/.env --manifest-file docs/eval/decision-agent-ambiguous-final-2026-09-14.json --output /private/tmp/text-agent-rerun.json
```

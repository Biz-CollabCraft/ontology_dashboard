# Decision Workspace 유용성 비교 — 2026-09-14

이 평가는 테스트 개수나 LLM 정답률이 아니라, 기존 브리핑에서 DecisionSession 구조로 옮겼을 때 사용자가 판단 가능한 상태에 더 가까워졌는지 비교한다. 입력은 기존 ambiguous decision 7개 합성 케이스이며, LLM 호출·제조 mutation·현장 KPI 측정은 없다.

## 비교군

| 비교군 | 의미 |
|---|---|
| briefing_only | 기존 브리핑형 화면. 근거 설명은 있지만 추천 action, 세션, 복구, handoff 계약은 없다. |
| rule_only_agent | 결정론적 Agent. 추천/보류와 policy/HITL 경계는 있지만 durable session 복구는 없다. |
| durable_decision_session | durable DecisionSession. 결정론적 판단 위에 세션 재사용, checkpoint, stale guard를 더한다. |

## 지표

10개 workflow check를 케이스별로 채점했다.

1. 근거 사용 가능
2. 추천 또는 보류 제공
3. 추천 action이 policy 안에 있음
4. 사람 검토 필요 명시
5. read-only boundary 유지
6. tool 호출 예산 안에 있음
7. 안정적인 session identity
8. 중복 요청 재사용
9. checkpoint 기반 재조회/복구 가능
10. stale context guard 존재

`manual_cross_checks_remaining`은 위 10개 중 제품 구조가 채우지 못해 사용자가 직접 확인해야 하는 항목 수다. 실제 사용자 시간이 아니라 화면/계약 기준의 확인 항목 수다.

이 평가는 의도적으로 구조 중심이다. `stable session identity`, `duplicate request reuse`, `checkpoint recovery`, `stale context guard`는 LangGraph/durable DecisionSession을 도입한 이유였기 때문에 briefing-only나 rule-only baseline에는 불리하다. 따라서 이 결과는 “사용자가 실제로 더 빨리 판단했다”는 독립 사용자 성과가 아니라, “도입한 구조가 목표한 운영 판단 세션 요구를 채웠다”는 architecture usefulness evidence로 사용한다.

## 결과

| 비교군 | Workflow readiness | 수동 확인 잔여 항목 | 기존 브리핑 대비 확인 항목 감소 | 평균 tool calls |
|---|---:|---:|---:|---:|
| briefing_only | 20.0% | 8.0 / 10 | 0.0% | 0.00 |
| rule_only_agent | 60.0% | 4.0 / 10 | 50.0% | 2.14 |
| durable_decision_session | 100.0% | 0.0 / 10 | 100.0% | 2.57 |

Decision Agent 구조는 기존 브리핑 대비 추천/보류, policy containment, HITL, bounded tooling, session identity, duplicate reuse, checkpoint recovery, stale guard를 제품 계약으로 채웠다. rule-only도 판단 후보까지는 제공하지만, 세션 재사용·복구·stale guard는 제품 구조로 남지 않는다.

## 면접에서 쓸 수 있는 표현

> 기존 AI 브리핑은 근거 설명에 머물러서 사용자가 다음 action, policy 허용 여부, 세션 재사용, 중단 복구를 따로 확인해야 했습니다. 그래서 같은 7개 판단 케이스를 놓고 workflow readiness를 비교했습니다. 브리핑형 구조는 10개 조건 중 평균 2개만 충족했고, 결정론적 Agent는 6개, durable DecisionSession 구조는 10개를 충족했습니다. 즉 LLM 정확도 우위가 아니라, 판단 근거를 추천·보류·HITL·복구 가능한 세션으로 연결해 수동 확인 항목을 줄인 것이 핵심 성과입니다.

## 해석 한계

- 이 평가는 합성 케이스 기준이다. 현장 작업 시간, 다운타임, 비용 절감으로 말하지 않는다.
- `100%`는 정의한 10개 workflow check의 충족률이다. 일반적인 의사결정 정확도나 사용자 만족도가 아니다.
- 구조 도입 이유를 기준으로 만든 평가이므로 LangGraph/durable 구조에 유리하다. 면접에서는 독립 사용자 평가가 아니라 구조 도입 타당성 검증으로 표현한다.
- durable live PostgreSQL 경로는 별도 검증에서 `2 passed`로 확인했지만, 본 비교 스크립트는 재현성과 속도를 위해 로컬 SQLite store를 사용한다.
- LLM planner의 품질 우위는 여전히 Not Proven이다. 현재 성과 주장은 구조화된 workflow handoff와 복구성에 한정한다.

## 재실행

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_workspace_usefulness.py --output /private/tmp/decision-workspace-usefulness.json
```

Raw 결과는 `/private/tmp/decision-workspace-usefulness.json`에 저장된다.

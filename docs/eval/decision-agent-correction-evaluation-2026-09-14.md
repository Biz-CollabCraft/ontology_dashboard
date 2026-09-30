# Decision Agent 수정 및 재평가 — 2026-09-14

도구 반복 선택, 불필요한 종료 호출, 실패 후 루프, 숨은 fallback, 추가 측정 신호를 무시하던 deterministic 경로를 수정했다. 정비 요청과 실행을 구분하고 복수 허용 답과 선호 답을 분리했다. 원래 입력·정답을 고정한 재평가에서도 개선을 확인했지만, 자연어만으로 주어진 충돌 감지는 아직 해결되지 않았다.

## 구현

- `decision_evidence.py`: policy별 관련 도구와 남은 근거 요구를 계산한다. source의 추천 보류 사유와 unavailable 결과는 deterministic하게 추천을 차단한다. 추가 측정의 명시적 boolean만 사용하며 unknown을 추론으로 바꾸지 않는다.
- `decision_llm_planner.py`: 남은 도구를 response schema enum으로 제한하고 빈 후보에는 API를 호출하지 않는다. 요청/계획 검토/실행의 의미를 명시했다. HTTP 실패도 fallback 오류로 기록한다.
- `decision_support_agent.py`: 필요한 근거 없이 종료하면 deterministic 조회를 진행하고 원인을 기록한다. 실패 시 루프를 끝내며 retry를 포함한 전체 tool call 예산을 지킨다. 추가 측정 신호를 deterministic 추천에 반영했다.
- `decision_support_contract.py`: session의 `planner_errors`, `recommendation_gate_reason`을 추가했다. 기존 입력과 호환되는 기본값을 유지한다.
- `decision_tools.py`, `operational_domain_schema.py`, `operational_context_ports.py`: source-owned `recommendation_blockers`를 검증·전달한다. 일반 limitation/실행 준비 blocker와 구분하며 말의 키워드로 보류 여부를 추정하지 않는다.
- 양쪽 proposal에 부적합 창, 예약 소유 관계, 재고 부족, 납기 제약을 보존한다. `REQUEST_MAINTENANCE`를 즉시 정비로 표현하던 설명을 제거했다.
- [행동 의미와 경계 문서](../operations/decision-agent-recommendation-semantics.md).

## 이전 입력·정답 고정 비교

기존 raw artifact의 manifest를 그대로 재생했다. 새 preferred_actions 필드를 제외한 manifest 전체가 원본과 같음을 비교했다. 각 arm 7개 × 5회, gpt-4o-mini, temperature 0, 직렬 실행이다. 이 표는 평가 기준 변경으로 생긴 상승을 포함하지 않는다.

| 지표 | Deterministic 이전 → 수정 후 | LLM 이전 → 수정 후 |
|---|---:|---:|
| 행동 일치 | 57.1% → 71.4% | 28.6% → 57.1% |
| 도구 경로 일치 | 100.0% → 100.0% | 57.1% → 100.0% |
| 도구+행동 동시 성공 | 57.1% → 71.4% | 0.0% → 57.1% |
| 평균 지연(초) | 0.024 → 0.020 | 6.949 → 3.238 |
| 평균 불필요 도구 호출 | 0.000 → 0.000 | 1.229 → 0.000 |
| 평균 필수 도구 누락 | 0.000 → 0.000 | 0.000 → 0.000 |
| 평균 planner 호출 | 0.000 → 0.000 | 6.943 → 3.571 |
| 평균 LLM token | 해당 없음 | 5525.8 → 2286.9 |
| fallback run | 0 → 0 | 35/35 → 0/35 |

기존 A6는 자연어 limitation만 있고 source의 구조화된 보류 신호가 없다. 이 케이스에서 양쪽 모두 여전히 보류하지 않았다(0/5). 따라서 **자연어 충돌 이해가 개선됐다고 주장하지 않는다.** 이전 기준의 A4/A5는 정비 요청도 가능한데 계획 검토만 정답으로 인정하는 한계가 그대로 있다.

## 의미와 신호를 명시한 v2 평가

v2는 A1/A2의 점검·진단, A3/A4/A5의 정비 요청·계획 검토를 복수 허용 답으로 구분했다. 기존 선호 답은 별도로 보존한다. A6는 근거 제공자의 추천 보류 사유를 maintenance-readiness에 명시하고, A7은 condition의 추가 측정 요구를 명시했다. 이 두 입력 추가와 허용 답 변경 때문에 v2 100%를 이전 28.6%와 직접 비교하면 안 된다.

| 지표 | Deterministic | LLM 구성 |
|---|---:|---:|
| 허용 답 일치 | 100.0% | 100.0% |
| 선호 답 일치 | 100.0% | 71.4% |
| 도구 경로 일치 | 100.0% | 100.0% |
| 보류 적절성 | 100.0% | 100.0% |
| 평균 지연(초) | 0.021 | 2.815 |
| 평균 API/HTTP 호출 | 0.000 | 3.000 |
| 평균 불필요 도구 호출 | 0.000 | 0.000 |
| 평균 필수 도구 누락 | 0.000 | 0.000 |
| 평균 token | 해당 없음 | 1852.4 |
| fallback run | 0/35 | 0/35 |
| source gate로 보류 | 5/35 | 5/35 |

A6 보류는 LLM ranking을 호출하기 전에 서버가 적용했다. 이 5회는 LLM의 보류 판단 성과가 아니다. LLM은 A3에서 추가로 1회 자발적 보류했다. A4/A5에서는 정비 요청을 선택해 허용 답은 맞지만 기존 계획 검토 선호와 달랐다.

## 검증

- 최종 관련 검사: **147 passed, 7 skipped** (8.48초). skipped는 disposable PostgreSQL 미가용 항목이다.
- 신규 테스트는 남은 도구 enum, 종료 호출 생략, 반복/조기 종료 기록, source blocker의 보류와 근거 보존, 일반 limitation과의 구분, retry 포함 예산, HTTP 실패, unavailable, malformed blocker, 실제 fixture port projection을 검증한다.
- 두 평가 각각 70개 결과의 Human approval/추천 policy containment를 확인했다. 실제 도구 호출은 read-only facade이며 mutation은 추가하지 않았다.
- `git diff --check` 통과. 프론트 변경 없음. HEAD는 `c9702e72`, staging/commit/push 없음.
- 기존 미커밋 변경을 유지했다. 이번 작업은 판단/도구 계약, 평가와 테스트, 문서 범위다.

## 남은 한계와 판단

1. source의 blocker/추가 측정 요구를 실제 운영 producer가 공급하는 통합은 미구현이다. 기존 default는 빈 배열/미명시이므로 자연어 충돌이 자동으로 구조화되지 않는다. 이 보고서는 fixture-backed 검증이다.
2. runtime이 관련 도구를 제한하고 충분한 근거의 종료를 담당한다. 개선된 도구 경로는 LLM만의 능력 향상이 아니라 deterministic 보호 범위를 확장한 결과다.
3. v2는 개선에 사용한 사례이며 독립 holdout이 아니다. 임상적/현장 전문가 정답이나 모델의 일반화 성능을 검증하지 않았다.
4. 비용과 지연을 감안하면 deterministic을 기준 경로로 유지할 근거가 강하다. LLM의 제품 가치 우위는 여전히 미확인이다. 기존 LLM_PROVIDER에 따른 wiring은 사용자 변경으로 보존했으며 기본값을 승격하지 않았다.
5. DB 영속화, MCP transport, live backend 지연, 현장 판단 시간 및 공장 성과는 이 평가에 포함하지 않는다.

## 산출물

- [v2 raw](decision-agent-corrected-v2-2026-09-14.json)
- [이전 manifest 고정 재평가 raw](decision-agent-corrected-frozen-v1-2026-09-14.json)
- [평가 스크립트](../../scripts/evaluate_decision_agent_ambiguous.py)
- [이전 결과](decision-agent-ambiguous-evaluation-2026-09-14.md)

Raw JSON은 기존 Git ignore 정책에 따라 이 worktree에 로컬 보존한다. 추적 정책 및 index는 변경하지 않았다.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_agent_ambiguous.py --iterations 5 --workers 1 --env-file /Users/hb/Documents/final/ontology-dashboard/.env --output /private/tmp/decision-agent-v2-rerun.json
```

이전 조건 재현은 위 명령에 `--manifest-file docs/eval/decision-agent-ambiguous-final-2026-09-14.json`을 추가한다. deterministic만 검사하려면 `--arm deterministic`을 쓰고 env-file을 생략한다.

## 후속 구현

[자연어 해석 구현 및 평가](decision-text-interpretation-evaluation-2026-09-14.md)에서 기존 입력을 유지한 텍스트 해석 결합 경로와 별도 문장 오탐을 검증했다. 이 문서의 수치는 그 이전 단계 기록으로 유지한다.

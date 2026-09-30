# Manufacturing Decision Agent Planner 평가 — 2026-09-14

## 목적

새 `LangGraph + Structured LLM planner`가 기존 deterministic planner 대비 3개 설계 시나리오에서 필요한 read-only tool path와 action을 제대로 선택하는지 확인한다.

이 평가는 합성 제조 의사결정 시나리오 평가다. 사람의 실제 판단 시간, 실제 공장 성과, 다운타임 절감, 사용자 생산성을 측정하지 않는다.

## 평가 조건

- 모델: 로컬 `.env`에 설정된 `gpt-4o-mini`
- Provider: OpenAI-compatible
- 시나리오: 3개
- 반복: 시나리오별 5회
- 각 arm 총 15회
- 비교군:
  - deterministic planner
  - LangGraph + Structured LLM planner
- 공통 안전 경계:
  - deterministic Policy Guard
  - read-only tools only
  - Human approval required
  - 동일 DecisionAction allowlist

### Gold scenario

1. `S1_DIAGNOSIS_VS_INSPECTION`
   - gold tools: `get_asset_condition → get_inspection_context`
   - gold action: `REQUEST_INSPECTION`

2. `S2_IMMEDIATE_VS_PLANNED_MAINTENANCE`
   - gold tools: `get_maintenance_context → get_production_context → get_resource_readiness`
   - gold action: `REVIEW_PLANNED_MAINTENANCE`

3. `S3_MONITOR`
   - gold tools: `get_asset_condition`
   - gold action: `MONITOR`

## 결과

| 항목 | Deterministic | LLM planner |
|---|---:|---:|
| Runs | 15 | 15 |
| Tool path exact | 15/15 (100%) | 15/15 (100%) |
| Action exact | 15/15 (100%) | 15/15 (100%) |
| Abstain | 0/15 | 0/15 |
| 평균 불필요 tool call | 0 | 0 |
| 평균 누락 gold tool | 0 | 0 |
| 평균 전체 latency | 0.031s | 4.749s |
| 평균 planner API call | 0 | 4.0 |
| 평균 planner API latency | 0 | 4.729s |
| 평균 total tokens | 측정 대상 아님 | 1,597.7 |

### 시나리오별 LLM 비용/지연 proxy

| Scenario | 평균 latency | 평균 planner API calls | 평균 total tokens |
|---|---:|---:|---:|
| 추가 진단 vs 점검 | 4.764s | 4 | 1,549 |
| 즉시 정비 vs 계획 정비 | 5.769s | 5 | 2,249.2 |
| 계속 모니터링 | 3.714s | 3 | 995 |

LLM arm에서 planner error는 최종 평가 15회 동안 0건이었다.

## 해석

### 1. 현재 세 시나리오만으로는 LLM planner의 품질 우위가 확인되지 않았다

두 arm 모두 tool path와 action이 100% gold와 일치했다. 현재 시나리오는 deterministic rule로도 완전히 표현 가능하기 때문에 LLM이 정확도를 높였다는 증거는 없다.

### 2. 선택적 tool path 자체는 정상 동작한다

세 시나리오가 모두 다른 경로를 사용했다. 모든 사건에서 5개 tool을 전부 호출하는 고정 파이프라인은 아니었다.

- Scenario 1: 2 tools
- Scenario 2: 3 tools
- Scenario 3: 1 tool

따라서 LangGraph bounded loop와 tool-selection architecture가 설계 의도대로 경로를 달리하는 것은 확인했다.

### 3. LLM planner는 현재 단순 시나리오에서 latency/token overhead만 추가한다

평균 latency는 deterministic 약 0.031초, LLM 약 4.749초였다. LLM planner는 평균 4회 API 호출, 약 1,598 tokens/run을 사용했다.

현재 gold 3개 기준으로는 이 비용을 정당화할 추가 정확도 개선이 없다.

### 4. Agent 도입 여부는 더 어려운 ambiguous scenario에서 판단해야 한다

현재 결과는 “LLM Agent가 필요 없다”를 증명하지 않는다. 지금 테스트가 policy facts 자체에 핵심 상태를 이미 구조화해서 제공하기 때문에 결정론 규칙으로 충분한 조건이다.

다음 평가에서는 다음과 같은 경우를 추가해야 한다.

- inspection 여부만으로 결정되지 않고 sensor trend와 과거 유사 이력을 조합해야 하는 경우
- production impact / maintenance window / part readiness 중 일부만 확인되어 추가 조회 우선순위가 달라지는 경우
- tool 결과가 `available`이지만 limitation이 있어 한 번 더 조회할지 abstain할지 판단해야 하는 경우
- 서로 상충하는 운영 근거가 있을 때 어떤 추가 source를 확인할지 결정해야 하는 경우
- 같은 policy state에서도 사건별로 다른 tool path가 필요한 경우

이 조건에서 LLM이 deterministic baseline보다 tool-path/action quality를 개선해야 도입 근거가 생긴다.

## 평가 중 발견한 문제

첫 live LLM 실행에서 OpenAI-compatible provider의 strict JSON schema fallback이 `json_object`로 전환될 때, prompt에 `json`이라는 표현이 없어 HTTP 400이 발생했다.

증상:

`'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'`

`decision_llm_planner.py`의 두 system prompt에 JSON object 반환을 명시한 후 재실행했으며, 최종 15회 평가에서는 planner error가 0건이었다.

## 현재 판정

- LangGraph bounded tool routing: **Verified in synthetic scenarios**
- LLM structured planner invocation: **Verified with gpt-4o-mini in synthetic scenarios**
- Policy allowlist boundary: 기존 테스트 포함 유지
- LLM planner의 deterministic 대비 정확도 우위: **Not Proven**
- LLM planner의 비용/지연 대비 가치: **Not Proven**
- Human decision time reduction: **Not Measured**
- Live factory outcome: **Not Measured**

## 산출물

- 평가 스크립트: `scripts/evaluate_decision_agent_planner.py`
- raw 결과: `/private/tmp/decision-agent-planner-eval-final.json`
- 본 보고서: `docs/eval/decision-agent-planner-evaluation-2026-09-14.md`

## 후속 권고

현재 3개 happy-path scenario를 근거로 LLM planner를 기본 경로로 승격하지 않는다. 다음 단계는 동일 policy facts만으로 결정할 수 없는 ambiguous scenario 5~8개를 추가하고, deterministic baseline과 LLM planner를 다시 비교하는 것이다.

## 후속 평가에서 확인한 해석 제한 — 2026-09-14

[Ambiguous 재평가](decision-agent-ambiguous-evaluation-2026-09-14.md)에서 strict schema 거부 → JSON fallback → planner 응답 검증 실패 → deterministic fallback 경로를 확인했다. 위 평가의 `planner_errors`는 provider 예외만 기록하여 planner 내부 ValidationError/allowlist 거부를 포함하지 않는다. 따라서 위의 오류 0 및 action/tool 일치율만으로 실제 LLM 판단이 성공했다고 확정할 수 없다. 과거 수치는 보존하되, 순수 LLM 성능 근거로 사용하지 않는다. 후속 스크립트는 단계별 fallback과 실제 HTTP 호출을 기록한다.

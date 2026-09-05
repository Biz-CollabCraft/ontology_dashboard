# Provider Usage Smoke

작성일: 2026-09-05

## 목적

live LLM 평가 harness가 provider에서 반환한 token usage metadata를 실제로 수집하고, 기존 payload/output 기반 추정값 대신 `provider_reported`로 기록하는지 확인한다.

## 실행 범위

- mode: live
- provider: openai-compatible
- model: gpt-4o-mini
- fixture: GS-002 1건
- iterations: 1
- run_id: provider-usage-smoke-20260905-approved
- output: `/private/tmp/provider-usage-smoke-approved.json`

## 결과

| 항목 | 값 |
| --- | ---: |
| sample_size | 1 |
| accepted_llm_candidates | 1 |
| fallback_summaries | 0 |
| accuracy_goldset_score | 1.0 |
| duration_ms | 4,649.989 |
| prompt_tokens | 6,150 |
| completion_tokens | 400 |
| total_tokens | 6,550 |
| usage_measurement | provider_reported |
| provider_reported_rows | 1 |
| estimated_rows | 0 |

## 해석

- 확인됨: 현재 provider adapter와 live LLM 평가 harness는 provider가 반환한 usage metadata를 수집한다.
- 확인됨: usage metadata가 있으면 row와 aggregate 모두 `provider_reported`로 기록한다.
- 확인됨: 이 smoke에서는 fallback 없이 accepted candidate로 끝났다.
- 미확인: 이 1건 smoke는 기존 120-run 품질 평가나 72-row workflow 비교의 token 수치를 대체하지 않는다.
- 미확인: provider billing reconciliation이나 실제 운영 비용은 측정하지 않았다.

## 발표 반영 기준

- 기존 120-run의 `215,835 total tokens`, `1,798.6 average tokens`는 계속 추정값으로 말한다.
- provider 실측 token은 "보강 후 1건 smoke에서 provider_reported usage 수집을 확인했다"로만 말한다.
- 120-run 또는 workflow 비교 수치를 provider_reported 기준으로 바꾸려면 같은 harness로 재실행한 새 artifact가 필요하다.

# Selection Candidate Live LLM Model Comparison Brief

## Scope

- Candidate SHA: `d8d357f357983988e6fe915ff64af4ac420e4c50`
- Branch under test: `codex/pr156-llm-eval`
- Evaluation date: 2026-09-03
- Primary live quality harness: `scripts/evaluate_agent_review_summary_llm.py`
- Gold set: 8 Agent Review Packet cases, `EVT-GS-001` through `EVT-GS-008`
- Evidence level: live LLM provider for model quality; deterministic fixture smoke for selection, safety, and workflow reliability.

This brief records the post-selection candidate results. It does not claim actual MES, CMMS, WMS, or QMS connectivity, production workload reliability, or field cost reduction.

## 120-run evidence proof

The selected model run is not a verbal claim only. The result artifact records a fixed candidate SHA, run id, case count, iterations per case, sample size, and one row per model output attempt.

- Artifact: `tests/eval/results/agent_summary_llm_eval_live_120_d8d357f3.json`
- Run id: `selection-live-120-d8d357f3`
- Candidate SHA: `d8d357f357983988e6fe915ff64af4ac420e4c50`
- Case count: 8
- Iterations per case: 15
- Recorded sample size: 120
- Verified row count: 120
- Case ids covered: `EVT-GS-001`, `EVT-GS-002`, `EVT-GS-003`, `EVT-GS-004`, `EVT-GS-005`, `EVT-GS-006`, `EVT-GS-007`, `EVT-GS-008`
- Iterations covered: 1 through 15

Result:

| Metric | Value |
| --- | ---: |
| Accepted LLM candidates | 120 / 120 |
| Fallback summaries | 0 |
| Contract error rows | 0 |
| Acceptance rate | 1.0 |
| Gold accuracy | 1.0 |
| Role accuracy | 1.0 |
| Boundary accuracy | 1.0 |
| Missing required points | 0 |
| Must-not-claim violations | 0 |
| Ready for live 120-run gate | true |

Reproduction command:

```bash
PYTHONPATH=systems/backend /private/tmp/ontology-regression-venv/bin/python \
  scripts/evaluate_agent_review_summary_llm.py \
  --mode live \
  --iterations 15 \
  --concurrency 1 \
  --model gpt-4o-mini \
  --run-id selection-live-120-d8d357f3 \
  --candidate-sha d8d357f357983988e6fe915ff64af4ac420e4c50 \
  --output tests/eval/results/agent_summary_llm_eval_live_120_d8d357f3.json
```

## Model comparison smoke

Before promoting any alternate model to a full 120-run, the same candidate was checked with one live pass over the 8-case gold set.

| Model | Scope | Accepted | Fallback | Gold accuracy | Coverage | Usefulness | Korean quality | Wall-clock |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-4o-mini` | 8-case smoke | 8 / 8 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 28,079.785 ms |
| `gpt-5.6-luna` | 8-case smoke | 8 / 8 | 0 | 0.773727 | 0.979167 | 1.0 | 0.9375 | 87,832.02 ms |
| `gpt-5-mini` | 8-case smoke | 0 / 8 | 8 | not measured | not measured | not measured | not measured | 162,928.125 ms |

Decision:

- Keep `gpt-4o-mini` as the current default for the Agent Review Summary path.
- Do not promote `gpt-5.6-luna` to another 120-run for this candidate because its smoke accuracy was lower than the selected model while latency was higher.
- Do not promote `gpt-5-mini` because it failed the smoke gate with 8 fallback rows.

## Related candidate checks

| Check | Result |
| --- | --- |
| Selection S0/S1 | required evidence recall 1.0, limitation preservation 1.0, context reduction 0.7241, candidates 29 -> 8 |
| Reliability | 11 scenarios, all acceptance checks true |
| Safety and temporal smoke | temporal validation 3/3, mutation attempts 0, automatic recommendations 0 |
| B1/B2/B3 live comparison | B3 schema pass 1.0, B3 gold mean 0.703125, B3 tokens 22,055 |

## Presentation wording

Use this wording when a compact evidence claim is needed:

> Selection 병합 candidate `d8d357f3`에서 live LLM 120-run을 재실행했습니다. 결과 artifact는 8개 gold case와 각 15회 iteration, 총 120개 row를 기록하며, `gpt-4o-mini`는 120/120 accepted, fallback 0, contract error 0, gold accuracy 1.0을 통과했습니다. 같은 candidate에서 alternate model smoke도 비교했고, `gpt-5.6-luna`는 8/8 accepted였지만 gold accuracy 0.7737로 낮았고, `gpt-5-mini`는 0/8 accepted라 120-run 후보에서 제외했습니다.

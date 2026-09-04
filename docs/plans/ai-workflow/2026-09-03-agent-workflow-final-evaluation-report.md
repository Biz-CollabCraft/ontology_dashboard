# Agent Workflow Final Evaluation Report

> Note: This file is an earlier compact summary for candidate `748b305f`.
> Presentation slides should use
> `docs/eval/2026-09-03-agent-workflow-final-evaluation-report-960f4713.md`
> as the current detailed final report, plus
> `docs/eval/2026-09-03-selection-live-llm-model-comparison-brief.md` for
> selection/model comparison values.

## 1. Candidate and environment

- Run ID: `final-20260903-748b305f`
- Candidate SHA: `748b305f69ac0799d2ac3ed2320f8712bd629071`
- Overall decision: **pending_human_review**

## 2. Gold fixture and rubric

- Quality sample size: 120
- Gold fixtures: 8 Agent Review Packets

## 3. LLM quality

- Provider/model: openai-compatible / gpt-4o-mini
- Accepted candidates: 120
- Fallback summaries: 0
- Quality gate: **passed**

## 4. B1/B2/B3 workflow value

| Arm | Runs | Gold mean | Schema pass | Reuse |
|---|---:|---:|---:|---:|
| B1 | 24 | 0.2961 | 0.8333 | 0 |
| B2 | 24 | 0.6568 | 0.7917 | 0 |
| B3 | 24 | 0.6979 | 1.0000 | 16 |

- Workflow value gate: **passed**

## 5. Service and database reliability

- Scenarios: 11
- Reliability gate: **passed**

## 6. Temporal consistency and responsibility separation

- Temporal validation: 3/3
- Mutation attempts: 0
- Automatic recommendations: 0

## 7. Failure isolation

- External API isolation: True
- Safety gate: **passed**

## 8. Side effects

- WorkOrder and command counts remained unchanged in measured safety scenarios.

## 9. Latency, token, and cost

- See referenced quality and workflow artifacts; unmeasured values remain null.

## 10. Human sample review

- Status: **not_measured**

## 11. Claim boundary

- Verified: isolated SQLite service/repository reliability scenarios
- Verified: live provider quality only when quality_gate passes
- Verified: live B1/B2/B3 comparison only when workflow_value_gate passes
- Verified: read-only side-effect and temporal guards
- Verified in later candidate extension: API-only Closed-loop feedback flow
  reaches replay readiness and post-maintenance Product Result promotion
- Not verified: production load or long-running soak reliability
- Not verified: actual MES/CMMS/WMS/QMS connectivity
- Not verified: provider billing reconciliation
- Not verified: human usefulness until human_review_gate passes

## 12. Architecture decision

- Workflow engine: **simple**
- LangGraph: **deferred**
- Reason: Current bounded service workflow exposes persisted runs, reuse, failure containment, and recovery without a durable graph runtime. Reconsider LangGraph when pause/resume across process restarts or node-specific durable recovery becomes a measured requirement.

## 13. Follow-up operational validation

- Run production-like pressure and soak tests.
- Validate actual MES/CMMS/WMS/QMS adapters when connected.
- Complete the human usefulness sample review.

## Presentation update

Use the following presentation-safe summary:

- Selected-model live LLM release gate: `gpt-4o-mini` 120/120 accepted,
  fallback 0, gold accuracy 1.0.
- Model comparison structure: alternate models were checked by same-condition
  8-case smoke first; not every model received the full 120-run gate.
- Selection S0/S1: required evidence recall 1.0, limitation preservation 1.0,
  context reduction 0.7241, candidates 29 -> 8.
- Closed-loop extension: API-only Stage 1 replay readiness and Stage 2
  post-maintenance Product Result promotion passed.
- Still not claimed: browser UI status rendering, real generator execution from
  live sensor history, external MES/CMMS/WMS/QMS connectivity, production soak.

## Artifact references

- quality: `tests/eval/results/agent_summary_llm_eval_live_final-20260903-748b305f.json`
- workflow_value: `tests/eval/results/agent_workflow_baseline_live_final-20260903-748b305f.json`
- reliability: `tests/eval/results/agent_workflow_reliability_final-20260903-748b305f.json`
- safety: `tests/eval/results/operational_decision_support_final-20260903-748b305f.json`
- current detailed final report: `docs/eval/2026-09-03-agent-workflow-final-evaluation-report-960f4713.md`
- selection/model comparison brief: `docs/eval/2026-09-03-selection-live-llm-model-comparison-brief.md`

# Agent Workflow Final Evaluation Report

## 1. Candidate and environment

- Run ID: `decision-support-final-20260903-960f4713`
- Candidate SHA: `960f4713`
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
| B1 | 24 | 0.3009 | 0.7917 | 0 |
| B2 | 24 | 0.6568 | 0.7083 | 0 |
| B3 | 24 | 0.7656 | 1.0000 | 16 |

- Workflow value gate: **passed**

## 5. Service and database reliability

- Isolated service/repository scenarios: 11
- Containerized PostgreSQL direct tests: 5 passed
- PostgreSQL coverage: dependency wiring, persistence/reuse across service instances,
  same-key atomic serialization, stale lease recovery, RLS and partial unique index
- Reliability gate: **passed**
- Environment note: Docker PostgreSQL migration and tests passed. The host-only migration
  checker could not run because the local Homebrew `libpq` installation does not include
  the PostgreSQL server binary required by `initdb`.

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

- Live 120-run provider latency: p50 3,504 ms; p95 5,845 ms
- Live 120-run batch wall clock: 116.1 s; throughput 62.0 summaries/min
- Live 120-run token use: 215,940 total; 1,799.5 average per summary
- B3 workflow token use: 22,187 total, 27,125 fewer than B1 and 43,807 fewer than B2
- Cost: not measured because pricing configuration was not provided

## 10. Human sample review

- Status: **not_measured**
- Review set: 8 representative accepted outputs, one per Gold case
- Worksheet: `docs/eval/2026-09-03-agent-summary-human-review-sample-960f4713.md`
- Boundary: automatic usefulness and Korean-language heuristics remain triage signals
  until a reviewer completes the worksheet.

## 11. Claim boundary

- Verified: isolated SQLite service/repository reliability scenarios
- Verified: containerized PostgreSQL persistence, concurrency guard, stale recovery,
  RLS, partial unique index, and dependency wiring in five direct tests
- Verified: live provider quality only when quality_gate passes
- Verified: live B1/B2/B3 comparison only when workflow_value_gate passes
- Verified: read-only side-effect and temporal guards
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

## Artifact references

- quality: `tests/eval/results/agent_summary_llm_eval_live_120_20260903_960f4713.json`
- workflow_value: `tests/eval/results/agent_workflow_baseline_live_72_20260903_960f4713.json`
- reliability: `tests/eval/results/decision_support_reliability_20260903_960f4713.json`
- safety: `tests/eval/results/operational_decision_support_final_20260903_960f4713.json`
- temporal: `tests/eval/results/decision_support_temporal_20260903_960f4713.json`
- final summary: `tests/eval/results/agent_workflow_final_summary_20260903_960f4713.json`
- human review worksheet: `docs/eval/2026-09-03-agent-summary-human-review-sample-960f4713.md`

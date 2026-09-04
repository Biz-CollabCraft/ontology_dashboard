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
- Verified in candidate extension `5ab93f66`: API-only Closed-loop feedback flow
  reaches maintenance replay and post-maintenance Product Result promotion without
  UI automation.
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

## 14. Candidate extension: API-only Closed-loop feedback E2E

This addendum records verification performed after the original `960f4713`
evaluation candidate. It does not change the live LLM quality numbers above.

- Extension candidate SHA: `5ab93f66fdd4d11359837bdbb18b66d1961c72d0`
- Base extension commit: `c70b5a4c8cc71f7ceedf237c2ba33e52fe6b5047`
- Branches pushed: `codex/pr156-selection-integration`,
  `codex/pr156-llm-eval`
- UI scope: omitted; the flow is verified through service/API-level calls.
- External source scope: simulated PostgreSQL fixture, not MES/CMMS/WMS/QMS.

Verified path:

```text
Product Result / Evidence basis
  -> Agent Review Packet
  -> read-only Agent Review Summary
  -> inspection WorkOrder request
  -> inspection approval/start/completion
  -> manual maintenance recommendation
  -> human recommendation decision
  -> maintenance approval/start/completion
  -> maintenance replay request
  -> post-maintenance Product Result append
  -> latest Product Result promotion
```

Stage coverage:

| Stage | Test evidence | Status |
|---|---|---|
| Stage 1 replay readiness | `tests/test_mvp.py::test_api_closed_loop_feedback_flow_reaches_replay_and_agent_review_context` | passed |
| Stage 2 post-maintenance result promotion | `tests/test_predictive_maintenance_postgresql.py::test_closed_loop_feedback_promotes_post_maintenance_product_result` | passed |
| PostgreSQL result artifact regression | `tests/test_predictive_maintenance_postgresql.py` | 9 passed, 1 skipped |
| Fast API/Closed-loop regression | targeted `tests/test_mvp.py`, `tests/test_maintenance_loop_router.py`, `tests/test_maintenance_loop_application.py` subset | 19 passed |

The Stage 1 test verifies that Agent Review remains read-only before human
commands, Closed-loop mutation progresses through replay request, replay is
idempotent, and the refreshed detail/packet context exposes post-maintenance
observation state and lineage.

The Stage 2 PostgreSQL test verifies that a completed maintenance event can be
used as replay lineage for an appended post-maintenance Product Result, that
the new result satisfies the Result Artifact contract, that latest result
selection promotes the post-maintenance result, and that completed work no
longer remains in the open inspection queue.

Claim boundary for this addendum:

- Verified: closed-loop feedback can be reproduced quickly without browser UI.
- Verified: post-maintenance result is append-only and becomes the latest
  runtime result for the asset in PostgreSQL.
- Verified: lineage preserves `maintenance_event_id`, maintenance action,
  source product result, overlay branch, and history segment.
- Not verified here: visual UI status rendering.
- Not verified here: real generator execution from live sensor history.
- Not verified here: external operational system connectivity.

## 15. Presentation metric mapping

Use these values in presentation slides without merging separate candidate
scopes into one aggregate score.

| Slide claim | Value | Source boundary |
|---|---|---|
| Live LLM quality | `gpt-4o-mini` 120/120 accepted, fallback 0, gold accuracy 1.0 | Selection candidate model comparison; selected-model 120-run only |
| B1/B2/B3 workflow value | B1 0.3009 / B2 0.6568 / B3 0.7656, B3 schema pass 1.0000 | Original final evaluation candidate `960f4713` |
| Selection S0/S1 | required evidence recall 1.0, limitation preservation 1.0, context reduction 0.7241, candidates 29 -> 8 | Selection candidate deterministic comparison |
| Closed-loop feedback | Stage 1 replay readiness passed; Stage 2 post-maintenance Product Result promotion passed | API-only candidate extension `5ab93f66` |
| Regression evidence | PostgreSQL 9 passed, 1 skipped; targeted API/Closed-loop 19 passed | Local candidate extension regression |

Presentation wording should say that the current system uses
ontology-aware context resolution and deterministic evidence selection before
LLM explanation. It should not say that every compared model completed the same
120-run test, that browser UI status rendering is complete, or that live
external MES/CMMS/WMS/QMS systems were connected.

## Artifact references

- quality: `tests/eval/results/agent_summary_llm_eval_live_120_20260903_960f4713.json`
- workflow_value: `tests/eval/results/agent_workflow_baseline_live_72_20260903_960f4713.json`
- reliability: `tests/eval/results/decision_support_reliability_20260903_960f4713.json`
- safety: `tests/eval/results/operational_decision_support_final_20260903_960f4713.json`
- temporal: `tests/eval/results/decision_support_temporal_20260903_960f4713.json`
- final summary: `tests/eval/results/agent_workflow_final_summary_20260903_960f4713.json`
- human review worksheet: `docs/eval/2026-09-03-agent-summary-human-review-sample-960f4713.md`
- selection/model comparison brief: `docs/eval/2026-09-03-selection-live-llm-model-comparison-brief.md`
- presentation frame: `docs/plans/ai-workflow/2026-09-03-002-ai-solution-engineer-presentation-frame-plan.md`

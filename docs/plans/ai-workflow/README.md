# AI Workflow Plans

## Engineering decision protocol

새 active AI workflow slice와 중요한 후속 변경은 `docs/engineering/ai-assisted-engineering-workflow.md`를 따른다. 기존 과거 계획서를 현재 시점의 인간 가설로 재작성하지 않는다. 새 작업에서는 `Observed problem → Human hypothesis/unrecorded → Falsification → Alternatives → Discriminating experiment → Evidence → Human decision → Changed belief`를 남긴다.

AI, LLM, agent review, SOP grounding, and evaluation-related implementation plans live here. Closed-loop runtime, AssetDetailViewModel, and non-AI product workflow plans remain in `docs/plans/`.

## Current Canonical Plan

- `2026-08-29-001-ai-context-orchestration-adapter-plan.md`: post-PR #130 AI context orchestration plan covering adapter-based domain context, polling watcher materialization, ontology/SOP exploration, KG Level 0 traces, and deferred RAG/LangGraph gates.
- `2026-08-29-002-product-result-evidence-materialization-plan.md`: prerequisite product-evidence boundary plan covering Generator output validation, Product Result/Evidence materialization, lineage, checksum, and ViewModel consumption boundaries.
- `2026-08-29-003-evidence-snapshot-consistency-guard-plan.md`: sibling projection and guard plan ensuring UI ViewModel, Report, Closed-loop Recommendation Input, and Agent Review consume the same Product Result/Evidence snapshot without making ViewModel the Closed-loop input.
- `2026-08-27-001-pr130-sop-sensor-judgment-proposal.md`: PR #130 based Agent Review Packet, SOP judgment, scenario-based agent rationale, LLM summary, and minimum eval plan.

Use the 2026-08-29 AI context plan as the current source of truth for the next AI workflow architecture slice. Use the Product Result/Evidence materialization plan as its lower trusted-evidence prerequisite, not as an AI-only pipeline. Use the Evidence Snapshot Consistency Guard plan when discussing how UI, Report, Closed-loop, and Agent Review share one evidence basis while remaining separate projections. Use the 2026-08-27 PR #130 plan as the baseline source for read-only agent review, SOP maturity gate, field inspection reference, and LLM summary sequencing.

## Supporting Background Plans

- `2026-08-18-001-feat-week3-week4-evidence-report-ui-closure-plan.md`: Evidence-to-report workflow, grounded LLM summary, component planner, fallback, and evaluation closure.
- `2026-08-20-001-feat-recommendation-policy-gold-seed-plan.md`: Recommendation policy gold seed, deterministic evaluator, and AI evidence boundary.

## Removed As Duplicates

- `2026-08-24-001-feat-asset-detail-ui-agent-flow-plan.md`: folded into the current canonical PR #130 plan.
- `2026-08-27-001-sop-grounding-consumption-contract-proposal.md`: folded into the current canonical PR #130 plan.

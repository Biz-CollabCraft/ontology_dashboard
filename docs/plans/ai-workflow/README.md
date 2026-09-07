# AI Workflow Plans

AI, LLM, agent review, SOP grounding, and evaluation-related implementation plans live here. Closed-loop runtime, AssetDetailViewModel, and non-AI product workflow plans remain in `docs/plans/`.

## Current Canonical Plan

- `2026-09-07-001-pr167-role-aware-natural-language-briefing-model-trigger-optimization-plan.md`: PR #167 기반 역할별 자연어 브리핑, prose-only LLM editable boundary, 3역할 contract 정렬, 모델 품질·속도·비용 비교, Click/Always/Hybrid 생성 정책 및 발표 수정 계획.
- `2026-08-29-001-ai-context-orchestration-adapter-plan.md`: post-PR #130 AI context orchestration plan covering adapter-based domain context, polling watcher materialization, ontology/SOP exploration, KG Level 0 traces, and deferred RAG/LangGraph gates.
- `2026-08-29-002-product-result-evidence-materialization-plan.md`: prerequisite product-evidence boundary plan covering Generator output validation, Product Result/Evidence materialization, lineage, checksum, and ViewModel consumption boundaries.
- `2026-08-29-003-evidence-snapshot-consistency-guard-plan.md`: sibling projection and guard plan ensuring UI ViewModel, Report, Closed-loop Recommendation Input, and Agent Review consume the same Product Result/Evidence snapshot without making ViewModel the Closed-loop input.
- `2026-08-27-001-pr130-sop-sensor-judgment-proposal.md`: PR #130 based Agent Review Packet, SOP judgment, scenario-based agent rationale, LLM summary, and minimum eval plan.

Use the 2026-09-07 PR #167 plan as the active source of truth for role-aware natural-language briefing, model comparison, pre-generation policy, and the corresponding presentation correction. Use the 2026-08-29 AI context plan for the underlying context-orchestration architecture. Use the Product Result/Evidence materialization plan as its lower trusted-evidence prerequisite, not as an AI-only pipeline. Use the Evidence Snapshot Consistency Guard plan when discussing how UI, Report, Closed-loop, and Agent Review share one evidence basis while remaining separate projections. Use the 2026-08-27 PR #130 plan as the baseline source for read-only agent review, SOP maturity gate, field inspection reference, and LLM summary sequencing.

## Supporting Background Plans

- `2026-08-18-001-feat-week3-week4-evidence-report-ui-closure-plan.md`: Evidence-to-report workflow, grounded LLM summary, component planner, fallback, and evaluation closure.
- `2026-08-20-001-feat-recommendation-policy-gold-seed-plan.md`: Recommendation policy gold seed, deterministic evaluator, and AI evidence boundary.

## Removed As Duplicates

- `2026-08-24-001-feat-asset-detail-ui-agent-flow-plan.md`: folded into the current canonical PR #130 plan.
- `2026-08-27-001-sop-grounding-consumption-contract-proposal.md`: folded into the current canonical PR #130 plan.

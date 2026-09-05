# B3 Gold Scorer Surface-Match Analysis

## Scope

- Run ID: `final-20260903-748b305f`
- Source artifact: `tests/eval/results/agent_workflow_baseline_live_final-20260903-748b305f.json`
- Gold answers: `tests/fixtures/agent_review_packets/gold_answers.json`
- Focus: B3 `process_manager` satisfaction `12.5%`

This note records a post-run scorer review. It does not change the original
stored evaluation artifact.

## Finding

The original B3 workflow-value result was `0.697917`. The low
`process_manager` satisfaction was primarily caused by surface-form matching,
not missing process-manager meaning.

The previous scorer checked required points with exact substring matching.
Observed B3 process-manager outputs often used equivalent field wording:

| Gold point | Observed B3 wording |
| --- | --- |
| `생산 영향이 중간` | `중간 정도의 생산 영향`, `생산에 미치는 영향이 중간 수준` |
| `생산 영향이 낮은` | `생산에 미치는 영향이 낮으며`, `낮은 생산 영향` |
| `25건`, `32건`, `18건`, `13건` | `25개`, `32개`, `18개`, `13개`, `손실 예상 유닛` |
| `점검 승인` | `승인 검토`, `점검 승인 여부` |
| `전달` | `인계` |

## Recalibration Evidence

Re-scoring the stored B3 outputs with surface variants enabled gives:

| Fixture | Original gold | Re-scored gold | Original PM | Re-scored PM | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| GS-001 | 0.666667 | 0.763889 | 0.000000 | 0.333333 | Mixed: production impact wording matched, but `0건` and approval remain missing. |
| GS-002 | 0.625000 | 0.902778 | 0.000000 | 1.000000 | Surface-form mismatch. |
| GS-003 | 0.625000 | 0.902778 | 0.000000 | 1.000000 | Surface-form mismatch. |
| GS-004 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | Already matched. |
| GS-005 | 0.666667 | 0.902778 | 0.000000 | 1.000000 | Surface-form mismatch. |
| GS-006 | 0.625000 | 0.902778 | 0.000000 | 1.000000 | Surface-form mismatch. |
| GS-007 | 0.750000 | 0.791667 | 0.000000 | 0.000000 | Real data-quality-hold process-manager miss remains visible. |
| GS-008 | 0.625000 | 0.902778 | 0.000000 | 1.000000 | Surface-form mismatch. |

Aggregate B3 re-score:

- Gold mean: `0.697917 -> 0.883681`
- Process-manager satisfaction: `0.125000 -> 0.791667`

## Boundary

This correction is a scorer calibration for reference-answer triage. It is not
a claim that the LLM is semantically perfect, and it does not replace human
review. GS-007 remains a real miss because a data-quality-hold packet should
keep estimated production impact and similar-history language explicitly
uncertain instead of presenting a low production impact as ordinary manager
context.

## Follow-up Live Evidence

After the scorer calibration and process-manager generation fix, new local-dirty
live runs were recorded with candidate label `cb07147d64f4-dirty-pm-fix`.

| Run | Artifact | Result |
| --- | --- | --- |
| Live smoke, 8 rows | `tests/eval/results/agent_summary_llm_eval_live_smoke_20260905_pm_fix.json` | 8/8 accepted, fallback 0, gold 1.0, process-manager 1.0 |
| Live B1/B2/B3, 72 rows | `tests/eval/results/agent_workflow_baseline_live_20260905_pm_fix.json` | B3 gold 1.0, B3 process-manager 1.0, B3 fallback/reuse contained provider-unavailable rows |
| Live quality, 120 rows | `tests/eval/results/agent_summary_llm_eval_live_120_20260905_pm_fix.json` | 120/120 accepted, fallback 0, gold 1.0, role accuracy 1.0, missing required points 0 |

The 72-row workflow comparison should be reported with its arm-level caveat:
B1/B2 provider-unavailable rows were invalid and unscored, while B3 recovered
through retry/fallback/reuse. The 120-row quality run is the clean live quality
claim for the updated process-manager wording.

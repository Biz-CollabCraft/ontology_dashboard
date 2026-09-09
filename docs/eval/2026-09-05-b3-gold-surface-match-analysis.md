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
| Live B1/B2/B3 after PM validator, 72 rows | `tests/eval/results/agent_workflow_baseline_live_20260905_pm_validator_fix.json` | B3 gold 1.0 and process-manager 1.0 across 24/24 rows; stricter validator forced first-pass B3 PM misses into fallback/reuse |

The 72-row workflow comparison should be reported with its arm-level caveat:
B1/B2 provider-unavailable rows were invalid and unscored, while B3 recovered
through retry/fallback/reuse. After the PM validator hardening, B1/B2 rows are
not a clean schema-pass comparison because they do not have B3 fallback/reuse;
the strongest workflow-value claim is that B3 contains PM omissions and returns
grounded deterministic summaries instead. The 120-row quality run remains the
clean live quality claim for the updated process-manager wording before the
additional B3 fallback hardening.

## Overfit Check Status

The current `1.0` B3 result should be reported as fixture-based live-eval
evidence, not as proof of production-wide semantic accuracy. Two local
overfit guards are in place:

- A separate holdout/paraphrase fixture set is generated under
  `tests/fixtures/agent_review_packets_holdout/` with changed scenario IDs,
  asset IDs, production-impact levels, downtime, and lost-unit values.
- The gold scorer has a negative check so unrelated inventory counts such as
  `25개 부품 재고` do not satisfy a lost-units requirement such as `25건`.

Additional overfit evidence has now been recorded:

- Live holdout/paraphrase artifact:
  `tests/eval/results/agent_summary_llm_eval_live_holdout_paraphrase_20260905_pm_overfit_check.json`
- Human-review worksheet:
  `docs/eval/2026-09-05-agent-summary-human-review-holdout-pm-overfit-check.md`

The live holdout/paraphrase run covered 8 changed cases over 3 iterations each
and produced 24/24 accepted LLM candidates, fallback 0, gold `1.0`, role
accuracy `1.0`, and process-manager `1.0`.

The remaining overfit check is human review. A reviewer should mark PM
production impact, lost units, approval review, and data-quality-hold
uncertainty case by case. Until that review is complete, the strongest accurate
claim is: B3 reached `1.0` on the current gold/live fixture evaluations and on
a separate holdout/paraphrase live set, while production-wide semantic accuracy
still requires human review and operational evidence.

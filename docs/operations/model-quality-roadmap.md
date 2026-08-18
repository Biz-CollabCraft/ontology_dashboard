# Compressor model quality baseline and roadmap

This document records the production-facing quality baseline for the Canonical
V3.1 compressor failure-within-24h model. It is a release/operations record,
not a claim of SOTA predictive performance.

## Acceptance interpretation

The project accepts a model for the product closed loop when it has real signal,
reproducible feature/runtime parity, an immutable artifact, and a deployment
threshold selected without touching the final time holdout. Model quality is
still an ongoing ML-lifecycle responsibility after acceptance.

For Canonical V3.1, random prevalence is about `0.0352` in the hourly temporal
evaluation table. The legacy reference regression sanity benchmark is:

- ROC-AUC: `0.734353`
- PR-AUC / average precision: `0.222111`
- Top 5% recall: `0.283333`

The first Mac mini Generator artifact used only current sensor values and had
average precision about `0.0196`, with precision/recall/F1 all zero at the
fixed 0.5 threshold. That artifact is retained as immutable failure evidence
but is not an acceptable quality baseline.

## Temporal v2 baseline

Per-asset first-seven-day running baselines plus 1 h / 6 h temporal features
raised the selected RandomForest candidate to:

- regression sanity PR-AUC: `0.185693`
- regression sanity recall: `0.410417` at the v2 threshold
- deployment time-holdout PR-AUC: `0.509353`
- deployment recall: `0.958333`
- deployment precision: `0.056931`
- deployment F1: `0.107477`

This is acceptable for proving the real prediction → Model Artifact → Backend
inference → product closed loop, but the low precision produces too many alerts
for a mature operational model.

## v3 threshold-quality improvement

The ranking model remains RandomForest because the untouched time holdout has
the strongest ranking among the evaluated CPU-friendly candidates. Threshold
selection is changed to validation maximum F1 subject to validation recall >=
0.30. In the pre-release experiment this selects approximately `0.12` and gives
the untouched deployment holdout:

- PR-AUC: `0.509353` (ranking unchanged)
- precision: `0.135338`
- recall: `0.750000`
- F1: `0.229299`
- false positives: `115` instead of `381` in the same holdout

The threshold is selected from validation data only. The deployment holdout is
used for final release acceptance/regression reporting, not threshold tuning.

The v3 promotion gate additionally requires regression sanity PR-AUC >= `0.15`,
non-zero recall, and deployment alert precision above base prevalence.

## Candidate comparison

- LogisticRegression reproduces the legacy regression sanity PR-AUC almost
  exactly (`0.222111`) and is retained as an important regression reference.
  Its deployment time-holdout PR-AUC is lower (`0.335445`).
- HistGradientBoosting was evaluated as a CPU-friendly candidate. It reached
  regression sanity PR-AUC `0.203291` and deployment PR-AUC `0.472380`, but its
  validation-selected release threshold produced lower deployment F1 than the
  RandomForest v3 candidate, so it is not promoted.
- XGBoost/LightGBM/GPU/LSTM/Transformer are not justified by the current MVP
  requirements and 16 GiB M1 deployment target.

## Remaining improvement opportunities

1. Preserve a new lockbox time window before repeated model/threshold iteration;
   repeated decisions against the same final holdout eventually overfit the
   evaluation process even if training never sees its labels.
2. Add probability calibration and alert-budget/cost evaluation if product
   requirements define an acceptable false-positive workload.
3. Add drift monitoring by site/asset and retrain only when source distribution
   or alert quality materially changes.
4. Add calibrated new-asset baseline support instead of requiring every runtime
   asset to exist in the training artifact baseline map.
5. Add a separate CNC Model Artifact; until then CNC stays on the deterministic
   compatibility predictor while compressor uses the versioned trained artifact.
6. Add official local explanation support (for example a governed SHAP artifact)
   only if the product needs instance-level attribution beyond the current local
   proxy factor contract.

These items extend the existing ML lifecycle plan in
`docs/final_team_role_and_step_plan.md`: retraining, quality regression,
runtime feature parity, model limitation provenance, golden-vector tests, and
artifact reproducibility remain active responsibilities after first release.

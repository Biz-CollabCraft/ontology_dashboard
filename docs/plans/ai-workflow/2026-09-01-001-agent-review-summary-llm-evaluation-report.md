# Agent Review Summary LLM Evaluation Report

Date: 2026-09-01

## Scope

This report measures the read-only Agent Review Summary path for the 8-case
Agent Review Packet gold set. The evaluated path is:

```text
Agent Review Packet -> LLM candidate summary -> deterministic contract validator
```

The LLM is evaluated as an expression layer. It must not become the source of
domain truth, create Closed-loop mutations, approve maintenance work, claim
repair completion, or introduce unsupported facts.

## Evaluation Set

The gold set contains 8 packet fixtures:

- `GS-001`: normal stable state
- `GS-002`: heat-dissipation warning
- `GS-003`: low-confidence attention case
- `GS-004`: critical multi-factor case with one inspection target
- `GS-005`: multiple inspection-target case
- `GS-006`: SOP guidance unavailable case
- `GS-007`: data-quality hold case
- `GS-008`: LLM/offline fallback-oriented case

Each 120-run evaluation uses 8 cases x 15 iterations. This is enough to verify
contract stability, grounding behavior, and first-order provider reliability for
the current MVP slice. It is not a broad production load test.

## Metrics

Acceptance rate:

```text
accepted_llm_candidates / sample_size
```

Fallback rate:

```text
fallback_summaries / sample_size
```

Contract error rows:

```text
count(rows where validation_errors is not empty)
```

Grounding rate:

```text
rows_with_grounded_source_refs / sample_size
```

Latency:

```text
duration from candidate-generation start to candidate validation end
```

For live runs, this is end-to-end provider-call duration plus local validation
time. It is not a pure network-latency breakdown. The current provider port does
not expose provider-side timing, queueing, or token-usage metadata.

Cost:

```text
estimated prompt cost + estimated completion cost
```

The current harness estimates tokens from serialized payload size and configured
`gpt-4o-mini` price inputs. It is a configured-rate estimate, not provider
billing reconciliation.

Gold-set accuracy:

```text
accuracy_goldset_score = average(required_fact_score, role_accuracy_score, boundary_accuracy_score)
required_fact_score = matched required answer points / required answer points
role_accuracy_score = matched role answer points / role answer points
boundary_accuracy_score = 1.0 when no must-not claim appears, otherwise 0.0
```

The reference answers live in:

```text
tests/fixtures/agent_review_packets/gold_answers.json
```

The answer key is intentionally small for the current project size. It does not
try to match a full natural-language answer. Each case records only required
operational facts, role-specific expected points, visible limitations, and
must-not claims such as repair completion, approval completion, automatic
execution, or unsupported failure certainty.

Candidate semantic signals:

```text
coverage_candidate = passed packet-anchor checks / packet-anchor checks
usefulness_candidate = passed role-usefulness checks / role-usefulness checks
korean_quality_candidate = passed Korean-field-language checks / Korean checks
overall_candidate = average(coverage_candidate, usefulness_candidate, korean_quality_candidate)
```

Coverage candidate checks:

- `status_grade_present`: accepted prose contains the packet risk status grade.
- `primary_component_present`: accepted prose contains the primary inspection
  component when a component is present in the packet.
- `inspection_location_present`: field-operator copy contains the inspection
  location when a location is present in the packet.
- `production_context_present`: process-manager copy reflects production impact
  when the packet carries production-impact context.
- `history_context_present`: accepted prose mentions maintenance/request/history
  context when work orders or similar events are present.
- `data_gap_present_when_needed`: accepted prose mentions a limitation only when
  the packet has a visible `display_policy=show_limitation` evidence gap.

Usefulness candidate checks:

- `field_operator_has_action_focus`: field-operator copy tells the operator to
  inspect/check/confirm a concrete target or location.
- `field_operator_has_record_handoff_focus`: field-operator copy asks the
  operator to record symptoms, alarms, photos, or observations and hand them off
  to maintenance or production management.
- `manager_has_decision_context`: process-manager copy gives production,
  approval, priority, impact, or loss context.
- `roles_are_distinct`: field and manager role quotes are not identical.
- `summary_is_not_generic`: accepted prose mentions the asset, asset label, or
  inspection component from the packet.

Korean field-language checks:

- `contains_korean`: accepted prose contains Korean text.
- `avoids_internal_terms`: accepted prose does not expose internal terms such as
  `source_ref`, `event_id`, `asset_id`, `packet`, `schema`, or `closed_loop`.
- `uses_field_language`: accepted prose uses field-facing terms such as 설비,
  현장, 점검, 생산, 작업 처리, or 표준.
- `concise_for_side_panel`: summary and role quotes stay within the side-panel
  copy budget.

Gold-set accuracy is the metric to cite when claiming correctness. Candidate
semantic signals are triage columns only. The hard gates remain contract shape,
grounded source references, forbidden action claims, forbidden Closed-loop
authority, and fallback behavior. Usefulness and Korean quality still need a
small human-reviewed acceptance sample before they become release gates.

## Results

### Controlled Mock 120-Run

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_mock_2026-09-01.json
```

Result:

- sample size: 120
- accepted candidates: 120
- fallback summaries: 0
- contract-error rows: 0
- grounding rate: 1.0
- estimated total cost: USD 0.169101

Interpretation:

The mock result validates the harness, schema checks, grounding checks, and cost
aggregation path. It must not be reported as live model quality.

### Controlled Mock 120-Run with Semantic Scores

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_mock_quality_2026-09-01.json
```

Result:

- sample size: 120
- prompt payload profile: `compact-editable-v1`
- concurrency: 8
- accepted candidates: 120
- fallback summaries: 0
- contract-error rows: 0
- `accuracy_goldset_score`: 1.0
- `coverage_candidate`: 1.0
- `usefulness_candidate`: 1.0
- `korean_quality_candidate`: 1.0
- `overall_candidate`: 1.0
- estimated total cost: USD 0.04092975

Interpretation:

This result proves that reference-answer accuracy and candidate semantic signals
are recorded and aggregated for every accepted row. It is a controlled baseline
against the deterministic summary, not live model quality. Existing live result
artifacts recorded contract, grounding, latency, and cost metrics, but did not
store the accepted candidate text. Therefore gold-set accuracy, usefulness, and
Korean quality should be measured from the next live rerun using the updated
harness rather than backfilled from the old live artifacts.

### Live Smoke Run

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_smoke_2026-09-01.json
```

Result:

- sample size: 8
- accepted candidates: 8
- fallback summaries: 0
- contract-error rows: 0
- p50 latency: 16,763.825 ms
- p95 latency: 18,476.763 ms
- average latency: 16,221.258 ms
- estimated total cost: USD 0.0112626

Interpretation:

The smoke run confirms that the configured live `gpt-4o-mini` path can produce
validator-accepted Agent Review Summary candidates for every gold-set case.

### Live 120-Run

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_2026-09-01.json
```

Result:

- sample size: 120
- accepted candidates: 118
- acceptance rate: 0.983333
- fallback summaries: 2
- fallback rate: 0.016667
- fallback reason: `ReadTimeout` for both fallback rows
- contract-error rows: 0
- grounding rate: 1.0
- p50 latency: 16,528.991 ms
- p95 latency: 19,858.608 ms
- average latency: 16,642.154 ms
- estimated total cost: USD 0.1689318
- estimated average cost per accepted summary: USD 0.00143163

Interpretation:

The quality gate passed: there were no schema-contract errors, no unsupported
source-ref rows, and no observed Closed-loop authority leak in accepted output.

The operating gate is partial: 2/120 live calls fell back because of provider
read timeouts. This is an operational reliability issue, not a grounding or
contract-shape issue. Production use should add retry policy, checkpointed
execution, and progress reporting before treating live 120-run execution as a
release gate.

### Live 120-Run with Concurrency 4

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_c4_2026-09-01.json
```

Result:

- sample size: 120
- concurrency: 4
- batch wall-clock duration: 593,433.237 ms
- throughput: 12.132789 requests/minute
- accepted candidates: 100
- acceptance rate: 0.833333
- fallback summaries: 20
- fallback rate: 0.166667
- fallback reason: `ReadTimeout` for all fallback rows
- contract-error rows: 0
- grounding rate: 1.0
- p50 request latency: 19,635.85 ms
- p95 request latency: 22,375.92 ms
- average request latency: 19,703.355 ms
- p50 queue wait: 294,252.155 ms
- p95 queue wait: 551,242.319 ms
- estimated total cost: USD 0.1690266
- operating gate: partial, 20 observed fallback rows against 2 allowed rows

Interpretation:

Concurrency 4 reduced the total wall-clock duration compared with sequential
execution, but it materially worsened live provider reliability. The failure
mode stayed operational: every fallback row was `ReadTimeout`, while contract
errors and source-ref grounding failures remained 0. This means concurrency 4
should not be promoted as the current default without retry, timeout tuning, and
checkpointed recovery.

### Compact Input and Output Evidence

Before changing the live prompt payload, the provider sent the full
`agent_review_packet`, the full `baseline_summary`, and all allowed output
fields, and asked the LLM to return the full public summary shape. The compact
provider keeps the same public summary contract but sends only grounded summary
context plus editable baseline fields, and asks the LLM to return only prose
edits for `title`, `summary`, and `role_summaries[*].quote`.

Measured against the 8 gold packets, the serialized request payload changed as
follows:

- `GS-001`: 23,508 bytes -> 7,579 bytes, 67.76% reduction
- `GS-002`: 26,735 bytes -> 8,096 bytes, 69.72% reduction
- `GS-003`: 29,146 bytes -> 8,128 bytes, 72.11% reduction
- `GS-004`: 17,565 bytes -> 6,532 bytes, 62.81% reduction
- `GS-005`: 29,125 bytes -> 8,104 bytes, 72.18% reduction
- `GS-006`: 23,512 bytes -> 7,568 bytes, 67.81% reduction
- `GS-007`: 12,941 bytes -> 5,798 bytes, 55.20% reduction
- `GS-008`: 29,094 bytes -> 8,089 bytes, 72.20% reduction
- average reduction: 67.47%

The expected serialized output payload also changed from full
`agent-review-summary-v1.0` examples to editable-only examples:

- `GS-001`: 6,876 bytes -> 1,344 bytes, 80.45% reduction
- `GS-002`: 7,114 bytes -> 1,347 bytes, 81.07% reduction
- `GS-003`: 7,126 bytes -> 1,356 bytes, 80.97% reduction
- `GS-004`: 6,123 bytes -> 1,259 bytes, 79.44% reduction
- `GS-005`: 7,109 bytes -> 1,361 bytes, 80.86% reduction
- `GS-006`: 6,879 bytes -> 1,346 bytes, 80.43% reduction
- `GS-007`: 6,069 bytes -> 1,184 bytes, 80.49% reduction
- `GS-008`: 7,114 bytes -> 1,347 bytes, 81.07% reduction
- average reduction: 80.60%

The response schema itself changed from the full public summary schema to the
editable-only schema:

- full summary schema: 2,830 bytes
- editable schema: 514 bytes
- schema reduction: 81.84%

This supports input/output reduction as the first corrective action. Lowering
concurrency only finds the current operating limit; it does not address the
heavy prompt, heavy response shape, and larger strict schema that pushed live
calls close to the 20-second timeout boundary.

### Live 120-Run with Compact Payload and Concurrency 4

Smoke artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_compact_c4_smoke_2026-09-01.json
```

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_compact_c4_2026-09-01.json
```

Smoke result:

- sample size: 8
- prompt payload profile: `compact-editable-v1`
- concurrency: 4
- batch wall-clock duration: 8,048.079 ms
- accepted candidates: 8
- fallback summaries: 0
- p50 request latency: 3,731.703 ms
- p95 request latency: 4,315.279 ms
- estimated total cost: USD 0.00272865

Result:

- sample size: 120
- prompt payload profile: `compact-editable-v1`
- concurrency: 4
- batch wall-clock duration: 114,542.742 ms
- throughput: 62.858631 requests/minute
- accepted candidates: 120
- acceptance rate: 1.0
- fallback summaries: 0
- fallback rate: 0.0
- contract-error rows: 0
- grounding rate: 1.0
- p50 request latency: 3,675.527 ms
- p95 request latency: 5,359.453 ms
- average request latency: 3,791.982 ms
- p50 queue wait: 56,512.444 ms
- p95 queue wait: 106,520.111 ms
- estimated total cost: USD 0.04092975
- estimated average cost per accepted summary: USD 0.00034108
- operating gate: passed

Interpretation:

The compact payload corrected the observed concurrency-4 failure mode without
lowering concurrency. Compared with the full-payload concurrency-4 run, fallback
rows dropped from 20 to 0, p95 request latency dropped from 22,375.92 ms to
5,359.453 ms, batch wall-clock duration dropped from 593,433.237 ms to
114,542.742 ms, and estimated configured-rate cost dropped from USD 0.1690266
to USD 0.04092975.

### Live 120-Run with Compact Payload and Concurrency 8

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_compact_c8_2026-09-01.json
```

Result:

- sample size: 120
- prompt payload profile: `compact-editable-v1`
- concurrency: 8
- batch wall-clock duration: 63,890.402 ms
- throughput: 112.692983 requests/minute
- accepted candidates: 120
- acceptance rate: 1.0
- fallback summaries: 0
- fallback rate: 0.0
- contract-error rows: 0
- grounding rate: 1.0
- p50 request latency: 3,952.738 ms
- p95 request latency: 5,018.95 ms
- average request latency: 4,109.452 ms
- p50 queue wait: 28,061.77 ms
- p95 queue wait: 55,631.332 ms
- estimated total cost: USD 0.04092975
- estimated average cost per accepted summary: USD 0.00034108
- operating gate: passed

Interpretation:

Compact payload with concurrency 8 passed the same 120-request gate. Compared
with compact concurrency 4, it reduced batch wall-clock duration from
114,542.742 ms to 63,890.402 ms and increased throughput from 62.858631 to
112.692983 requests/minute while keeping fallback rows at 0 and grounding rate
at 1.0. Request p50 latency increased slightly, from 3,675.527 ms to 3,952.738
ms, but p95 remained comparable. This makes concurrency 8 a viable pressure-test
result for the compact prompt profile, not yet a production default without
rate-limit telemetry, retry accounting, and checkpointed recovery.

### Live 120-Run with Compact Payload, Concurrency 8, and Gold Accuracy

Artifact:

```text
tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt4o_mini_gold_2026-09-01.json
```

Result:

- sample size: 120
- model: `gpt-4o-mini`
- prompt version: `agent-review-summary-prompt-v1.2-role-workflow`
- prompt payload profile: `compact-editable-v1`
- concurrency: 8
- batch wall-clock duration: 59,973.108 ms
- throughput: 120.053808 requests/minute
- accepted candidates: 120
- fallback summaries: 0
- contract-error rows: 0
- grounding rate: 1.0
- `accuracy_goldset_score`: 1.0
- missing required points: 0
- must-not claim violations: 0
- `coverage_candidate`: 1.0
- `usefulness_candidate`: 1.0
- `korean_quality_candidate`: 1.0
- p50 request latency: 3,658.122 ms
- p95 request latency: 5,476.296 ms
- estimated total cost: USD 0.0412605
- operating gate: passed

Interpretation:

This is the first live artifact that stores accepted candidate text and scores
it against the explicit 8-case answer key. It upgrades the `gpt-4o-mini`
evidence from "contract and grounding passed" to "contract, grounding, gold-set
accuracy, Korean-field signal, latency, and configured-rate cost all passed for
the MVP 8x15 evaluation." It does not remove the need for a small human
acceptance sample before promoting usefulness or Korean quality to hard release
gates.

The `v1.2-role-workflow` prompt keeps the expansion minimal: it does not add
MES, ERP, CMMS, WMS, quality-lot, customer-order, or air-compressor dependency
domains. It only tightens role wording so `field_operator` handles
shop-floor inspection, symptom recording, and handoff, while `process_manager`
keeps production impact, priority, approval review, and line/cell sequencing.

## Current Judgment

The Agent Review Summary LLM path is ready to remain enabled behind
deterministic validation and fallback with the compact payload profile. It is
also a viable concurrency-4 and concurrency-8 batch candidate for the current
8x15 MVP eval set. Production runtime still needs checkpoint support, retry
telemetry, and rate-limit accounting before being treated as an unattended
release gate.

Use the current result as:

- positive evidence for contract stability
- positive evidence for grounded summary acceptance
- positive evidence for gold-set answer-key accuracy on the live compact
  `gpt-4o-mini` 120-run
- positive evidence for rough `gpt-4o-mini` cost scale
- positive evidence that compact payload reduction addresses the timeout-heavy
  concurrency-4 failure mode
- negative evidence that full-payload concurrency 4 is safe without prompt
  compaction
- positive pressure-test evidence that compact-payload concurrency 8 can
  complete the same 120-request gate with 0 fallbacks

## Model Comparison Plan

Compare three models with the same compact payload profile, same 8x15 gold set,
same validator, and same concurrency:

| Model | Role in comparison | Input price / 1M | Output price / 1M | Why include it |
| --- | --- | ---: | ---: | --- |
| `gpt-4o-mini` | Current measured baseline | USD 0.15 | USD 0.60 | Already measured; lowest current cost baseline for this path. |
| `gpt-5.6-luna` | Cost-sensitive high-volume candidate | USD 0.20 | USD 1.20 | Similar cost tier, newer model family, suitable for high-volume structured summary generation. |
| `gpt-5-mini` | Quality/robustness comparison candidate | USD 0.25 | USD 2.00 | More expensive than Luna/4o-mini, useful as a higher-quality reference point. |

Evaluation axes:

1. Quality and accuracy.
   Use hard contract metrics plus `accuracy_goldset_score`, required evidence
   coverage, role usefulness, Korean field-language quality, priority
   correctness, concision, and human accept-without-edit ratio.
2. Operating reliability.
   Compare accepted rate, fallback rate, `ReadTimeout`, rate-limit events, p50
   and p95 request latency, queue wait, throughput, and batch wall-clock
   duration at the same concurrency.
3. Cost efficiency.
   Compare estimated total cost per 120-run, estimated cost per accepted
   summary, prompt tokens, completion tokens, and quality-adjusted cost once the
   candidate accuracy review exists.

Initial model-comparison run:

```text
8 gold cases x 15 iterations = 120 total requests per model
prompt payload profile = compact-editable-v1
concurrency = 8
models = gpt-4o-mini, gpt-5.6-luna, gpt-5-mini
```

Do not mix model comparison with prompt/schema changes. If the prompt payload
changes again, rerun all three models under the same new profile.

## Model Comparison Results

Recorded artifacts:

- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt4o_mini_gold_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt56_luna_smoke_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt56_luna_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt5_mini_smoke_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt5_mini_smoke_timeout60_2026-09-01.json`

The model comparison used the same compact payload profile and concurrency 8.
The OpenAI-compatible provider had to omit `temperature=0` for GPT-5-family
models because those endpoints rejected non-default temperature values.

| Model | Scope | Accepted | Fallback | Contract errors | Grounding | Gold accuracy | p95 latency | Wall-clock | Estimated cost | Judgment |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gpt-4o-mini` | 120-run, gold-scored | 120/120 | 0 | 0 | 1.0 | 1.0 | 5,476.296 ms | 59,973.108 ms | USD 0.0412605 | Best current default. |
| `gpt-5.6-luna` | smoke | 8/8 | 0 | 0 | 1.0 | not measured | 10,187.532 ms | 10,190.517 ms | USD 0.0045186 | Compatible after temperature fix. |
| `gpt-5.6-luna` | 120-run | 119/120 | 1 | 1 | 0.991667 | not measured | 12,910.35 ms | 145,302.416 ms | USD 0.0675846 | Viable but weaker than baseline. |
| `gpt-5-mini` | smoke, 20s timeout | 0/8 | 8 | 0 | 1.0 | not measured | 20,866.351 ms | 20,869.504 ms | USD 0.00590275 | Fails operating smoke by timeout. |
| `gpt-5-mini` | smoke, 60s timeout | 5/8 | 3 | 3 | 0.625 | not measured | 32,522.984 ms | 32,526.047 ms | USD 0.00790875 | Not promoted to 120-run. |

Quality leaderboard policy:

| Metric | Current evidence state | Use in decision |
| --- | --- | --- |
| Contract and boundary pass | Available in existing live artifacts | Hard gate |
| Grounding rate | Available in existing live artifacts | Hard gate |
| `accuracy_goldset_score` | Available for `gpt-4o-mini` gold-scored live 120-run | Correctness comparison |
| `coverage_candidate` | Available for `gpt-4o-mini` gold-scored live 120-run | Triage signal |
| `usefulness_candidate` | Available for `gpt-4o-mini` gold-scored live 120-run; requires human calibration before release gating | Triage signal |
| `korean_quality_candidate` | Available for `gpt-4o-mini` gold-scored live 120-run; requires human calibration before release gating | Triage signal |
| p95 latency and cost | Available in existing live artifacts | Operating and cost comparison |

`gpt-5.6-luna` failed one accepted-candidate validation row because the output
contained the forbidden Korean phrase `수리 완료`. That is an accuracy/boundary
issue caught by the deterministic validator, not a timeout issue.

`gpt-5-mini` was not promoted to a 120-run comparison because it failed both
smoke gates: with the default 20-second timeout every row timed out, and with a
60-second timeout only 5/8 rows were accepted while three rows failed priority
claim validation.

Current model choice:

- Use `gpt-4o-mini` as the default for the current Agent Review Summary path.
- Keep `gpt-5.6-luna` as an experimental candidate only if Korean wording or
  reasoning quality is later shown to beat `gpt-4o-mini` under human review.
- Do not use `gpt-5-mini` for this compact summary path without a different
  prompt contract or model-specific timeout strategy.

The strongest product evidence now reads as follows: model selection is not
based on cost alone. The selected model passes contract and grounding gates,
matches the 8-case manufacturing answer key, avoids Closed-loop authority
leakage, stays acceptable in Korean field-copy signals, and keeps latency and
cost within the MVP workflow budget.

## Deferred Factory Operating Context

Customer persona, CNC/air-compressor dependency, synthetic MES/ERP/CMMS/WMS
fixtures, spare inventory, and quality-lot impact remain future adoption
candidates. They should be introduced only when role-specific outputs repeatedly
need those facts or when the demo scope explicitly moves from Agent Review
Summary evaluation to a broader factory operating workflow. Until then, the
current slice uses existing packet facts plus the role-flow prompt and answer
key rather than inventing customer-order, inventory, lot, or actual integration
claims.

## Next Measurement

The next measurement should not multiply the sample size for `gpt-4o-mini`.
That model already has a gold-scored 8x15 live result. The next step is either
human calibration or same-harness model comparison:

```text
human calibration = 8 representative accepted outputs, one per gold case
same-harness model comparison = 8 gold cases x 15 iterations, concurrency 8
```

For human calibration, record:

- whether each accepted output is usable without edit
- any incorrect required fact
- any awkward Korean field-language phrase
- any role-mismatch issue between field operator and process manager copy
- whether automatic `usefulness_candidate` and `korean_quality_candidate` agree
  with human judgment

For same-harness model comparison, rerun only candidates still worth promoting:

- `gpt-5.6-luna`: rerun with the gold-scored harness only if a Korean wording or
  reasoning-quality advantage is expected to offset its slower latency and
  previous boundary failure.
- `gpt-5-mini`: do not rerun at 120 until the timeout and priority-mismatch
  smoke failures are addressed.

Runtime recovery instrumentation is still useful before production operation:
record retry attempts, retry outcome, rate-limit events, and
accepted-after-retry rate separately from model quality.

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

Candidate accuracy metrics:

- Required evidence coverage: whether each case's expected operational facts are
  present in `summary` or role quotes.
- Role usefulness: whether `field_operator` copy answers what to inspect and
  where, while `process_manager` copy answers risk, production context, and
  approval-review context.
- Korean field-language quality: whether the summary avoids internal-only terms,
  awkward literal translation, and excessive caveats.
- Priority correctness: whether risk, confidence, data-quality hold, SOP
  availability, and production-impact wording match packet facts.
- Concision: whether accepted summaries stay short enough for the workflow side
  panel.
- Human accept-without-edit ratio: manual review result for whether the summary
  could ship as-is.

These candidate accuracy metrics are not hard gates yet. The current hard gates
remain contract shape, grounding, and boundary compliance. A model comparison can
use the candidate metrics as review columns before they become deterministic
release gates.

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
   Use hard contract metrics plus candidate accuracy review columns: required
   evidence coverage, role usefulness, Korean field-language quality, priority
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
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt56_luna_smoke_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt56_luna_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt5_mini_smoke_2026-09-01.json`
- `tests/eval/results/agent_summary_llm_eval_live_compact_c8_gpt5_mini_smoke_timeout60_2026-09-01.json`

The model comparison used the same compact payload profile and concurrency 8.
The OpenAI-compatible provider had to omit `temperature=0` for GPT-5-family
models because those endpoints rejected non-default temperature values.

| Model | Scope | Accepted | Fallback | Contract errors | Grounding | p95 latency | Wall-clock | Estimated cost | Judgment |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gpt-4o-mini` | 120-run | 120/120 | 0 | 0 | 1.0 | 5,018.95 ms | 63,890.402 ms | USD 0.04092975 | Best current default. |
| `gpt-5.6-luna` | smoke | 8/8 | 0 | 0 | 1.0 | 10,187.532 ms | 10,190.517 ms | USD 0.0045186 | Compatible after temperature fix. |
| `gpt-5.6-luna` | 120-run | 119/120 | 1 | 1 | 0.991667 | 12,910.35 ms | 145,302.416 ms | USD 0.0675846 | Viable but weaker than baseline. |
| `gpt-5-mini` | smoke, 20s timeout | 0/8 | 8 | 0 | 1.0 | 20,866.351 ms | 20,869.504 ms | USD 0.00590275 | Fails operating smoke by timeout. |
| `gpt-5-mini` | smoke, 60s timeout | 5/8 | 3 | 3 | 0.625 | 32,522.984 ms | 32,526.047 ms | USD 0.00790875 | Not promoted to 120-run. |

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

## Next Measurement

The next live measurement should not multiply the sample size. It should keep
the same 120 requests and execute them with compact payload plus runtime
recovery instrumentation:

```text
8 gold cases x 15 iterations = 120 total requests
concurrency = 4
retry exhausted rows must be measured separately
```

Record:

- request latency
- queue wait
- attempt count
- retry outcome
- fallback reason
- batch wall-clock duration
- rate-limit events
- accepted-after-retry rate

Recommended sequence:

1. Reuse the existing sequential 120-run as concurrency `1` baseline.
2. Keep `compact-editable-v1` as the provider payload profile.
3. Add retry and checkpoint support to the harness.
4. Re-run the same 120 requests at concurrency `4` and `8`.
5. Compare retry-exhausted rows, rate-limit events, p95 request latency, queue
   wait, and batch wall-clock duration before selecting a runtime default.

The concurrency `4` run should be considered successful when contract-error
rows remain 0, grounding rate remains 1.0, retry-exhausted timeout rows are 0 or
at most 1/120, and batch wall-clock time decreases materially from the
sequential baseline.

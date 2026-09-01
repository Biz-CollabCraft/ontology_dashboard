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

### Compact Payload Evidence

Before changing the live prompt payload, the provider sent the full
`agent_review_packet`, the full `baseline_summary`, and all allowed output
fields. The compact provider keeps the same public summary contract but sends
only grounded summary context plus editable baseline fields.

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

This supports payload reduction as the first corrective action. Lowering
concurrency only finds the current operating limit; it does not address the
heavy prompt and response shape that pushed live calls close to the 20-second
timeout boundary.

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

## Current Judgment

The Agent Review Summary LLM path is ready to remain enabled behind
deterministic validation and fallback with the compact payload profile. It is
also a viable concurrency-4 batch candidate for the current 8x15 MVP eval set.
Production runtime still needs checkpoint support and retry telemetry before
being treated as an unattended release gate.

Use the current result as:

- positive evidence for contract stability
- positive evidence for grounded summary acceptance
- positive evidence for rough `gpt-4o-mini` cost scale
- positive evidence that compact payload reduction addresses the timeout-heavy
  concurrency-4 failure mode
- negative evidence that full-payload concurrency 4 is safe without prompt
  compaction

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
4. Re-run the same 120 requests at concurrency `4`.
5. Only if concurrency `4` is stable after retry, run the same 120 requests at
   concurrency `8` as a pressure test.

The concurrency `4` run should be considered successful when contract-error
rows remain 0, grounding rate remains 1.0, retry-exhausted timeout rows are 0 or
at most 1/120, and batch wall-clock time decreases materially from the
sequential baseline.

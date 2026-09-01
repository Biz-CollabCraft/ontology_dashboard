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

## Current Judgment

The Agent Review Summary LLM path is ready to remain enabled behind deterministic
validation and fallback. It is not yet ready to be treated as an unattended
production batch/runtime gate without retry and checkpoint support.

Use the current result as:

- positive evidence for contract stability
- positive evidence for grounded summary acceptance
- positive evidence for rough `gpt-4o-mini` cost scale
- partial evidence for live provider reliability
- negative evidence that the current sequential harness is sufficient for
  operational throughput measurement

## Next Measurement

The next live measurement should not multiply the sample size. It should keep
the same 120 requests and execute them with bounded parallelism:

```text
8 gold cases x 15 iterations = 120 total requests
concurrency = 4
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
2. Run the same 120 requests at concurrency `4`.
3. Only if concurrency `4` is stable, run the same 120 requests at concurrency
   `8` as a pressure test.

The concurrency `4` run should be considered successful when contract-error
rows remain 0, grounding rate remains 1.0, retry-exhausted timeout rows are 0 or
at most 1/120, and batch wall-clock time decreases materially from the
sequential baseline.

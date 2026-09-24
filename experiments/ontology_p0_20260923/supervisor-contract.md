# Ontology P0 supervisor execution contract

Date: 2026-09-23. Status: preparation and bounded preflight; no product improvement selected.

## Question and ownership
Does the existing generation/read separation and snapshot architecture retain its scoped guarantees under continuous Product Result events and slow downstream generation?

- Observed problem: no new operational incident observed; current sustained-workload guarantee lacks this experiment's evidence.
- Human hypothesis: unrecorded.
- AI/challenger hypotheses: serial candidate generation plus post-batch polling sleep can delay latest-ready; cached latest-stored fallback may differ from the approved strict exact-snapshot invariant.
- Falsification condition: matched normal/slow workload maintains exact scoped correctness and shows no sustained GET/control-asset/error/pending degradation attributable to generation delay.
- Decision required: user-owned required freshness and acceptability of historical stored prose, and any product improvement selection after evidence.
- Human decision: pending. Changed belief: unrecorded.
- Alternatives before evidence: baseline; if stale historical output violates required contract, return pending on exact miss versus explicitly separate historical content and readiness in the API/UI. No adoption assumed.

## Environment and preservation
Primary execution: DevSpace Max workspace ws_98abfab73c, repository /Users/hb/Projects/ontology-dashboard. HEAD verified 71337cddd755eaa8cdb762af4598e21b2f7d085f. Existing dirty files are preserved.

Initial SHA256:
- AGENTS.md: 0bc0a488ce7509accd64abcb03011f07751723b051fcc8047b4e2778ba317a57
- docs/plans/ai-workflow/README.md: 3f82f9411e94e39caa0a19207dea1f05816656c5854a809117f0e77b3f1a18c2
- docs/engineering/ai-assisted-engineering-workflow.md: 701f9019e4f7ebf69fb9fb9fa34eb795bf169f6eef5169cad17595be1960848b
- docs/plans/ai-workflow/2026-09-23-001-agent-review-operational-limits-measurement-plan.md: d7c3368cf67b6c05d31c2e7b4ccaa934f84a5c15a73e0abb89c0b00a8a22c2b1

Dedicated container ontology-p0-20260923-pg, PostgreSQL16 image digest sha256:a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6, 127.0.0.1:55433, cpus2, memory2g. Synthetic databases ontology_p0_* only. Existing .venv Python3.12.14 augmented with psycopg3.3.6, psycopg-binary3.3.6 and psycopg-pool3.3.3. No operating database, paid provider, deployment, commit or push permitted. No global prune/shared-service stop.

## Work division and measurement gate
- runtime_map: runtime read and isolated fixture.py.
- harness: runner/provider/minimal tracing only inside this directory.
- oracle: independent assertions, tiny diagnostic tests and skeptical review.
- supervisor: resource scheduling, integration and evidence report.

Inventory supervisor (source task 01a0cd69-3b83-7a81-b246-8d7aa5e7c98d) uses port55432 and inventory-p0 names. Both supervisors agreed to serialize full load; no full load has started at this record. Small overlapping smoke must be disclosed.

Freeze default always, watcher interval60 after serial scan, limitNone (runtime page default20), workflow max_attempts2. Provisional matched measurement sequence480s so slow ten-asset scans can span >=3 cycles; validate actual completed cycles, never infer from duration alone. Warmup>=2 complete cycles; normal/slow/fault three repeats if no hard gate fires, drain<=300s. Actual harness manifest supersedes provisional details only with explicit evidence of why.

First perform bounded changed-snapshot preflight: exact hit, mutate same-event context, query; distinguish exact ready, historical LATEST_STORED provenance, fallback and missing. Hard invariant failure stops higher-rate/full-load escalation; preserve raw evidence and report which planned measurements were not run. No automatic product improvement or second experiment cycle.

# Independent review: bounded PostgreSQL preflight

Evidence: `runs/preflight-03/raw.jsonl` (179 rows), independently processed by `oracle.py`; output `runs/preflight-03/oracle.json`. Source and SQLite diagnostic evidence remain separately preserved.

## Findings
- Five actual in-process API GETs: one pending miss, one exact validated stored response, three disclosed historical responses after same-event operational context mutation.
- Eleven provider boundary starts: ten baseline generations and one delayed generation. None attributed to a GET request. No duplicate exact-key boundary call candidates in this small sample.
- Both actual DB context imports changed context hash and summary key while retaining event/source identity. All three later reads returned the original stored key with LATEST_STORED; no new-key rebinding was observed. Therefore the strict requested-current-snapshot gate is not met, while historical provenance is preserved. Source review also found explicit frontend historical labeling. This is not evidence of concealed stale content or scope leak.
- The delayed generation ended after 10.251 seconds in RuntimeError. Raw probe storage checks show neither the in-flight invalidated key nor its successor stored, and worker_alive=false. The persisted workflow record in `runs/preflight-03/failed-workflow-forensic.json` confirms the same run ID `8fb511cc-4860-41e9-bedb-be8637293c56`, failed status, and `error_message=agent_review_context_changed_during_generation`. Together with the effective context mutations and absent stored keys, this confirms the snapshot binding guard blocked publication in this probe. It does not establish multi-process lease fencing or crash recovery.
- Nine protected closed-loop business table digests match before/after; every table was empty in this fixture. This establishes no final writes to these tables in this run, not comprehensive business side-effect coverage or detection of transient create/delete pairs.
- GET during generation was approximately 117 ms; only five GETs total. Report observed single-request timings, not p95 or durable latency isolation. Analyzer p95 fields are mechanical nearest-rank summaries, explicitly unsuitable for capacity claims at this n.

## Completion boundary
This is a valid bounded provider-delay/context-change probe after fixture setup corrections. It is not completion of the approved sustained-event P0 workload: no measurement window, zero measurement-phase poll cycles, no repeated normal/slow pair, no timeout/recovery sequence, no latest-only event conservation or backlog trend, and no full 300-second drain. Earlier preflights with invalid packets and zero provider starts are setup failures and must not be pooled with this run.

The runtime used an administrative PostgreSQL connection according to harness/parent disclosure; this does not validate non-bypass RLS isolation. Scope-key inclusion and unchanged scope in this probe are not adversarial cross-scope authorization tests. Provider quality, real HTTP retry behavior, cost, network API latency, crash/lease recovery and multi-process behavior remain unmeasured.

## Decision alternatives, not implemented
1. Exact-only GET readiness: return pending until the current exact identity exists; historical display would need a separately explicit contract. Downside: removes currently intentional useful historical briefing availability.
2. Preserve historical briefing display and explicitly separate current readiness from stored history in the API/acceptance contract. Downside: clients must distinguish history from ready-current, and strict existing plan wording must be revised by its owner.
3. Baseline: keep behavior and document the mismatch; no claim that the original exact gate passed.

Human decision and Changed belief remain pending/unrecorded. No product improvement was selected or implemented by this reviewer. Stop here; do not start an automatic improvement cycle.

# Decision Agent gold quality comparison — Luna live smoke, 2026-09-15

This evaluation checks whether the Decision Agent planner selects the human-authored gold next action on ambiguous manufacturing cases. The ranking prompt already contains domain rules for measurement needs, persistent worsening, reserved stock, future replenishment, unsuitable windows, due pressure, and source-owned blockers, so this does not isolate model reasoning from prompt policy design. It is fixture-backed for operational data. The `llm` arm uses a live external LLM provider call when the command is run with `--live`. It does not measure factory downtime, cost, operator adoption, or deployed production behavior.

## Gold set

Gold file: `evaluation/decision_quality/decision-agent-gold-v1.json`

The gold set contains seven ambiguous cases derived from the existing Decision Agent scenario design:

1. persistent rapid warning with no inspection → `REQUEST_INSPECTION`
2. transient warning with explicit measurement need → `REQUEST_ADDITIONAL_DIAGNOSIS`
3. maintenance recommended but reserved stock ownership is unverified and window is unsuitable → abstain
4. maintenance recommended with low due pressure, enough slack, available stock, suitable window → `REVIEW_PLANNED_MAINTENANCE`
5. maintenance recommended but part is unavailable with future replenishment only → abstain
6. conflicting maintenance evidence that tools cannot reconcile → abstain
7. unknown trend with unverified calibration → `REQUEST_ADDITIONAL_DIAGNOSIS`

Gold review is built into the script. It checks that:

- gold actions stay inside deterministic Policy Guard when an action is expected;
- each case has required tools;
- gold action is not also listed as a forbidden action;
- case id, rationale, and gold fields are not visible in tool payloads.

## Live smoke result

Command:

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_agent_gold_quality.py   --arm both --iterations 3   --env-file /Users/hb/.devspace/worktrees/ontology-dashboard-9a87037d/.env   --model gpt-5.6-luna --reasoning-effort low --live   --output artifacts/decision-agent-gold-quality-luna-live-2026-09-15.json
```

The env file was used for credentials and endpoint configuration. Secrets are not included in this document.

| Arm | Runs | Exact gold action | Required tool coverage | Forbidden action avoided | Policy contained | Mean latency | Mean API calls | Mean tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| deterministic | 21 | 71.4% | 100.0% | 100.0% | 100.0% | 0.027s | 0.0 | not measured |
| Luna live planner | 21 | 76.2% | 100.0% | 100.0% | 100.0% | 7.029s | 3.0 | 2,093.5 |

## Case-level interpretation

| Case | Gold | Deterministic | Luna live |
| --- | --- | --- | --- |
| A1 persistent rapid | inspection | 3/3 exact | 3/3 exact |
| A2 transient measurement | additional diagnosis | 3/3 exact | 3/3 exact |
| A3 reserved + unsuitable window | abstain | 0/3 exact | 1/3 exact |
| A4 ready planned | planned maintenance review | 3/3 exact | 3/3 exact |
| A5 future replenishment only | abstain | 0/3 exact | 0/3 exact |
| A6 conflicting evidence | abstain | 3/3 exact | 3/3 exact |
| A7 unknown trend | additional diagnosis | 3/3 exact | 3/3 exact |

## Judgment

The live Luna planner shows a small exact-gold-agreement improvement under the current bounded planner prompt: 76.2% vs 71.4%. The only observed improvement is one abstention on `A3_RESERVED_UNSUITABLE`, where deterministic always chose planned maintenance review. Both arms failed `A5_REPLENISHMENT`, meaning the current planner/policy stack still treats future replenishment as enough for planned review instead of abstaining.

This is not strong enough to claim broad LLM superiority. The safe claim is narrower: with the Policy Guard, read-only DecisionSession structure, and current domain-specific ranking prompt in place, Luna can sometimes make a more cautious choice in ambiguous resource/window cases, but the benefit is small in this 7-case smoke and costs about 7 seconds plus roughly three API calls per run.

## Live durable storage check

A separate live PostgreSQL check was run against the already running local `ontology-standalone-page-pg` container on port 63542:

```sh
PATH=/opt/homebrew/opt/libpq/bin:$PATH TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=63542 TEST_POSTGRES_USER=postgres TEST_POSTGRES_PASSWORD=<local-test-password> PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_decision_durable_postgresql.py
```

Result: `2 passed`.

## Communication boundary

Safe interview claim:

> We built a seven-case exact gold set for ambiguous manufacturing decisions and compared deterministic planning with a live Luna planner. Both stayed inside Policy Guard with 100% required tool coverage and no forbidden-action recommendation. Under the current bounded planner prompt, Luna improved exact gold agreement from 71.4% to 76.2%, mainly by abstaining once in an ambiguous resource/window case, but it was slower and still missed the future-replenishment abstention case. So I would present LLM quality benefit as preliminary, while the stronger proven value remains the DecisionSession, evidence boundary, policy containment, and human review structure.

Do not claim:

- LLMs are generally better than deterministic rules.
- The result proves field KPI, downtime, cost, or operator time improvement.
- The fixture-backed gold set represents live factory distribution.

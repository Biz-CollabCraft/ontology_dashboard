# Decision record: policy-B response compatibility adapter

작성일: 2026-09-24  
근거: `docs/evidence/2026-09-24-readiness-response-compatibility.md`

## Human-authorized implementation scope

The user authorized continuing the recommended policy-B implementation direction. This slice adds a frontend compatibility adapter for retained legacy agent-review trace responses only.

## Implemented contract

- New explicit readiness fields remain the primary contract.
- During a response-shape compatibility window, `latest_stored=true` maps to disclosed historical availability and never to current readiness.
- A ready non-fallback legacy summary without the history marker maps to exact current readiness.
- Unclassifiable legacy traces fail closed to not-ready.

## Retained boundaries

- No change to exact snapshot identity, scope binding, historical fallback selection, mismatch publication guard, GET-without-generation, provider path, or persistent schema.
- No claim of deployed mixed-version compatibility or operational readiness.

## Human-owned completion fields

- **Final adoption / defer / reject:** pending human decision.
- **Interpretation of the focused evidence:** pending human decision.
- **Changed belief:** pending human decision.
- **Next decision:** decide whether the synthetic adapter evidence is sufficient for the intended compatibility window. A real rolling-deployment check, if needed, is a separate bounded experiment.

## Stop condition

The one adapter, its GET/POST fixtures, existing ViewModel regression test, and type check are complete. Stop here; provider, deploy, workload, multi-worker, and migration work remain outside this slice.

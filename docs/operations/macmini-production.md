# Mac mini production migration and rollback

The canonical production candidate is Vercel frontend → Cloudflare HTTPS → Mac
mini Backend → Mac mini PostgreSQL, with a private ephemeral Redis instance for
production rate limiting. The independent Generator publishes a
versioned Model Artifact that Backend consumes through `MODEL_ARTIFACT_URI`.
Generator and Backend never import one another's implementation or search a
sibling physical path.

Operational source data is supplied by `Biz-CollabCraft/gen_data` through its
canonical file/artifact contract. Generator persistent state, cache policy,
startup commands, backup scripts and the concrete Compose layout are documented
in `infra/macmini/README.md`.

During cutover, Render and Neon are rollback standby and are not deleted,
suspended, branched, truncated, or otherwise destructively modified. A failed
application cutover returns Vercel's same-origin `/api/*` rewrite to the Render
URL. A database rollback returns the application to the existing Render+Neon
pair; it does not expose Neon credentials to the Mac mini repository or publish
PostgreSQL port 5432.

Production validation must include all three backend health endpoints, database
migration/row-count comparison, artifact checksum validation, a real Generator
run, HTTPS through Cloudflare, and the browser MVP login → assets → report →
evidence flow. Only after those pass should the Mac mini be treated as primary;
retirement of Render/Neon is a separate change.

The public Backend hostname is `ontology-api.oosu.dev`. A nested hostname such
as `api.ontology.oosu.dev` would require a certificate covering
`*.ontology.oosu.dev`; the standard zone wildcard only covers one label below
`oosu.dev`.

The Generator's Canonical V3.1 compressor regression sanity check is intentionally
kept separate from deployment-realism evaluation. It uses per-asset baseline
normalization and temporal 1 h / 6 h features, while deployment realism uses a
per-asset chronological split. Candidate selection and threshold choice must not
optimize on the final test set. A newly published immutable artifact is promoted
to `current` only after the metric sanity gate passes; failed candidates remain
available for diagnosis but do not replace the Backend runtime artifact.

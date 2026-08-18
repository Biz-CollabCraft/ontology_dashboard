# Mac mini production migration and rollback

The canonical production path is Cloudflare HTTPS → Mac mini Frontend → Mac
mini Backend → Mac mini PostgreSQL, with a private ephemeral Redis instance for
production rate limiting. Vercel remains a CI/preview validation target rather
than the production origin. The independent Generator publishes versioned CNC
and compressor Model Artifacts that Backend consumes through injected artifact
URIs.
Generator and Backend never import one another's implementation or search a
sibling physical path.

Operational source data is supplied by `Biz-CollabCraft/gen_data` through its
canonical file/artifact contract. Generator persistent state, cache policy,
startup commands, backup scripts and the concrete Compose layout are documented
in `infra/macmini/README.md`.

During cutover, Vercel, Render and Neon are rollback/validation standbys and are
not deleted, suspended, branched, truncated, or otherwise destructively
modified. A failed frontend cutover returns the Cloudflare `ontology.oosu.dev`
catch-all ingress to the existing Vercel production origin. A full application
rollback can then use Vercel's Render rewrite, returning to Render+Neon without
publishing PostgreSQL port 5432.

Production validation must include all three backend health endpoints, database
migration/row-count comparison, artifact checksum validation, a real Generator
run, HTTPS through Cloudflare, and the browser MVP login → assets → report →
evidence flow. Only after those pass should the Mac mini be treated as primary;
retirement of Render/Neon is a separate change.

The public Backend hostname is `ontology-api.oosu.dev`. A nested hostname such
as `api.ontology.oosu.dev` would require a certificate covering
`*.ontology.oosu.dev`; the standard zone wildcard only covers one label below
`oosu.dev`.

The public product hostname is `ontology.oosu.dev`. Its Cloudflare Tunnel
catch-all points to the Mac mini frontend on `127.0.0.1:8120`; the frontend
nginx container proxies same-origin `/api/*` over the private Compose network to
Backend. No browser-visible Mac mini port is opened.

The Generator's Canonical V3.1 compressor regression sanity check is intentionally
kept separate from deployment-realism evaluation. It uses per-asset baseline
normalization and temporal 1 h / 6 h features, while deployment realism uses a
per-asset chronological split. Candidate selection and threshold choice must not
optimize on the final test set. A newly published immutable artifact is promoted
to `current` only after the metric sanity gate passes; failed candidates remain
available for diagnosis but do not replace the Backend runtime artifact.

Generator LLM enrichment is optional to the deterministic closed loop. The
client supports OpenAI or Google Vertex AI through `GENERATOR_LLM_PROVIDER`.
Mac mini production uses Vertex AI project `flai-oosuhada-20260506`, location
`global`, and `gemini-3.7-flash`. Its service-account credential stays in the
server-only secrets tree and is mounted read-only into the one-shot Generator
container through `GOOGLE_APPLICATION_CREDENTIALS`; it is never copied into the
image or repository. An API key can still be injected with `VERTEX_AI_API_KEY`
when that authentication mode is intentionally used.

The production sensor loop is distinct from weekly model training. The
`gen_data` daemon owns time-progressing source observations and persists its
checkpoint/output under the Mac mini data root. `live-ingestor` is owned by
`ontology_dashboard`: in the normal path it accepts complete source ticks,
writes them to the separate `gen-data-live-v1` Dataset Version, invokes the
promoted CNC and compressor Model Artifacts, and refreshes Product Result
Artifacts. The source clock is a configurable simulation clock; the production
demo currently runs it faster than wall clock, so timestamps are virtual-time
observations rather than a claim of physical real-time acquisition.

Closed-loop maintenance uses a separate additive Runtime Overlay path. A target
equipment branch is never merged back into Canonical source rows. `gen_data`
persists append-only `maintenance_replay_overlay` observations and checkpoints a
pending `runtime_overlay.observations.available` notification before advancing
its durable branch state. The availability outbox is idempotent by `event_id`
and is replayed on daemon restart, closing the observation-persisted / event-not-
yet-persisted crash window. Backend stores those rows in dedicated Runtime
Overlay tables, excludes active target equipment from the normal live inference
selection, evaluates Model Artifact history requirements against branch-only
post-maintenance history, and creates the post-maintenance prediction only after
the required history is available. Pre-maintenance history is not mixed into the
post-maintenance temporal window.

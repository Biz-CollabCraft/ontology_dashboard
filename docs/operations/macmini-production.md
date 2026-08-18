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
Secrets stay server-side. For Vertex AI, prefer project-scoped credentials/ADC;
an API key can be injected with `VERTEX_AI_API_KEY` when that authentication
mode is intentionally used.

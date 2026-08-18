# Mac mini production stack

This stack runs Frontend, Backend, PostgreSQL and the batch Generator on the Mac
mini. Vercel remains available for CI/preview validation; Render and Neon remain
untouched rollback sources during the validation period.

## Services and boundary

- `postgres`: PostgreSQL 18 + pgvector on the private Compose network only. The
  host bind mount targets `/var/lib/postgresql` (the PostgreSQL 18+ image
  layout), not the pre-18 `/var/lib/postgresql/data` path.
- `redis`: private-network-only ephemeral Redis used by the Backend's
  distributed production rate limiter. It exposes no host port and contains no
  authoritative application data.
- `backend`: canonical `systems/backend`, published only to `127.0.0.1:8110` for
  Cloudflare Tunnel. It reads `/artifacts/.../current` read-only via
  `MODEL_ARTIFACT_URI`.
- `generator`: one-shot batch profile. It owns extraction, ontology mapping,
  feature/label processing and immutable Model Artifact publication. It is not a
  continuously spinning API server.
- `frontend`: canonical `systems/frontend` nginx runtime, published only to
  `127.0.0.1:8120`. It builds with an empty `VITE_API_BASE_URL`, so browser API
  requests remain same-origin and nginx proxies `/api/*` to Backend through the
  private Compose alias `api:8000`.
- Vercel is retained as CI/preview validation rather than the production origin.

The production `.env` is server-only, mode `0600`, and must never be committed.

## Persistent layout

`ONTOLOGY_DATA_ROOT` contains `postgres/`, `generator/{source,data_preprocessed,ontology,models_store,logs}`,
`artifacts/`, and `backups/{neon,postgres,generator}`. Generated feature caches
can be recreated. PostgreSQL dumps, immutable Model Artifacts, mapping metadata,
and the source snapshot metadata are backup-worthy.

## Startup / shutdown / logs

```sh
docker compose --env-file .env -f docker-compose.yml up -d postgres redis backend frontend
docker compose --env-file .env -f docker-compose.yml ps
docker compose --env-file .env -f docker-compose.yml logs -f frontend backend
docker compose --env-file .env -f docker-compose.yml stop frontend backend redis postgres
```

Do not publish port 5432. Cloudflare routes the product hostname only to the
frontend localhost port and may keep the dedicated Backend health/API hostname
on its backend localhost port. `restart: unless-stopped` makes the long-running
services return after OrbStack/host restart.

## Generator

The source contract is file/artifact based; there is no Python import from
`Biz-CollabCraft/gen_data`. Place or synchronize the pinned Canonical V3.1 CNC
and compressor telemetry/failure-truth files under `generator/source`. Both
trained families derive per-asset first-seven-day running baselines plus temporal
1 h / 6 h change and rolling statistics. Each immutable artifact embeds those
baseline statistics and a rolling-context contract so Backend can reproduce the
same 40 features from the current observation plus the preceding 35 ten-minute
observations without importing Generator or `gen_data` code.

```sh
./scripts/run-generator.sh
docker compose --env-file .env -f docker-compose.yml --profile generator run --rm generator llm-smoke
```

The complete run writes intermediate feature/label outputs to persistent
storage and publishes an immutable `model-artifact-v1.0`. `current` is an
operational alias only; the artifact version directories are never overwritten.
Promotion is blocked unless regression-sanity average precision is above label
prevalence and both regression/deployment evaluations detect positive rows.
Threshold selection is validation-only rather than a fixed 0.5 or test-set
optimization. Default tree-model parallelism is two workers. Weekly Sunday
03:15 local time is the provided retraining schedule, intentionally not every
sensor event.

On the 16 GiB / 8-core Mac mini, Compose caps PostgreSQL at 1.5 CPU / 2 GiB,
Redis at 0.25 CPU / 128 MiB, Backend at 2 CPU / 2 GiB, and Generator at 2 CPU /
4 GiB. Frontend is capped at 0.5 CPU / 256 MiB, so the stack cannot consume the
whole host alongside existing services.

### Optional Generator LLM provider

The ML path does not require an LLM. Extraction profiling and ontology mapping
can use an LLM and safely fall back to deterministic rules when credentials are
absent. Supported providers are:

- `GENERATOR_LLM_PROVIDER=openai` with `OPENAI_API_KEY`.
- `GENERATOR_LLM_PROVIDER=vertex_ai` with Google Vertex AI. Mac mini production
  uses project `flai-oosuhada-20260506`, location `global`, and
  `gemini-3.7-flash`. The server-side service-account JSON is mounted read-only
  through `GENERATOR_GOOGLE_APPLICATION_CREDENTIALS_HOST` and exposed inside
  the Generator container only as `GOOGLE_APPLICATION_CREDENTIALS`. A supported
  `VERTEX_AI_API_KEY` remains available as an alternative, but is not the
  production credential path.

Do not commit either provider's credential. The production service account is
expected to have only the Vertex AI runtime role needed by Generator.

The standalone image declares dependencies from the current Generator import
graph. Legacy `lightgbm`/`xgboost` declarations are intentionally not installed
because the merged canonical runtime does not import them; the production model
uses scikit-learn RandomForest with bounded worker count.

## PostgreSQL migration, backup, restore

Neon is dumped in PostgreSQL custom format with `--no-owner --no-acl`, retained
under `backups/neon`, then restored into the local PostgreSQL 18 service. Verify
schema migrations, row counts, indexes, foreign keys, representative queries,
and Backend API responses before cutover.

Daily local dumps use `scripts/postgres-backup.sh` and keep seven daily copies
plus four Sunday weekly snapshots.
Run `scripts/postgres-restore-test.sh <dump>` to restore into a temporary DB and
prove the dump is usable. `scripts/install-backup-schedules.sh` installs the
02:30 daily PostgreSQL backup and Sunday 04:30 Generator/artifact backup as
macOS LaunchAgents. `generator-backup.sh` stores immutable artifacts and mapping/
plan metadata while intentionally excluding reproducible feature matrices.

## Cloudflare production and Vercel CI/preview

Reuse the existing named Mac mini tunnel. The canonical production routes are:

```yaml
- hostname: ontology-api.oosu.dev
  service: http://127.0.0.1:8110
- hostname: ontology.oosu.dev
  service: http://127.0.0.1:8120
```

Validate the tunnel configuration before restarting it. Never commit tunnel
credentials. The single-label `ontology-api.oosu.dev` hostname is used because
the zone's standard `*.oosu.dev` certificate does not cover a two-label hostname
such as `api.ontology.oosu.dev`. The Mac mini frontend keeps browser requests
same-origin and proxies `/api/*` privately. Vercel may still rewrite `/api/*` to
`https://ontology-api.oosu.dev/api/*` for preview/CI deployments, but it is not
the canonical production origin.

## Rollback

Frontend rollback: return the Cloudflare `ontology.oosu.dev` catch-all to the
existing Vercel production origin. Full application rollback can then use the
previous Vercel `/api/*` destination to Render. Render remains available until
a separate retirement decision.

Database rollback: restore the previous Render configuration (whose
`ONTOLOGY_DASHBOARD_DATABASE_URL` still points to Neon) rather than repointing
the Mac mini Backend across the public internet. Neon remains unchanged and is
the authoritative pre-cutover fallback snapshot until the retention decision.

## Secret handling

`POSTGRES_PASSWORD`, Neon URLs, `OPENAI_API_KEY`, `VERTEX_AI_API_KEY`, Render/Vercel/Cloudflare
credentials, and session/JWT secrets are never repository values. Store them in
the Mac mini `.env`/existing platform secret stores only, with permission 0600.

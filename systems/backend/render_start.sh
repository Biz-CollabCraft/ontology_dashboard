#!/bin/sh
set -eu

python -m ontology_dashboard.bootstrap

# Only the hosted demo auto-materializes the pinned Canonical V3.1 source
# snapshot. Non-demo environments retain their explicit ingestion lifecycle.
if [ "${APP_ENV:-}" = "demo" ]; then
  python -m ontology_dashboard.demo_predictive_maintenance_bootstrap
fi

exec python -m uvicorn ontology_dashboard.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --no-server-header

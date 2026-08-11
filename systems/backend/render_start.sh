#!/bin/sh
set -eu

python -m ontology_dashboard.bootstrap
exec python -m uvicorn ontology_dashboard.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-10000}" \
  --no-server-header

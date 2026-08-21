"""Mac mini live predictive-maintenance worker entrypoint.

All prediction, persistence, and ontology-materialization behavior is owned by
the injected application/runtime services.  This module only resolves worker
configuration, invokes one application use case, and controls polling.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from app.dependencies import build_live_predictive_maintenance_service


LOGGER = logging.getLogger(__name__)
DEFAULT_STREAM_ROOT = Path("/gen-data-runtime")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    stream_root = Path(
        os.getenv("GEN_DATA_RUNTIME_OUTPUT_ROOT", str(DEFAULT_STREAM_ROOT))
    )
    poll_seconds = max(1.0, float(os.getenv("LIVE_PM_POLL_SECONDS", "5")))
    once = os.getenv("LIVE_PM_RUN_ONCE", "0").lower() in {"1", "true", "yes"}
    service = build_live_predictive_maintenance_service()

    while True:
        try:
            payload = service.ingest_once(stream_root=stream_root)
            LOGGER.info(
                "live predictive-maintenance ingest: %s",
                json.dumps(payload, default=str),
            )
        except Exception:
            LOGGER.exception("live predictive-maintenance ingest failed")
            if once:
                raise
        if once:
            break
        time.sleep(poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Materialize Agent Review Summaries from Product Result/Evidence snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def configure_imports(root: Path) -> None:
    for relative in ("systems/backend", "packages/backend", "packages/ml_core"):
        path = str(root / relative)
        if path not in sys.path:
            sys.path.insert(0, path)


def resolve_database(root: Path, value: str | None) -> str:
    configured = (
        value
        or os.getenv("ONTOLOGY_DASHBOARD_DB")
        or os.getenv("FACTORY_SIGNAL_DB")
        or "data/local/ontology_dashboard.db"
    )
    if configured.startswith(("postgresql://", "postgresql+psycopg://")):
        return configured
    path = Path(configured).expanduser()
    return str(path if path.is_absolute() else root / path)


def run_once(
    *,
    root: Path,
    database: str,
    project_id: str,
    history_window: str,
    limit: int | None,
) -> dict:
    configure_imports(root)
    from app.dependencies import build_manufacturing_service

    service = build_manufacturing_service(database, root=root)
    result = service.materialize_agent_review_summaries(
        project_id,
        history_window=history_window,
        limit=limit,
    )
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": database,
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize read-only Agent Review Summaries. Run once by default; "
            "use --watch to poll for new snapshot/version keys."
        )
    )
    parser.add_argument("--database", help="SQLite path or PostgreSQL URL.")
    parser.add_argument("--project-id", default="manufacturing-demo-project")
    parser.add_argument(
        "--history-window",
        choices=("24h", "7d", "30d"),
        default="24h",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-iterations", type=int)
    args = parser.parse_args()

    root = project_root()
    database = resolve_database(root, args.database)
    iteration = 0
    while True:
        iteration += 1
        result = run_once(
            root=root,
            database=database,
            project_id=args.project_id,
            history_window=args.history_window,
            limit=args.limit,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not args.watch:
            return
        if args.max_iterations is not None and iteration >= args.max_iterations:
            return
        time.sleep(max(1.0, args.interval_seconds))


if __name__ == "__main__":
    main()

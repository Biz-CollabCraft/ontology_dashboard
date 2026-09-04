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
    database: str,
    service,
    project_id: str,
    history_window: str,
    limit: int | None,
    max_attempts: int,
    watch: bool,
    interval_seconds: float,
    max_iterations: int | None,
    stale_policy: str,
    source: str,
    require_live_provider: bool,
) -> dict:
    from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow

    result = AgentReviewSummaryWorkflow(service).run(
        project_id,
        history_window=history_window,
        limit=limit,
        trigger="polling_watcher",
        max_attempts=max_attempts,
        source=source,
        operating_mode={
            "mode": "watch" if watch else "once",
            "target_scope": "project",
            "poll_interval_seconds": interval_seconds if watch else None,
            "max_iterations": max_iterations,
            "stale_detection": stale_policy,
            "summary_duplicate_policy": "reuse_existing_summary",
            "run_record_policy": "record_each_explicit_trigger",
            "stop_behavior": (
                "bounded_iterations_or_signal" if watch else "return_after_run"
            ),
        },
    )
    if require_live_provider:
        result["live_provider_required"] = True
        result["live_provider_ready"] = _live_provider_ready(result)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": database,
        **result,
    }


def _live_provider_ready(result: dict) -> bool:
    items = result.get("items") or []
    return bool(items) and all(
        item.get("status") == "ready"
        and item.get("mode") == "llm"
        and not item.get("fallback_reason")
        for item in items
    )


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
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--source",
        choices=("fixture", "live", "auto", "post-maintenance"),
        default="fixture",
        help=(
            "Candidate source. fixture preserves local regression behavior; "
            "live/post-maintenance read Product Result artifacts from the DB; "
            "auto uses live candidates when available."
        ),
    )
    parser.add_argument(
        "--require-live-provider",
        action="store_true",
        help="Exit non-zero if any materialized item used deterministic fallback.",
    )
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument(
        "--stale-policy",
        choices=("summary_key",),
        default="summary_key",
        help=(
            "How the watcher decides whether a summary is fresh. summary_key "
            "uses source/context/model/prompt/schema checksums."
        ),
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive when provided")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.max_iterations is not None and args.max_iterations < 1:
        parser.error("--max-iterations must be positive when provided")

    root = project_root()
    configure_imports(root)
    from app.dependencies import build_manufacturing_service

    database = resolve_database(root, args.database)
    service = build_manufacturing_service(database, root=root)
    iteration = 0
    while True:
        iteration += 1
        result = run_once(
            database=database,
            service=service,
            project_id=args.project_id,
            history_window=args.history_window,
            limit=args.limit,
            max_attempts=args.max_attempts,
            watch=args.watch,
            interval_seconds=args.interval_seconds,
            max_iterations=args.max_iterations,
            stale_policy=args.stale_policy,
            source=args.source,
            require_live_provider=args.require_live_provider,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if args.require_live_provider and not result.get("live_provider_ready"):
            raise SystemExit(2)
        if not args.watch:
            return
        if args.max_iterations is not None and iteration >= args.max_iterations:
            return
        time.sleep(max(1.0, args.interval_seconds))


if __name__ == "__main__":
    main()

"""Reset only the repository-owned local Docker PostgreSQL demo database.

This command deliberately operates through the ``postgres`` service declared in
``infra/docker-compose.yml``.  It cannot accept a database URL, so it cannot be
redirected to the Team DB, a Tailscale host, or another PostgreSQL instance.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "docker-compose.yml"
DATABASE_NAME = "ontology_dashboard"
DATABASE_OWNER = "ontology"
CONFIRMATION = f"RESET {DATABASE_NAME}"


def _compose(
    *arguments: str,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "--profile",
            "polyglot",
            *arguments,
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _require_running_project_postgres() -> None:
    result = _compose(
        "ps",
        "--status",
        "running",
        "-q",
        "postgres",
        capture_output=True,
    )
    if not result.stdout.strip():
        raise RuntimeError(
            "the ontology-dashboard Docker PostgreSQL service is not running; "
            "start it before resetting"
        )


def _reset_database() -> None:
    terminate_sql = (
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        f"WHERE datname = '{DATABASE_NAME}' AND pid <> pg_backend_pid();"
    )
    _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        DATABASE_OWNER,
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        terminate_sql,
        "-c",
        f'DROP DATABASE IF EXISTS "{DATABASE_NAME}";',
        "-c",
        f'CREATE DATABASE "{DATABASE_NAME}" OWNER "{DATABASE_OWNER}";',
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help=f"Skip the interactive '{CONFIRMATION}' confirmation.",
    )
    args = parser.parse_args()

    print("Local real-time demo database reset")
    print(f"  Compose:  {COMPOSE_FILE}")
    print(f"  Service:  postgres")
    print(f"  Database: {DATABASE_NAME}")
    print("  Remote database URLs are not accepted by this command.")
    print("  Stop the integrated runner with Ctrl+C before continuing.\n")

    if not args.yes:
        entered = input(f"Type '{CONFIRMATION}' to continue: ").strip()
        if entered != CONFIRMATION:
            print("Reset cancelled; no data was changed.")
            return 2

    try:
        _require_running_project_postgres()
        _reset_database()
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\nReset failed: {exc}")
        return 1
    print("\nReset complete. The database is empty.")
    print("Run START_LOCAL_REALTIME_DEMO.cmd to apply migrations, seed demo accounts,")
    print("bootstrap the canonical package, and create a fresh 1008-tick live history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_review_summary_watcher_cli_reports_workflow_contract(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "APP_ENV": "test",
        "ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK": "1",
        "PYTHONPATH": "systems/backend:packages/backend:packages/ml_core",
    }

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/watch_agent_review_summaries.py",
            "--database",
            str(tmp_path / "watcher.db"),
            "--limit",
            "1",
            "--max-attempts",
            "1",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)

    assert payload["flow_version"] == "agent-review-summary-flow-v1.0"
    assert payload["trigger"] == "polling_watcher"
    assert payload["read_only"] is True
    assert payload["mutation_allowed"] is False
    assert payload["workflow"]["engine"] == "simple"
    assert payload["workflow"]["max_attempts"] == 1
    assert payload["workflow"]["attempt_count"] == 1
    assert payload["workflow"]["terminal_status"] == "completed"
    assert payload["workflow"]["attempts"] == [{"attempt": 1, "status": "succeeded"}]
    assert payload["materialized_count"] == 1

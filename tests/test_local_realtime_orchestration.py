import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import scripts.run_local_realtime as local_realtime
from scripts.run_local_realtime import (
    LIVE_SOURCE_VERSION,
    _bootstrap_database,
    _fast_forward_initial_history,
    _initial_fast_forward_target_hours,
    _latest_live_observed_at,
    _simulation_start_at,
)


def test_simulation_continues_exactly_one_cadence_after_persisted_cursor() -> None:
    latest = datetime(2026, 9, 2, 3, 41, 5, tzinfo=timezone.utc)

    assert _simulation_start_at(
        now=datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc),
        latest_observed_at=latest,
    ) == latest + timedelta(minutes=10)


def test_first_simulation_run_provides_six_hours_of_warmup() -> None:
    now = datetime(2026, 9, 2, 4, 0, tzinfo=timezone.utc)

    assert _simulation_start_at(now=now, latest_observed_at=None) == now - timedelta(
        hours=6
    )


def test_first_live_run_fast_forwards_exactly_36_ten_minute_ticks() -> None:
    assert _initial_fast_forward_target_hours(latest_observed_at=None) == 6


def test_resumed_live_run_does_not_repeat_initial_fast_forward() -> None:
    latest = datetime(2026, 9, 2, 3, 41, 5, tzinfo=timezone.utc)

    assert _initial_fast_forward_target_hours(latest_observed_at=latest) is None


def test_initial_fast_forward_keeps_the_original_run(monkeypatch) -> None:
    calls = []

    def post_json(url, payload):
        calls.append((url, payload))
        return {"run_id": "original-run", "generated_records": 3600}

    monkeypatch.setattr(local_realtime, "_post_json", post_json)

    result = _fast_forward_initial_history(
        gen_data_port=8300,
        run_id="original-run",
        latest_observed_at=None,
    )

    assert result == {"run_id": "original-run", "generated_records": 3600}
    assert calls == [
        (
            "http://127.0.0.1:8300/api/runs/original-run/simulation/fast-forward",
            {"target_elapsed_hours": 6},
        )
    ]


def test_live_cursor_query_excludes_canonical_dataset_versions(monkeypatch) -> None:
    expected = datetime(2026, 9, 2, 3, 41, 5, tzinfo=timezone.utc)

    class Result:
        def fetchone(self):
            return (expected,)

    class Connection:
        def __init__(self):
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params=None):
            self.executed.append((statement, params))
            if "SELECT MAX(live_observation.observed_at)" in statement:
                return Result()
            return self

    connection = Connection()
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda _database_url: connection),
    )

    assert _latest_live_observed_at("postgresql://local/demo") == expected
    query, params = connection.executed[-1]
    assert query.count("version.source_version=%s") == 2
    assert params.count(LIVE_SOURCE_VERSION) == 2


def test_database_bootstrap_migrates_and_seeds_before_package_ingestion(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        local_realtime,
        "_wait_database",
        lambda database_url: calls.append(("wait", database_url)),
    )

    def run(command, *, cwd, env, check):
        calls.append(("run", command, cwd, env, check))

    monkeypatch.setattr(local_realtime.subprocess, "run", run)

    _bootstrap_database(
        python="python",
        database_url="postgresql://local/demo",
        base_env={"APP_ENV": "local"},
    )

    assert calls[0] == ("wait", "postgresql://local/demo")
    assert calls[1][1] == ["python", "-m", "app.migrate"]
    assert calls[2][1][0:2] == ["python", "-c"]
    assert "get_identity_service" in calls[2][1][2]
    assert calls[1][2] == local_realtime.ROOT / "systems" / "backend"
    assert calls[2][2] == local_realtime.ROOT / "systems" / "backend"

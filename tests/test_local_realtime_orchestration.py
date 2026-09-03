from datetime import datetime, timedelta, timezone

from scripts.run_local_realtime import _simulation_start_at


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

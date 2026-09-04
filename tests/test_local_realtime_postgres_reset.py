from __future__ import annotations

from unittest.mock import Mock

import scripts.reset_local_realtime_postgres as reset


def test_reset_command_is_bound_to_repository_postgres_service(monkeypatch) -> None:
    run = Mock(
        side_effect=[
            Mock(stdout="container-id\n"),
            Mock(stdout=""),
        ]
    )
    monkeypatch.setattr(reset.subprocess, "run", run)

    reset._require_running_project_postgres()
    reset._reset_database()

    ps_command = run.call_args_list[1].args[0]
    assert ps_command[:6] == [
        "docker",
        "compose",
        "-f",
        str(reset.COMPOSE_FILE),
        "--profile",
        "polyglot",
    ]
    assert "postgres" in ps_command
    assert "ontology_dashboard" in " ".join(ps_command)
    assert not any("tail" in argument.lower() for argument in ps_command)


def test_reset_refuses_when_project_postgres_is_not_running(monkeypatch) -> None:
    monkeypatch.setattr(
        reset.subprocess,
        "run",
        Mock(return_value=Mock(stdout="")),
    )

    try:
        reset._require_running_project_postgres()
    except RuntimeError as exc:
        assert "not running" in str(exc)
    else:
        raise AssertionError("reset must refuse a missing project PostgreSQL service")

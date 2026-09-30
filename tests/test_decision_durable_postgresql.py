"""Actual PostgreSQL transaction/lease and hard-process recovery checks."""
from tests.test_predictive_maintenance_postgresql import postgresql_database
from tests.test_decision_durable_runner import assert_hard_crash_recovery, test_claim_scope_busy_expiry_and_old_writer_fencing as check_fencing
from app.infra.db.decision_run_repository import DecisionRunRepository


def test_postgresql_process_kill_and_resume(postgresql_database,tmp_path):
    assert_hard_crash_recovery(DecisionRunRepository(postgresql_database,lease_seconds=.3),tmp_path)


def test_postgresql_fenced_lease(postgresql_database):
    check_fencing(DecisionRunRepository(postgresql_database,lease_seconds=.3))

from app.operations.decision_retry import DecisionRetryPolicy, RetryFailureKind


def test_transient_failures_retry_with_budget_and_bounded_attempts() -> None:
    policy = DecisionRetryPolicy()
    assert policy.may_retry(RetryFailureKind.TIMEOUT, attempt=1, retry_budget_remaining=1)
    assert not policy.may_retry(RetryFailureKind.TIMEOUT, attempt=2, retry_budget_remaining=1)
    assert not policy.may_retry(RetryFailureKind.TIMEOUT, attempt=1, retry_budget_remaining=0)


def test_stale_snapshot_requires_new_session_not_retry() -> None:
    directive = DecisionRetryPolicy().directive(RetryFailureKind.STALE_SNAPSHOT)
    assert directive.retry is False
    assert directive.requires_new_session is True
    assert directive.terminal_action == "mark_session_stale"


def test_conflict_is_surfaced_instead_of_retried() -> None:
    directive = DecisionRetryPolicy().directive(RetryFailureKind.CONFLICTING_EVIDENCE)
    assert directive.retry is False
    assert directive.terminal_action == "surface_conflict_for_human_review"


def test_schema_and_parse_failures_do_not_repeat_same_bad_source() -> None:
    policy = DecisionRetryPolicy()
    for kind in (RetryFailureKind.SCHEMA_VALIDATION, RetryFailureKind.PARSE):
        assert not policy.may_retry(kind, attempt=1, retry_budget_remaining=5)
        assert policy.directive(kind).consume_budget == 0


def test_backoff_is_exponential_and_jitter_is_bounded() -> None:
    policy = DecisionRetryPolicy()
    first = policy.delay_seconds(RetryFailureKind.SERVER_5XX, 1, seed=7)
    second = policy.delay_seconds(RetryFailureKind.SERVER_5XX, 2, seed=7)
    assert 0.5 <= first <= 1.0
    assert 1.0 <= second <= 1.5
    assert second > first

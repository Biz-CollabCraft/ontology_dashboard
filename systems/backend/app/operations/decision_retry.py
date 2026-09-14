"""Retry classification and budget policy for decision-agent read-only tools."""

from __future__ import annotations

import random
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RetryFailureKind(StrEnum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    SERVER_5XX = "server_5xx"
    RATE_LIMIT = "rate_limit"
    SCHEMA_VALIDATION = "schema_validation"
    PARSE = "parse"
    STALE_SNAPSHOT = "stale_snapshot"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    REPEATED_FAILURE = "repeated_failure"
    NON_RETRYABLE = "non_retryable"


class RetryDirective(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retry: bool
    max_attempts: int = Field(ge=1, le=8)
    consume_budget: int = Field(ge=0, le=8)
    base_delay_seconds: float = Field(ge=0, le=60)
    jitter_seconds: float = Field(ge=0, le=30)
    requires_new_session: bool = False
    terminal_action: str


class DecisionRetryPolicy:
    policy_version = "manufacturing-decision-retry-v1"

    _DIRECTIVES = {
        RetryFailureKind.TIMEOUT: RetryDirective(
            retry=True, max_attempts=2, consume_budget=1, base_delay_seconds=0.25,
            jitter_seconds=0.25, terminal_action="abstain_with_gap",
        ),
        RetryFailureKind.NETWORK: RetryDirective(
            retry=True, max_attempts=2, consume_budget=1, base_delay_seconds=0.25,
            jitter_seconds=0.25, terminal_action="abstain_with_gap",
        ),
        RetryFailureKind.SERVER_5XX: RetryDirective(
            retry=True, max_attempts=2, consume_budget=1, base_delay_seconds=0.5,
            jitter_seconds=0.5, terminal_action="abstain_with_gap",
        ),
        RetryFailureKind.RATE_LIMIT: RetryDirective(
            retry=True, max_attempts=2, consume_budget=1, base_delay_seconds=1.0,
            jitter_seconds=0.5, terminal_action="abstain_with_gap",
        ),
        RetryFailureKind.SCHEMA_VALIDATION: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, terminal_action="record_invalid_source_and_abstain",
        ),
        RetryFailureKind.PARSE: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, terminal_action="record_invalid_source_and_abstain",
        ),
        RetryFailureKind.STALE_SNAPSHOT: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, requires_new_session=True,
            terminal_action="mark_session_stale",
        ),
        RetryFailureKind.CONFLICTING_EVIDENCE: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, terminal_action="surface_conflict_for_human_review",
        ),
        RetryFailureKind.REPEATED_FAILURE: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, terminal_action="abstain_retry_budget_exhausted",
        ),
        RetryFailureKind.NON_RETRYABLE: RetryDirective(
            retry=False, max_attempts=1, consume_budget=0, base_delay_seconds=0,
            jitter_seconds=0, terminal_action="abstain_with_gap",
        ),
    }

    def directive(self, failure_kind: RetryFailureKind) -> RetryDirective:
        return self._DIRECTIVES[failure_kind]

    def delay_seconds(self, failure_kind: RetryFailureKind, attempt: int, *, seed: int | None = None) -> float:
        directive = self.directive(failure_kind)
        if not directive.retry:
            return 0.0
        exponent = max(0, attempt - 1)
        base = directive.base_delay_seconds * (2 ** exponent)
        rng = random.Random(seed)
        return base + rng.uniform(0, directive.jitter_seconds)

    def may_retry(
        self,
        failure_kind: RetryFailureKind,
        *,
        attempt: int,
        retry_budget_remaining: int,
    ) -> bool:
        directive = self.directive(failure_kind)
        return (
            directive.retry
            and attempt < directive.max_attempts
            and retry_budget_remaining >= directive.consume_budget
        )

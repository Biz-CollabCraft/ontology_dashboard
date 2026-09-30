from datetime import datetime, timezone

import pytest

from app.operations.decision_policy import DecisionPolicyFacts, DecisionPolicyGuard
from app.operations.decision_support_contract import (
    DecisionAction,
    DecisionConfidence,
    DecisionProposal,
    DecisionSession,
    DecisionSessionStatus,
)
from app.operations.operational_context_contract import OperationalRequestIdentity


NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-S04-L04-01",
    evidence_snapshot_id="SNAP-001",
    decision_as_of=NOW,
)


def proposal(action: DecisionAction | None, *, alternatives=(), abstain_reason=None):
    return DecisionProposal(
        recommended_action=action,
        alternative_actions=alternatives,
        confidence=DecisionConfidence.MEDIUM,
        reasoning_summary="근거를 비교해 다음 판단 후보를 정리했습니다.",
        abstain_reason=abstain_reason,
    )


def test_data_quality_hold_keeps_only_non_mutating_diagnostic_decisions() -> None:
    result = DecisionPolicyGuard().evaluate(
        DecisionPolicyFacts(data_quality_hold=True, risk_status="data_quality_hold")
    )
    assert result.allowed_actions == (
        DecisionAction.MONITOR,
        DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS,
    )
    assert "DATA_QUALITY_HOLD" in result.blocked_reasons[DecisionAction.REQUEST_MAINTENANCE]


def test_preinspection_state_allows_monitor_diagnosis_or_inspection_only() -> None:
    result = DecisionPolicyGuard().evaluate(
        DecisionPolicyFacts(risk_status="warning")
    )
    assert result.allowed_actions == (
        DecisionAction.MONITOR,
        DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS,
        DecisionAction.REQUEST_INSPECTION,
    )


def test_maintenance_recommended_state_allows_immediate_or_planned_maintenance() -> None:
    result = DecisionPolicyGuard().evaluate(
        DecisionPolicyFacts(
            inspection_result_available=True,
            maintenance_recommended=True,
            production_impact_known=True,
            maintenance_window_known=True,
            resource_readiness_known=True,
            risk_status="warning",
        )
    )
    assert result.allowed_actions == (
        DecisionAction.REQUEST_MAINTENANCE,
        DecisionAction.REVIEW_PLANNED_MAINTENANCE,
    )


def test_snapshot_mismatch_blocks_every_recommendation() -> None:
    result = DecisionPolicyGuard().evaluate(
        DecisionPolicyFacts(snapshot_valid=False, risk_status="warning")
    )
    assert result.allowed_actions == ()
    assert result.recommendation_blocked is True
    assert all("SNAPSHOT_MISMATCH" in reasons for reasons in result.blocked_reasons.values())


def test_duplicate_request_blocks_duplicate_create_actions() -> None:
    result = DecisionPolicyGuard().evaluate(
        DecisionPolicyFacts(active_duplicate_request=True, risk_status="warning")
    )
    assert DecisionAction.REQUEST_INSPECTION not in result.allowed_actions
    assert DecisionAction.MONITOR in result.allowed_actions


def test_session_rejects_agent_action_outside_policy_allowlist() -> None:
    with pytest.raises(ValueError, match="proposal action must be allowed"):
        DecisionSession(
            decision_session_id="DS-001",
            identity=IDENTITY,
            actor_role="process_manager",
            status=DecisionSessionStatus.READY_FOR_REVIEW,
            allowed_actions=(DecisionAction.REQUEST_INSPECTION,),
            proposal=proposal(DecisionAction.REQUEST_MAINTENANCE),
            created_at=NOW,
            updated_at=NOW,
            retry_budget_remaining=3,
        )


def test_abstaining_session_requires_no_recommended_action() -> None:
    session = DecisionSession(
        decision_session_id="DS-002",
        identity=IDENTITY,
        actor_role="process_manager",
        status=DecisionSessionStatus.ABSTAINED,
        allowed_actions=(DecisionAction.REQUEST_INSPECTION,),
        proposal=proposal(None, abstain_reason="필요한 점검 근거를 확보하지 못했습니다."),
        created_at=NOW,
        updated_at=NOW,
        retry_budget_remaining=0,
    )
    assert session.proposal is not None
    assert session.proposal.recommended_action is None


def test_decision_session_forbids_mutation_attempts() -> None:
    with pytest.raises(ValueError, match="must remain read-only"):
        DecisionSession(
            decision_session_id="DS-003",
            identity=IDENTITY,
            actor_role="process_manager",
            status=DecisionSessionStatus.CREATED,
            created_at=NOW,
            updated_at=NOW,
            retry_budget_remaining=3,
            mutation_attempted=True,
        )

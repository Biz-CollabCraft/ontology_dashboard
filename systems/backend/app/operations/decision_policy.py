"""Deterministic policy guard for manufacturing decision recommendations."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.operations.decision_support_contract import DecisionAction


class DecisionPolicyFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_quality_hold: bool = False
    snapshot_valid: bool = True
    inspection_result_available: bool = False
    maintenance_recommended: bool = False
    active_duplicate_request: bool = False
    maintenance_window_known: bool = False
    resource_readiness_known: bool = False
    production_impact_known: bool = False
    risk_status: str | None = Field(default=None, max_length=80)


class DecisionPolicyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = "manufacturing-decision-policy-v1"
    allowed_actions: tuple[DecisionAction, ...]
    blocked_reasons: dict[DecisionAction, tuple[str, ...]]
    recommendation_blocked: bool = False


def decision_policy_facts_from_packet(packet: dict) -> DecisionPolicyFacts:
    """Derive policy facts from the trusted, event-scoped review packet."""
    from app.operations.agent_briefing_review import decision_facts

    scoped = decision_facts(packet)
    inspections = scoped.get("inspection_results") or []
    work_orders = scoped.get("work_orders") or []
    latest_inspection = inspections[-1] if inspections else None
    outcome = str((latest_inspection or {}).get("outcome") or "")
    active_duplicate = any(
        str(order.get("status") or "") not in {"completed", "cancelled"}
        for order in work_orders
    )
    risk = packet.get("risk_summary") or {}
    risk_status = risk.get("status_grade")
    operation = packet.get("operation_context_summary") or {}
    data_quality_hold = (
        str((packet.get("review_draft") or {}).get("priority_label") or "") == "미확정"
        or str(risk_status or "") == "data_quality_hold"
        or risk_status is None
    )
    return DecisionPolicyFacts(
        data_quality_hold=data_quality_hold,
        snapshot_valid=True,
        inspection_result_available=latest_inspection is not None,
        maintenance_recommended=outcome == "maintenance_recommended",
        active_duplicate_request=active_duplicate,
        production_impact_known=(
            operation.get("estimated_downtime_minutes") is not None
            or operation.get("estimated_lost_units") is not None
        ),
        risk_status=str(risk_status) if risk_status is not None else None,
    )


class DecisionPolicyGuard:
    """Owns action eligibility; the agent may only rank this allowed set."""

    policy_version = "manufacturing-decision-policy-v1"

    def evaluate(self, facts: DecisionPolicyFacts) -> DecisionPolicyResult:
        blocked: dict[DecisionAction, list[str]] = {action: [] for action in DecisionAction}

        if not facts.snapshot_valid:
            for action in DecisionAction:
                blocked[action].append("SNAPSHOT_MISMATCH")
            return self._result(blocked, recommendation_blocked=True)

        if facts.data_quality_hold:
            blocked[DecisionAction.REQUEST_INSPECTION].append("DATA_QUALITY_HOLD")
            blocked[DecisionAction.REQUEST_MAINTENANCE].append("DATA_QUALITY_HOLD")
            blocked[DecisionAction.REVIEW_PLANNED_MAINTENANCE].append("DATA_QUALITY_HOLD")
        elif not facts.inspection_result_available:
            blocked[DecisionAction.REQUEST_MAINTENANCE].append("INSPECTION_RESULT_REQUIRED")
            blocked[DecisionAction.REVIEW_PLANNED_MAINTENANCE].append("INSPECTION_RESULT_REQUIRED")
        elif not facts.maintenance_recommended:
            blocked[DecisionAction.REQUEST_MAINTENANCE].append("MAINTENANCE_NOT_RECOMMENDED")
            blocked[DecisionAction.REVIEW_PLANNED_MAINTENANCE].append("MAINTENANCE_NOT_RECOMMENDED")

        if facts.active_duplicate_request:
            blocked[DecisionAction.REQUEST_INSPECTION].append("DUPLICATE_ACTIVE_REQUEST")
            blocked[DecisionAction.REQUEST_MAINTENANCE].append("DUPLICATE_ACTIVE_REQUEST")

        if facts.maintenance_recommended:
            blocked[DecisionAction.MONITOR].append("MAINTENANCE_RECOMMENDED")
            blocked[DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS].append("MAINTENANCE_RECOMMENDED")
            blocked[DecisionAction.REQUEST_INSPECTION].append("INSPECTION_ALREADY_RESOLVED")

        return self._result(blocked, recommendation_blocked=False)

    def _result(
        self,
        blocked: dict[DecisionAction, list[str]],
        *,
        recommendation_blocked: bool,
    ) -> DecisionPolicyResult:
        allowed = tuple(action for action in DecisionAction if not blocked[action])
        return DecisionPolicyResult(
            policy_version=self.policy_version,
            allowed_actions=allowed,
            blocked_reasons={action: tuple(reasons) for action, reasons in blocked.items() if reasons},
            recommendation_blocked=recommendation_blocked,
        )

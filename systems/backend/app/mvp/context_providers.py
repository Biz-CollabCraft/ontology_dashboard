"""Read-only context provider contracts for Agent Review Packet composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentReviewContext:
    """Adapter-supplied context that can be safely merged into a review packet."""

    operation_context_summary: dict[str, Any] | None = None
    evidence_gaps: list[dict[str, str]] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


class AgentReviewContextProvider(Protocol):
    """Port implemented by domain adapters that contribute AI review context."""

    def context_for_packet(self, *, view_model: dict[str, Any]) -> AgentReviewContext:
        """Return source-ref grounded context without mutating domain state."""


class OperationContextProvider:
    """Build the current operating context section from AssetDetailViewModel data."""

    def context_for_packet(self, *, view_model: dict[str, Any]) -> AgentReviewContext:
        operation_context = view_model.get("operation_context") or {}
        operation_summary = operation_context_summary(operation_context)
        source_refs = []
        if operation_summary and operation_summary.get("source_ref"):
            source_refs.append(str(operation_summary["source_ref"]))
        return AgentReviewContext(
            operation_context_summary=operation_summary,
            source_refs=source_refs,
            limitations=[
                str(item)
                for item in (operation_context.get("limitations") or [])
                if str(item)
            ],
        )


def compose_default_agent_review_context(*, view_model: dict[str, Any]) -> AgentReviewContext:
    """Return the built-in context set used by the MVP packet composer."""

    return OperationContextProvider().context_for_packet(view_model=view_model)


def operation_context_summary(context: dict[str, Any]) -> dict[str, Any] | None:
    if not context:
        return None

    event_impact = context.get("event_impact") or {}
    event_basis = event_impact.get("basis") or {}
    production_plan = context.get("production_plan") or {}
    capacity_model = context.get("capacity_model") or {}
    context_id = str(context.get("context_id") or "")

    return {
        "production_impact": context.get("production_impact"),
        "estimated_downtime_minutes": _number_or_none(
            event_basis.get("estimated_downtime_minutes")
        ),
        "estimated_lost_units": _number_or_none(event_impact.get("estimated_lost_units")),
        "product_variant": event_impact.get("product_variant")
        or production_plan.get("product_variant"),
        "basis": str(capacity_model.get("basis") or ""),
        "limitations": [str(item) for item in context.get("limitations") or []],
        "source_ref": f"operation-context://{context_id}" if context_id else None,
    }


def _number_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None

"""Read-only ports for operational context domains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.mvp.operational_context_contract import (
    FreshnessMetadata,
    FreshnessState,
    OperationalContextEnvelope,
    OperationalContextStatus,
    OperationalRequestIdentity,
    OperationalScope,
    classify_freshness,
)


class OperationalContextReadPort(Protocol):
    owner_domain: str

    def lookup(
        self,
        *,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> OperationalContextEnvelope:
        """Return bounded, versioned context without mutating domain state."""


@dataclass(frozen=True)
class FixtureProductionContextReadPort:
    """Adapter for the existing synthetic production-planning context.

    The fixture is injected by the composition root. This adapter deliberately
    exposes no ProductionOrder or WIP records because the current source does
    not contain them.
    """

    context: dict[str, Any]
    organization_id: str
    workspace_id: str
    source_ref: str
    freshness_policy_version: str = "production-fixture-freshness-v1"
    max_age_seconds: int = 86_400
    owner_domain: str = "production"

    def lookup(
        self,
        *,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> OperationalContextEnvelope:
        self._require_configured_scope(identity)
        temporal = self.context.get("temporal_scope") or {}
        generated_at = _parse_required_datetime(
            temporal.get("generated_at"), "temporal_scope.generated_at"
        )
        valid_from = _parse_required_datetime(
            temporal.get("valid_from"), "temporal_scope.valid_from"
        )
        valid_to = _parse_required_datetime(
            temporal.get("valid_to"), "temporal_scope.valid_to"
        )
        if valid_from >= valid_to:
            raise ValueError("production context valid_from must be before valid_to")

        freshness_state = classify_freshness(
            source_updated_at=generated_at,
            retrieved_at=retrieved_at,
            max_age_seconds=self.max_age_seconds,
        )
        in_temporal_scope = valid_from <= identity.decision_as_of < valid_to
        status = (
            OperationalContextStatus.AVAILABLE
            if in_temporal_scope and freshness_state is FreshnessState.FRESH
            else OperationalContextStatus.STALE
        )
        effective_freshness = (
            FreshnessState.FRESH
            if status is OperationalContextStatus.AVAILABLE
            else FreshnessState.STALE
        )

        event_impact = next(
            (
                item
                for item in self.context.get("event_impacts") or []
                if str(item.get("equipment_id") or "") == identity.asset_id
            ),
            None,
        )
        limitations = tuple(str(item) for item in self.context.get("limitations") or [])
        if event_impact is None:
            limitations = (*limitations, "No event impact exists for the requested asset.")

        data: dict[str, Any] = {}
        if status is OperationalContextStatus.AVAILABLE:
            data = {
                "context_id": self.context.get("context_id"),
                "source_type": self.context.get("source_type"),
                "production_plan": self.context.get("production_plan") or {},
                "capacity_model": self.context.get("capacity_model") or {},
                "event_impact": event_impact,
                "production_orders": [],
                "wip": [],
                "alternative_resources": [],
                "availability": {
                    "production_orders": "not_connected",
                    "wip": "not_connected",
                    "alternative_resources": "not_connected",
                },
            }
        elif not in_temporal_scope:
            limitations = (
                *limitations,
                "Requested decision_as_of is outside the fixture validity window.",
            )
        else:
            limitations = (
                *limitations,
                "Production context exceeded its configured freshness policy.",
            )

        snapshot_id = str(temporal.get("snapshot_id") or "")
        source_version = snapshot_id or str(self.context.get("context_id") or "")
        if not source_version:
            raise ValueError("production context requires a source version")

        return OperationalContextEnvelope(
            owner_domain=self.owner_domain,
            scope=OperationalScope(
                organization_id=identity.organization_id,
                project_id=identity.project_id,
                workspace_id=identity.workspace_id,
                asset_id=identity.asset_id,
            ),
            status=status,
            source_version=source_version,
            source_updated_at=generated_at,
            retrieved_at=retrieved_at,
            as_of=identity.decision_as_of,
            freshness=FreshnessMetadata(
                policy_version=self.freshness_policy_version,
                max_age_seconds=self.max_age_seconds,
                state=effective_freshness,
            ),
            source_refs=(self.source_ref,),
            data=data,
            limitations=limitations,
        )

    def _require_configured_scope(
        self, identity: OperationalRequestIdentity
    ) -> None:
        fixture_scope = self.context.get("scope") or {}
        fixture_project_id = str(fixture_scope.get("project_id") or "")
        if (
            identity.organization_id != self.organization_id
            or identity.workspace_id != self.workspace_id
            or identity.project_id != fixture_project_id
        ):
            raise ValueError("production context configured scope mismatch")


def _parse_required_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed

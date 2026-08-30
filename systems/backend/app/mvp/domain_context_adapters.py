"""Domain context adapters for read-only MVP review enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.mvp.sop_retrieval import retrieve_inspection_sops


class DomainReviewContextAdapter(Protocol):
    """Read-only adapter for domain-specific review context.

    Implementations may enrich UI/report/AI review inputs with operational
    context, inspection references, and SOP retrieval results. They must not
    create or approve closed-loop state.
    """

    adapter_id: str

    def operation_context(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
        project_id: str,
    ) -> dict[str, Any] | None:
        """Return production/operations context for the selected snapshot."""

    def inspection_guidance(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Return SOP-backed guidance keyed by Product Evidence component id."""

    def inspection_locations(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Return displayable inspection-location references keyed by component id."""

    def sop_retrieval(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        """Return read-only SOP retrieval candidates for agent review."""


class ManufacturingFixtureReviewContextAdapter:
    """Fixture-backed manufacturing domain adapter used by the MVP demo."""

    adapter_id = "manufacturing-fixture-review-context"

    def __init__(self, root: str | Path) -> None:
        fixture_root = Path(root) / "data" / "fixtures"
        self.operation_contexts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((fixture_root / "operation_context").glob("*.json"))
        ]
        self.inspection_sops = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((fixture_root / "inspection_sop").glob("*.json"))
        ]
        self.inspection_location_references = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((fixture_root / "inspection_location").glob("*.json"))
        ]

    def operation_context(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
        project_id: str,
    ) -> dict[str, Any] | None:
        equipment = fixture.get("equipment") or {}
        dataset_version = str(fixture.get("dataset_version") or "")
        observed_at = _parse_iso_datetime(
            str((fixture.get("observation") or {}).get("timestamp") or artifact.get("observed_at") or "")
        )
        if observed_at is None:
            return None

        for context in self.operation_contexts:
            scope = context.get("scope") or {}
            if str(scope.get("project_id") or "") != project_id:
                continue
            if dataset_version and str(scope.get("dataset_version") or "") != dataset_version:
                continue
            temporal_scope = context.get("temporal_scope") or {}
            valid_from = _parse_iso_datetime(str(temporal_scope.get("valid_from") or ""))
            valid_to = _parse_iso_datetime(str(temporal_scope.get("valid_to") or ""))
            if valid_from is None or valid_to is None or not (valid_from <= observed_at < valid_to):
                continue
            fixture_context = fixture.get("operation_context") or {}
            event_impact = fixture_context.get("event_impact") or _event_impact_for_fixture(context, fixture, equipment)
            capacity = context.get("capacity_model") or {}
            planning_window = capacity.get("planning_window") or {}
            oee_basis = capacity.get("oee_basis") or {}
            cycle_time_basis = capacity.get("cycle_time_basis") or {}
            asset_count_basis = capacity.get("asset_count_basis") or {}
            production_impact = fixture_context.get("production_impact")
            if production_impact not in {"none", "low", "medium", "high"}:
                production_impact = _production_impact(
                    (event_impact or {}).get("basis", {}).get("estimated_downtime_minutes")
                    if event_impact
                    else equipment.get("estimated_downtime_minutes")
                )
            return {
                "load_level": fixture_context.get("load_level"),
                "runtime_hours_7d": fixture_context.get("runtime_hours_7d"),
                "production_impact": production_impact,
                "context_id": context["context_id"],
                "source_type": context["source_type"],
                "temporal_scope": temporal_scope,
                "production_plan": context["production_plan"],
                "capacity_model": {
                    "active_asset_count": asset_count_basis.get("active_asset_count"),
                    "planned_operating_hours": planning_window.get("planned_operating_hours"),
                    "oee": oee_basis.get("oee"),
                    "standard_cycle_minutes_per_unit": cycle_time_basis.get("standard_cycle_minutes_per_unit"),
                    "asset_units_per_hour": capacity.get("asset_units_per_hour"),
                    "daily_capacity_units": capacity.get("daily_capacity_units"),
                    "basis": (
                        f"{asset_count_basis.get('active_asset_count')} assets, "
                        f"{planning_window.get('planned_operating_hours')}h/day, "
                        f"OEE {oee_basis.get('oee')}, "
                        f"cycle {cycle_time_basis.get('standard_cycle_minutes_per_unit')}min 기준"
                    ),
                },
                "event_impact": event_impact,
                "limitations": context.get("limitations") or [],
            }
        return None

    def inspection_guidance(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        matching_sops = self._matching_inspection_sops(fixture=fixture, artifact=artifact)
        component_ids = _component_ids(artifact)
        guidance_by_component: dict[str, dict[str, Any]] = {}
        for sop in matching_sops:
            for component_id in component_ids.intersection({str(item) for item in sop.get("component_ids") or []}):
                guidance = sop.get("guidance") or {}
                guidance_by_component[component_id] = {
                    "source_type": sop["source_kind"],
                    "sop_id": sop["sop_id"],
                    "title": sop["title"],
                    "version": sop["version"],
                    "reference_location_label": guidance.get("reference_location_label"),
                    "suggested_check_method": guidance.get("suggested_check_method"),
                    "checklist_draft": guidance.get("checklist_draft") or [],
                    "replacement_review_guidance": guidance.get("replacement_review_guidance") or {},
                    "safety_level": sop["safety_level"],
                    "requires_human_approval": sop["requires_human_approval"],
                    "source_ref": f"{sop['source_uri']}#{sop['sop_id']}",
                    "disclaimer": guidance.get("disclaimer"),
                }
        return guidance_by_component

    def inspection_locations(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        component_ids = _component_ids(artifact)
        asset_type = str(artifact.get("asset_type") or fixture.get("asset_type") or "")
        references: dict[str, dict[str, Any]] = {}
        for contract in self.inspection_location_references:
            if asset_type and asset_type not in {str(item) for item in contract.get("asset_types") or []}:
                continue
            for location in contract.get("locations") or []:
                component_id = str(location.get("component_id") or "")
                if component_id not in component_ids:
                    continue
                references[component_id] = {
                    "contract_id": contract.get("contract_id"),
                    "maturity": contract.get("maturity"),
                    "location_label": location.get("location_label"),
                    "inspection_method": location.get("inspection_method"),
                    "source_ref": f"{contract['source_uri']}#{component_id}",
                }
        return references

    def sop_retrieval(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        return retrieve_inspection_sops(
            fixture=fixture,
            artifact=artifact,
            procedures=self.inspection_sops,
        )

    def _matching_inspection_sops(
        self,
        *,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            item["procedure"]
            for item in self.sop_retrieval(fixture=fixture, artifact=artifact)["results"]
        ]


def _component_ids(artifact: dict[str, Any]) -> set[str]:
    component_hypotheses = (
        (artifact.get("evidence_payload") or {}).get("component_hypotheses") or []
    )
    return {
        str(item.get("component_id"))
        for item in component_hypotheses
        if isinstance(item, dict) and item.get("component_id")
    }


def _production_impact(estimated_downtime_minutes: Any) -> str | None:
    if not isinstance(estimated_downtime_minutes, int) or isinstance(estimated_downtime_minutes, bool):
        return None
    if estimated_downtime_minutes >= 180:
        return "high"
    if estimated_downtime_minutes >= 90:
        return "medium"
    if estimated_downtime_minutes > 0:
        return "low"
    return "none"


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_impact_for_fixture(
    context: dict[str, Any],
    fixture: dict[str, Any],
    equipment: dict[str, Any],
) -> dict[str, Any] | None:
    event_id = str(fixture.get("event_id") or "")
    equipment_id = str(equipment.get("equipment_id") or "")
    for impact in context.get("event_impacts") or []:
        if str(impact.get("event_id") or "") == event_id:
            return {**impact, "equipment_id": equipment_id or str(impact.get("equipment_id") or "")}
    for impact in context.get("event_impacts") or []:
        if str(impact.get("equipment_id") or "") == equipment_id:
            return {**impact, "equipment_id": equipment_id}
    return None

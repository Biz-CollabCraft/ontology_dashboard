"""Canonical manufacturing demonstration application service."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.diagnosis.contracts import derive_features, load_fixture
from app.diagnosis.domain import (
    build_evidence_package,
    build_product_result_artifact,
    event_evidence_projection_to_legacy_evidence,
    product_result_artifact_to_event_evidence_projection,
)
from app.equipment.ports import EquipmentApplicationPort
from app.mvp.agent_review_packet import compose_agent_review_packet
from app.mvp.asset_detail_view_model import compose_asset_detail_view_model
from app.mvp.sop_retrieval import retrieve_inspection_sops

from .context import ContextProviderFactory
from .contracts import (
    DecisionRequest,
    FollowUpRequest,
    FollowUpResponse,
    GroundedReport,
    Intent,
    LayoutRequest,
    NoteRequest,
    ReportRequest,
    UILayout,
)
from app.planner.contracts import IntentRouter, deterministic_answer
from .ports import AuditRepositoryPort, LayoutPlannerPort, ReportAgentPort

RISK_PRIORITY = {"critical": 0, "warning": 1, "attention": 2, "data_quality_hold": 3, "normal": 4}


class EventNotFound(KeyError):
    pass


class ManufacturingPredictiveMaintenanceService:
    def __init__(
        self,
        root: str | Path,
        *,
        repository: AuditRepositoryPort,
        equipment_service: EquipmentApplicationPort,
        report_agent: ReportAgentPort,
        layout_planner: LayoutPlannerPort,
        context_provider_factory: ContextProviderFactory,
    ) -> None:
        self.root = Path(root)
        fixture_root = self.root / "data" / "fixtures"
        fixture_paths = sorted(
            path
            for pattern in ("GS-*.json", "AZ-*.json", "MPT-*.json")
            for path in fixture_root.glob(pattern)
        )
        self.project_fixtures = {
            payload["event_id"]: payload
            for payload in (load_fixture(path) for path in fixture_paths)
        }
        operation_context_paths = sorted((fixture_root / "operation_context").glob("*.json"))
        self.operation_contexts = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in operation_context_paths
        ]
        inspection_sop_paths = sorted((fixture_root / "inspection_sop").glob("*.json"))
        self.inspection_sops = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in inspection_sop_paths
        ]
        inspection_location_paths = sorted((fixture_root / "inspection_location").glob("*.json"))
        self.inspection_location_references = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in inspection_location_paths
        ]
        # Historical Gold regression and manufacturing Ontology projection must
        # remain exactly GS-001..GS-008. Showcase Project fixtures are available
        # through project_fixtures and project-scoped APIs, never this alias.
        self.fixtures = {
            event_id: fixture
            for event_id, fixture in self.project_fixtures.items()
            if self._fixture_project_id(fixture) == "manufacturing-demo-project"
        }
        self.equipment_service = equipment_service
        self.repository = repository
        self.report_agent = report_agent
        self.layout_planner = layout_planner
        self.context_provider_factory = context_provider_factory
        self.intent_router = IntentRouter()

    def _fixture(self, event_id: str) -> dict[str, Any]:
        try:
            return self.project_fixtures[event_id]
        except KeyError as exc:
            raise EventNotFound(event_id) from exc

    def _context_provider(self, fixture: dict[str, Any]):
        return self.context_provider_factory(fixture)

    @staticmethod
    def _fixture_project_id(fixture: dict[str, Any]) -> str:
        return str(fixture.get("project_id") or "manufacturing-demo-project")

    def project_id_for_event(self, event_id: str) -> str:
        return self._fixture_project_id(self._fixture(event_id))

    def fixture_snapshot(self, event_id: str) -> dict[str, Any]:
        """Return the source snapshot through the MVP application boundary."""

        return self._fixture(event_id)

    def fixture_items(self) -> list[tuple[str, dict[str, Any]]]:
        return sorted(self.fixtures.items())

    def fixture_count(self) -> int:
        return len(self.fixtures)

    def event_activity(self, event_id: str) -> dict[str, Any]:
        return self.repository.event_activity(event_id)

    def record_audit(self, **command: Any) -> dict[str, Any]:
        return self.repository.record_audit(**command)

    def evidence_snapshot(self, event_id: str) -> dict[str, Any]:
        fixture = self._fixture(event_id)
        package = self._projected_legacy_evidence(fixture)
        package["lineage"]["project_id"] = self._fixture_project_id(fixture)
        if fixture.get("dataset_version"):
            package["lineage"]["dataset_version"] = str(fixture["dataset_version"])
        return package

    def event_evidence_projection(self, event_id: str) -> dict[str, Any]:
        fixture = self._fixture(event_id)
        projection = self._event_evidence_projection(fixture)
        projection["event_id"] = fixture["event_id"]
        projection["scenario_id"] = fixture["scenario_id"]
        return projection

    def evidence(self, event_id: str, *, view: str = "legacy") -> dict[str, Any]:
        if view == "canonical":
            projection = self.event_evidence_projection(event_id)
            self._audit(
                event_id,
                "evidence.generated",
                projection["provenance"]["model_version"],
                {"event_id": projection["event_id"], "view": "canonical"},
            )
            return projection
        package = self.evidence_snapshot(event_id)
        self._audit(event_id, "evidence.generated", package["model"]["model_version"], {"evidence_id": package["evidence_id"]})
        return package

    def list_events(self, project_id: str = "manufacturing-demo-project") -> list[dict[str, Any]]:
        rows = []
        for event_id, fixture in self.project_fixtures.items():
            if self._fixture_project_id(fixture) != project_id:
                continue
            evidence = build_evidence_package(fixture, context_provider=self._context_provider(fixture))
            rows.append(
                {
                    "event_id": event_id,
                    "scenario_id": fixture["scenario_id"],
                    "equipment": fixture["equipment"],
                    "status": evidence["status"],
                    "failure_probability": evidence["failure_probability"],
                    "confidence": evidence["confidence"],
                    "predicted_failure_type": evidence["predicted_failure_type"],
                    "recommended_decision": evidence["recommended_decision"],
                }
            )
        return sorted(rows, key=lambda row: (RISK_PRIORITY[row["status"]], -(row["failure_probability"] or 0.0)))

    def list_equipment(self, project_id: str = "manufacturing-demo-project") -> list[dict[str, Any]]:
        return self.equipment_service.list_equipment(project_id)

    def equipment(self, equipment_id: str, project_id: str = "manufacturing-demo-project") -> dict[str, Any]:
        item = self.equipment_service.equipment(equipment_id, project_id)
        events = [
            event
            for event in self.list_events(project_id)
            if event["equipment"]["equipment_id"] == equipment_id
        ]
        return {**item, "events": events}

    def equipment_current_state(
        self, equipment_id: str, project_id: str = "manufacturing-demo-project"
    ) -> dict[str, Any] | None:
        return self.equipment_service.equipment_current_state(equipment_id, project_id)

    def asset_detail_view_model(
        self,
        asset_id: str,
        project_id: str = "manufacturing-demo-project",
        *,
        dataset_version_id: str | None = None,
        history_window: str = "24h",
    ) -> dict[str, Any]:
        fixture = self._fixture_for_asset(asset_id, project_id, dataset_version_id=dataset_version_id)
        artifact = self._product_result_artifact(fixture)
        asset = self._asset_summary_for_fixture(fixture, artifact)
        return compose_asset_detail_view_model(
            asset=asset,
            result_artifact=artifact,
            feature_series=self._feature_series_for_fixture(fixture, artifact),
            runtime_prediction_history=self._runtime_history_for_fixture(fixture, artifact),
            equipment_history=self._equipment_history_for_fixture(fixture),
            operation_context=self._operation_context_for_fixture(fixture, artifact) or fixture.get("operation_context"),
            closed_loop=fixture.get("closed_loop"),
            inspection_guidance=self._inspection_guidance_for_fixture(fixture, artifact),
            inspection_locations=self._inspection_location_references_for_fixture(fixture, artifact),
            data_status={
                "source": "canonical",
                "last_updated_at": artifact["observed_at"],
                "warnings": [],
            },
            history_window=history_window,
        )

    def agent_review_packet(
        self,
        asset_id: str,
        project_id: str = "manufacturing-demo-project",
        *,
        dataset_version_id: str | None = None,
        history_window: str = "24h",
    ) -> dict[str, Any]:
        fixture = self._fixture_for_asset(asset_id, project_id, dataset_version_id=dataset_version_id)
        artifact = self._product_result_artifact(fixture)
        return compose_agent_review_packet(
            project_id=project_id,
            view_model=self.asset_detail_view_model(
                asset_id,
                project_id,
                dataset_version_id=dataset_version_id,
                history_window=history_window,
            ),
            sop_retrieval=self._retrieve_inspection_sops(fixture, artifact),
        )

    def patch_equipment_state(
        self,
        equipment_id: str,
        *,
        expected_state_version: int | None,
        state_patch: dict[str, Any],
        project_id: str = "manufacturing-demo-project",
    ) -> dict[str, Any]:
        return self.equipment_service.patch_equipment_state(
            equipment_id,
            expected_state_version=expected_state_version,
            state_patch=state_patch,
            project_id=project_id,
        )

    def event(self, event_id: str) -> dict[str, Any]:
        fixture = self._fixture(event_id)
        return {
            "event_id": event_id,
            "project_id": self._fixture_project_id(fixture),
            "scenario_id": fixture["scenario_id"],
            "equipment": fixture["equipment"],
            "observation": fixture["observation"],
            "history": fixture["history"],
            "runtime": fixture["runtime"],
            "activity": self.repository.event_activity(event_id),
        }

    def _fixture_for_asset(
        self,
        asset_id: str,
        project_id: str,
        *,
        dataset_version_id: str | None = None,
    ) -> dict[str, Any]:
        for fixture in self.project_fixtures.values():
            if self._fixture_project_id(fixture) != project_id:
                continue
            if dataset_version_id and fixture.get("dataset_version") and fixture.get("dataset_version") != dataset_version_id:
                continue
            equipment = fixture.get("equipment") or {}
            if str(equipment.get("equipment_id")) == asset_id:
                return fixture
        raise EventNotFound(asset_id)

    @staticmethod
    def _asset_summary_for_fixture(fixture: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        equipment = fixture.get("equipment") or {}
        last_maintenance_days_ago = _days_between(
            equipment.get("last_maintenance_date"),
            artifact["observed_at"],
        )
        estimated_downtime = equipment.get("estimated_downtime_minutes")
        return {
            "asset_id": artifact["asset_id"],
            "asset_type": equipment.get("asset_type") or artifact["asset_type"],
            "display_name": equipment.get("display_name") or artifact["asset_id"],
            "site_id": equipment.get("site_id") or artifact.get("site_id") or "Manufacturing Demo",
            "cell_id": equipment.get("cell_id") or equipment.get("line") or artifact.get("cell_id") or "unknown",
            "observed_at": artifact["observed_at"],
            "criticality": equipment.get("criticality"),
            "criticality_basis": ["fixture equipment.criticality"]
            if equipment.get("criticality") in {"low", "medium", "high"}
            else [],
            "criticality_source": "equipment_master"
            if equipment.get("criticality") in {"low", "medium", "high"}
            else "unknown",
            "maintenance_context": {
                "last_maintenance_days_ago": last_maintenance_days_ago,
                "similar_events_30d": None,
                "open_work_order_exists": None,
            },
            "operation_context": {
                "load_level": None,
                "runtime_hours_7d": None,
                "production_impact": _production_impact(estimated_downtime),
            },
        }

    @staticmethod
    def _feature_series_for_fixture(
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        feature_keys = list(
            dict.fromkeys(
                [
                    *(factor.get("feature") for factor in artifact.get("top_factors") or []),
                    *(
                        ((artifact.get("evidence_payload") or {}).get("sensor_evidence") or {})
                        .get("sensors", {})
                        .keys()
                    ),
                ]
            )
        )
        rows = fixture.get("history") or []
        current_observed_at = str(artifact["observed_at"])
        current_instant = _timestamp_instant(current_observed_at)
        series: dict[str, dict[str, Any]] = {}
        for key in feature_keys:
            points_by_instant: dict[datetime, dict[str, Any]] = {}
            for row in rows:
                derived_row: dict[str, Any] = {}
                try:
                    derived_row = derive_features(row)
                except (TypeError, ValueError):
                    derived_row = {}
                source_row = {**derived_row, **row}
                if key not in source_row:
                    continue
                observed_at = str(row.get("timestamp") or current_observed_at)
                instant = _timestamp_instant(observed_at)
                if instant >= current_instant:
                    continue
                point = {
                    "observed_at": observed_at,
                    "value": source_row.get(key),
                    "quality_status": "unknown"
                    if artifact.get("status_grade") == "data_quality_hold"
                    else "good",
                }
                if instant in points_by_instant and points_by_instant[instant] != point:
                    raise ValueError(
                        f"conflicting fixture history points at instant={instant.isoformat()}"
                    )
                points_by_instant[instant] = point
            points = [points_by_instant[instant] for instant in sorted(points_by_instant)]
            if points:
                series[str(key)] = {
                    "source_ref": f"observation-contract://{artifact['asset_id']}/{key}",
                    "points": points,
                }
        return series

    @staticmethod
    def _runtime_history_for_fixture(
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        points = []
        history = fixture.get("runtime_prediction_history") or fixture.get("prediction_history") or []
        for index, row in enumerate(history):
            if "failure_probability" not in row:
                continue
            observed_at = str(row.get("timestamp") or artifact["observed_at"])
            points.append(
                {
                    "observed_at": observed_at,
                    "failure_probability": row["failure_probability"],
                    "status_grade": row.get("status_grade") or row.get("status"),
                    "prediction_id": str(row.get("prediction_id") or f"{artifact['asset_id']}#{observed_at}#{index}"),
                    "source_kind": str(row.get("source_kind") or "runtime_inference"),
                    "source_ref": str(row.get("source_ref") or f"diagnosis-runtime-history://{artifact['asset_id']}/{observed_at}"),
                }
            )
        return points

    @staticmethod
    def _equipment_history_for_fixture(fixture: dict[str, Any]) -> list[dict[str, Any]]:
        equipment = fixture.get("equipment") or {}
        last_maintenance = equipment.get("last_maintenance_date")
        if not last_maintenance:
            return []
        return [
            {
                "occurred_at": f"{last_maintenance}T00:00:00+09:00",
                "kind": "maintenance",
                "tone": "normal",
                "description": "최근 정비 이력",
                "source": "equipment-maintenance-context",
            }
        ]

    def _operation_context_for_fixture(
        self,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, Any] | None:
        equipment = fixture.get("equipment") or {}
        project_id = self._fixture_project_id(fixture)
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

    def _inspection_guidance_for_fixture(
        self,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        matching_sops = self._matching_inspection_sops(fixture, artifact)
        component_hypotheses = (
            (artifact.get("evidence_payload") or {}).get("component_hypotheses") or []
        )
        component_ids = {
            str(item.get("component_id"))
            for item in component_hypotheses
            if isinstance(item, dict) and item.get("component_id")
        }
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

    def _inspection_location_references_for_fixture(
        self,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        component_hypotheses = (
            (artifact.get("evidence_payload") or {}).get("component_hypotheses") or []
        )
        component_ids = {
            str(item.get("component_id"))
            for item in component_hypotheses
            if isinstance(item, dict) and item.get("component_id")
        }
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

    def _matching_inspection_sops(
        self,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            item["procedure"]
            for item in self._retrieve_inspection_sops(fixture, artifact)["results"]
        ]

    def _retrieve_inspection_sops(
        self,
        fixture: dict[str, Any],
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        return retrieve_inspection_sops(
            fixture=fixture,
            artifact=artifact,
            procedures=self.inspection_sops,
        )

    def report(self, event_id: str, request: ReportRequest) -> tuple[GroundedReport, dict[str, Any]]:
        fixture = self._fixture(event_id)
        evidence = self._projected_legacy_evidence(fixture)
        report, trace = self.report_agent.generate(
            evidence,
            request.role,
            locale=request.locale,
            use_llm=request.use_llm,
            provider_available=fixture["runtime"]["llm_available"],
        )
        self._audit(
            event_id,
            "report.generated",
            evidence["model"]["model_version"],
            {"report_id": report.report_id, "role": request.role, "locale": request.locale, **trace},
        )
        return report, trace

    def _event_evidence_projection(self, fixture: dict[str, Any]) -> dict[str, Any]:
        artifact = self._product_result_artifact(fixture)
        return product_result_artifact_to_event_evidence_projection(artifact)

    def _projected_legacy_evidence(self, fixture: dict[str, Any]) -> dict[str, Any]:
        artifact = self._product_result_artifact(fixture)
        projection = product_result_artifact_to_event_evidence_projection(artifact)
        legacy = event_evidence_projection_to_legacy_evidence(
            projection,
            ranked_factor_evidence=artifact.get("ranked_factor_evidence"),
        )
        legacy["event_id"] = fixture["event_id"]
        legacy["evidence_id"] = f"EVD-{fixture['event_id']}"
        legacy["scenario_id"] = fixture["scenario_id"]
        legacy["equipment"] = fixture["equipment"]
        return legacy

    def _product_result_artifact(self, fixture: dict[str, Any]) -> dict[str, Any]:
        return build_product_result_artifact(
            fixture,
            context_provider=self._context_provider(fixture),
        )

    def layout(self, event_id: str, request: LayoutRequest) -> tuple[UILayout, dict[str, Any]]:
        fixture = self._fixture(event_id)
        evidence = build_evidence_package(fixture, context_provider=self._context_provider(fixture))
        report, report_trace = self.report_agent.generate(
            evidence,
            request.role,
            locale=request.locale,
            use_llm=request.use_llm,
            provider_available=fixture["runtime"]["llm_available"],
        )
        layout, layout_trace = self.layout_planner.plan(
            evidence,
            report,
            request.role,
            request.intent,
            locale=request.locale,
            use_llm=request.use_llm,
            provider_available=fixture["runtime"]["planner_available"],
        )
        trace = {"report": report_trace, "layout": layout_trace}
        self._audit(
            event_id,
            "layout.generated",
            evidence["model"]["model_version"],
            {"layout_id": layout.layout_id, "role": request.role, "intent": request.intent, **trace},
        )
        return layout, trace

    def decide(self, event_id: str, request: DecisionRequest) -> dict[str, Any]:
        self._fixture(event_id)
        record = self.repository.record_decision(event_id, request.actor, request.decision, request.note)
        self._audit(event_id, "decision.recorded", None, record)
        return record

    def note(self, event_id: str, request: NoteRequest) -> dict[str, Any]:
        self._fixture(event_id)
        record = self.repository.add_note(event_id, request.actor, request.body)
        self._audit(event_id, "note.recorded", None, {"note_id": record["id"], "actor": request.actor})
        return record

    def follow_up(self, event_id: str, request: FollowUpRequest) -> FollowUpResponse:
        fixture = self._fixture(event_id)
        evidence = build_evidence_package(fixture, context_provider=self._context_provider(fixture))
        routed = self.intent_router.route(request.question)
        intent: Intent = routed.intent
        report, report_trace = self.report_agent.generate(
            evidence,
            request.role,
            locale=request.locale,
            use_llm=False,
            provider_available=False,
        )
        layout, layout_trace = self.layout_planner.plan(
            evidence,
            report,
            request.role,
            intent,
            locale=request.locale,
            use_llm=False,
            provider_available=False,
        )
        answer = deterministic_answer(intent, evidence, routed.supported, request.locale)
        thread_id = f"THR-{event_id}-{request.role}"
        record = self.repository.add_conversation(
            thread_id,
            event_id,
            request.role,
            request.question,
            intent,
            answer,
        )
        return FollowUpResponse(
            thread_id=thread_id,
            event_id=event_id,
            role=request.role,
            intent=intent,
            answer=answer,
            report=report,
            layout=layout.model_dump(mode="python") if hasattr(layout, "model_dump") else layout,
            supported=routed.supported,
            audit={"conversation_id": record["id"], "reason": routed.reason, "report": report_trace, "layout": layout_trace},
        )

    def reset(self) -> dict[str, str]:
        self.repository.reset()
        return {"status": "reset", "scope": "decisions, notes, conversations, ontology actions, audit"}

    def _audit(self, event_id: str | None, action: str, model_version: str | None, payload: dict[str, Any]) -> None:
        self.repository.record_audit(
            event_id=event_id,
            run_id=str(uuid.uuid4()),
            action=action,
            model_version=model_version,
            payload=payload,
        )


def _timestamp_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("fixture observation timestamps must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _days_between(start_date: Any, end_timestamp: str) -> int | None:
    if not start_date:
        return None
    try:
        start = datetime.fromisoformat(f"{start_date}T00:00:00+09:00")
        end = datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (end.date() - start.date()).days)


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


def _matches_any(value: str, candidates: list[Any]) -> bool:
    return value in {str(candidate) for candidate in candidates}


def _is_displayable_inspection_sop(sop: dict[str, Any]) -> bool:
    source_kind = str(sop.get("source_kind") or "")
    maturity = str(sop.get("maturity") or "")
    return (
        (source_kind == "demo_sop_fixture" and maturity == "fixture")
        or (source_kind == "site_sop" and maturity == "approved")
    )


# Temporary compatibility alias for integrations that still import the historical
# service name. New code should use ManufacturingPredictiveMaintenanceService.
FactorySignalService = ManufacturingPredictiveMaintenanceService


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

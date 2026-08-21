"""Canonical manufacturing demonstration application service."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from app.diagnosis.contracts import load_fixture
from app.diagnosis.domain import (
    build_evidence_package,
    build_product_result_artifact,
    event_evidence_projection_to_legacy_evidence,
    product_result_artifact_to_event_evidence_projection,
)
from app.equipment.ports import EquipmentApplicationPort

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


# Temporary compatibility alias for integrations that still import the historical
# service name. New code should use ManufacturingPredictiveMaintenanceService.
FactorySignalService = ManufacturingPredictiveMaintenanceService

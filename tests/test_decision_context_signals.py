from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.operations.decision_tools import DecisionToolName, ManufacturingDecisionTools
from app.operations.operational_context_contract import OperationalRequestIdentity
from app.operations.operational_context_ports import (
    FixtureMaintenanceReadinessContextReadPort,
    FixtureProductionDecisionContextReadPort,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "data" / "fixtures" / "operation_context"
NOW = datetime(2026, 9, 2, 2, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-S04-L02-03",
    evidence_snapshot_id="ART-001",
    decision_as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc),
)


def load(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_production_context_exposes_bounded_decision_pressure_signals() -> None:
    source = deepcopy(load("operational-decision-context-v1.json"))
    source["due_pressure"] = "high"
    source["schedule_slack_minutes"] = 45
    result = FixtureProductionDecisionContextReadPort(
        context=source,
        source_ref="fixture:production",
    ).lookup(identity=IDENTITY, retrieved_at=NOW)

    assert result.data["due_pressure"] == "high"
    assert result.data["schedule_slack_minutes"] == 45


def test_maintenance_context_exposes_window_reservation_and_blocking_signals() -> None:
    source = deepcopy(load("maintenance-readiness-context-v1.json"))
    source["maintenance_windows"][0]["suitability"] = "conditional"
    source["maintenance_windows"][0]["conflict_reason"] = "production window overlap requires review"
    source["inventory_snapshots"][0]["reservation_state"] = "fully_reserved"
    source["blocking_reasons"] = ["part reservation must be released or replenished"]
    result = FixtureMaintenanceReadinessContextReadPort(
        context=source,
        source_ref="fixture:maintenance",
    ).lookup(identity=IDENTITY, retrieved_at=NOW)

    assert result.data["maintenance_windows"][0]["suitability"] == "conditional"
    assert result.data["maintenance_windows"][0]["conflict_reason"]
    assert result.data["inventory_snapshots"][0]["reservation_state"] == "fully_reserved"
    assert result.data["blocking_reasons"] == ["part reservation must be released or replenished"]


def test_missing_new_signals_remain_explicitly_unknown_without_breaking_existing_fixtures() -> None:
    production = FixtureProductionDecisionContextReadPort(
        context=load("operational-decision-context-v1.json"),
        source_ref="fixture:production",
    ).lookup(identity=IDENTITY, retrieved_at=NOW)
    maintenance = FixtureMaintenanceReadinessContextReadPort(
        context=load("maintenance-readiness-context-v1.json"),
        source_ref="fixture:maintenance",
    ).lookup(identity=IDENTITY, retrieved_at=NOW)

    assert production.data["due_pressure"] == "unknown"
    assert production.data["schedule_slack_minutes"] is None
    assert maintenance.data["maintenance_windows"][0]["suitability"] == "unknown"
    assert maintenance.data["inventory_snapshots"][0]["reservation_state"] == "unknown"
    assert maintenance.data["blocking_reasons"] == []


def test_decision_tools_surface_condition_and_inspection_completeness_without_inventing_trend() -> None:
    packet = {
        "asset_id": IDENTITY.asset_id,
        "snapshot_basis": {
            "artifact_id": IDENTITY.evidence_snapshot_id,
            "observed_at": IDENTITY.decision_as_of.isoformat(),
        },
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.82},
        "model_expression_context": {"top_factors": []},
        "review_draft": {"priority_label": "high"},
        "inspection_targets": [{"component_id": "tooling"}],
        "sop_guidance": [{"sop_id": "SOP-1"}],
        "maintenance_history_summary": {"inspection_results": []},
        "evidence_gaps": [{"field": "risk_series", "reason": "not materialized"}],
        "source_refs": ["artifact:ART-001"],
    }
    tools = ManufacturingDecisionTools(packet_loader=lambda _identity: packet, operational_ports={})

    condition = tools.call(
        tool_name=DecisionToolName.GET_ASSET_CONDITION,
        identity=IDENTITY,
        retrieved_at=NOW,
    )
    inspection = tools.call(
        tool_name=DecisionToolName.GET_INSPECTION_CONTEXT,
        identity=IDENTITY,
        retrieved_at=NOW,
    )

    assert condition.data["decision_signals"] == {
        "trend_severity": "unknown",
        "persistence": "unknown",
        "data_quality_hold": False,
    }
    assert inspection.data["decision_signals"] == {
        "completeness": "pending",
        "additional_measurement_required": None,
    }


def test_explicit_condition_and_inspection_signals_pass_through_for_agent_comparison() -> None:
    packet = {
        "asset_id": IDENTITY.asset_id,
        "snapshot_basis": {
            "artifact_id": IDENTITY.evidence_snapshot_id,
            "observed_at": IDENTITY.decision_as_of.isoformat(),
        },
        "risk_summary": {"status_grade": "warning"},
        "model_expression_context": {},
        "review_draft": {"priority_label": "high"},
        "condition_decision_signals": {"trend_severity": "rapid_worsening", "persistence": "persistent"},
        "inspection_decision_signals": {"completeness": "partial", "additional_measurement_required": True},
        "inspection_targets": [{"component_id": "tooling"}],
        "maintenance_history_summary": {"inspection_results": []},
        "source_refs": ["artifact:ART-001"],
    }
    tools = ManufacturingDecisionTools(packet_loader=lambda _identity: packet, operational_ports={})

    condition = tools.call(tool_name=DecisionToolName.GET_ASSET_CONDITION, identity=IDENTITY, retrieved_at=NOW)
    inspection = tools.call(tool_name=DecisionToolName.GET_INSPECTION_CONTEXT, identity=IDENTITY, retrieved_at=NOW)

    assert condition.data["decision_signals"]["trend_severity"] == "rapid_worsening"
    assert condition.data["decision_signals"]["persistence"] == "persistent"
    assert inspection.data["decision_signals"]["completeness"] == "partial"
    assert inspection.data["decision_signals"]["additional_measurement_required"] is True

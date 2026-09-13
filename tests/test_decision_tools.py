from datetime import datetime, timezone

import pytest

from app.operations.decision_retry import RetryFailureKind
from app.operations.decision_tools import (
    DecisionToolFailure,
    DecisionToolName,
    ManufacturingDecisionTools,
)
from app.operations.operational_context_contract import (
    FreshnessMetadata,
    FreshnessState,
    OperationalContextEnvelope,
    OperationalContextStatus,
    OperationalRequestIdentity,
    OperationalScope,
)

NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-01",
    evidence_snapshot_id="ART-001",
    decision_as_of=NOW,
)


def packet(identity=IDENTITY):
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {
            "artifact_id": identity.evidence_snapshot_id,
            "observed_at": identity.decision_as_of.isoformat(),
        },
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.82},
        "model_expression_context": {
            "top_factors": [{"feature": "tool_wear_min", "value": 230}],
            "source_refs": ["result:factor:1"],
        },
        "inspection_targets": [{"component_id": "tooling"}],
        "sop_guidance": [{"sop_id": "SOP-1"}],
        "maintenance_history_summary": {
            "inspection_results": [{"record_id": "IR-1", "outcome": "maintenance_recommended"}],
            "work_orders": [{"record_id": "WO-1", "status": "requested"}],
            "maintenance_actions": [],
            "maintenance_events": [],
        },
        "source_refs": ["artifact:ART-001"],
        "evidence_gaps": [],
    }


class Port:
    def __init__(self, domain, data, status=OperationalContextStatus.AVAILABLE):
        self.owner_domain = domain
        self.data = data
        self.status = status

    def lookup(self, *, identity, retrieved_at):
        return OperationalContextEnvelope(
            owner_domain=self.owner_domain,
            scope=OperationalScope(
                organization_id=identity.organization_id,
                project_id=identity.project_id,
                workspace_id=identity.workspace_id,
                asset_id=identity.asset_id,
            ),
            status=self.status,
            source_version=f"{self.owner_domain}-v1" if self.status is OperationalContextStatus.AVAILABLE else None,
            source_updated_at=retrieved_at if self.status is OperationalContextStatus.AVAILABLE else None,
            retrieved_at=retrieved_at,
            as_of=identity.decision_as_of,
            freshness=FreshnessMetadata(
                policy_version="test",
                max_age_seconds=60,
                state=FreshnessState.FRESH if self.status is OperationalContextStatus.AVAILABLE else FreshnessState.UNKNOWN,
            ),
            source_refs=(f"source:{self.owner_domain}",),
            data=self.data if self.status is OperationalContextStatus.AVAILABLE else {},
            limitations=(),
        )


def tools(loader=packet):
    return ManufacturingDecisionTools(
        packet_loader=loader,
        operational_ports={
            "production": Port("production", {"production_orders": [{"order_id": "PO-1"}]}),
            "maintenance_readiness": Port(
                "maintenance_readiness",
                {
                    "maintenance_windows": [{"window_id": "MW-1"}],
                    "concurrent_work_checks": [],
                    "part_requirements": [{"part_requirement_id": "PR-1"}],
                    "inventory_snapshots": [{"part_id": "P-1", "available_quantity": 1}],
                    "technician_readiness": [{"technician_id": "T-1"}],
                },
            ),
        },
    )


def test_exposes_exactly_five_read_only_tool_names():
    assert tools().names == tuple(DecisionToolName)
    assert len(tools().names) == 5


def test_asset_and_inspection_tools_project_packet_without_mutation():
    t = tools()
    condition = t.call(tool_name=DecisionToolName.GET_ASSET_CONDITION, identity=IDENTITY, retrieved_at=NOW)
    inspection = t.call(tool_name=DecisionToolName.GET_INSPECTION_CONTEXT, identity=IDENTITY, retrieved_at=NOW)
    assert condition.data["risk_summary"]["status_grade"] == "warning"
    assert inspection.data["inspection_results"][0]["outcome"] == "maintenance_recommended"
    assert "artifact:ART-001" in inspection.source_refs


def test_production_and_readiness_tools_reuse_operational_ports():
    t = tools()
    production = t.call(tool_name=DecisionToolName.GET_PRODUCTION_CONTEXT, identity=IDENTITY, retrieved_at=NOW)
    readiness = t.call(tool_name=DecisionToolName.GET_RESOURCE_READINESS, identity=IDENTITY, retrieved_at=NOW)
    assert production.data["production_orders"][0]["order_id"] == "PO-1"
    assert readiness.data["inventory_snapshots"][0]["available_quantity"] == 1
    assert readiness.data["technician_readiness"][0]["technician_id"] == "T-1"


def test_maintenance_context_combines_owner_history_with_readiness_window():
    result = tools().call(tool_name=DecisionToolName.GET_MAINTENANCE_CONTEXT, identity=IDENTITY, retrieved_at=NOW)
    assert result.data["work_orders"][0]["record_id"] == "WO-1"
    assert result.data["maintenance_windows"][0]["window_id"] == "MW-1"


def test_snapshot_mismatch_is_not_silently_retried_as_data():
    def wrong(_identity):
        value = packet()
        value["snapshot_basis"]["artifact_id"] = "OTHER"
        return value

    with pytest.raises(DecisionToolFailure) as error:
        tools(wrong).call(tool_name=DecisionToolName.GET_ASSET_CONDITION, identity=IDENTITY, retrieved_at=NOW)
    assert error.value.kind is RetryFailureKind.STALE_SNAPSHOT

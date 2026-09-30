from datetime import datetime, timezone

from app.operations.decision_mcp import MCP_TOOL_NAMES, register_decision_mcp_tools
from app.operations.decision_tools import ManufacturingDecisionTools
from app.operations.operational_context_contract import OperationalRequestIdentity

NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-01",
    evidence_snapshot_id="ART-001",
    decision_as_of=NOW,
)


class FakeServer:
    def __init__(self):
        self.registered = {}

    def tool(self, *, name, description):
        def decorator(fn):
            self.registered[name] = {"description": description, "fn": fn}
            return fn
        return decorator


def packet(identity):
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {"artifact_id": identity.evidence_snapshot_id, "observed_at": identity.decision_as_of.isoformat()},
        "risk_summary": {"status_grade": "warning"},
        "model_expression_context": {"top_factors": []},
        "inspection_targets": [],
        "sop_guidance": [],
        "maintenance_history_summary": {},
        "source_refs": ["artifact:ART-001"],
    }


def test_mcp_registers_exactly_five_read_only_tools_with_fixed_identity():
    server = FakeServer()
    tools = ManufacturingDecisionTools(packet_loader=packet, operational_ports={})
    register_decision_mcp_tools(server, tools=tools, identity=IDENTITY, now=lambda: NOW)
    assert tuple(server.registered) == MCP_TOOL_NAMES
    assert len(server.registered) == 5
    assert not any(any(token in name for token in ("create", "approve", "start", "complete", "update", "delete")) for name in server.registered)
    # Model-facing handler accepts no organization/project/asset arguments; scope is application-fixed.
    result = server.registered["get_asset_condition"]["fn"]()
    assert result["data"]["risk_summary"]["status_grade"] == "warning"
    assert result["as_of"] in {NOW.isoformat(), NOW.isoformat().replace("+00:00", "Z")}

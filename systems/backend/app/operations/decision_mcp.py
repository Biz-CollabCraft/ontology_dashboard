"""MCP adapter for the bounded read-only manufacturing decision tools.

Identity is fixed by the authenticated application session before registration;
the model cannot supply or widen organization/project/workspace/asset scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.operations.decision_tools import DecisionToolName, ManufacturingDecisionTools
from app.operations.operational_context_contract import OperationalRequestIdentity


MCP_SERVER_NAME = "manufacturing-decision-readonly"
MCP_TOOL_NAMES = tuple(tool.value for tool in DecisionToolName)
FORBIDDEN_MUTATION_TOKENS = (
    "create",
    "update",
    "delete",
    "approve",
    "start",
    "complete",
    "stop_asset",
    "order_part",
    "change_schedule",
)


def register_decision_mcp_tools(
    server: Any,
    *,
    tools: ManufacturingDecisionTools,
    identity: OperationalRequestIdentity,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Any:
    """Register exactly five zero-argument, read-only tools on an MCP server."""

    registered: list[str] = []

    def bind(tool_name: DecisionToolName, description: str) -> None:
        if any(token in tool_name.value.lower() for token in FORBIDDEN_MUTATION_TOKENS):
            raise ValueError(f"mutation-like MCP tool is forbidden: {tool_name.value}")

        def handler() -> dict[str, Any]:
            result = tools.call(
                tool_name=tool_name,
                identity=identity,
                retrieved_at=now(),
            )
            return result.model_dump(mode="json")

        handler.__name__ = tool_name.value
        handler.__doc__ = description
        server.tool(name=tool_name.value, description=description)(handler)
        registered.append(tool_name.value)

    bind(
        DecisionToolName.GET_ASSET_CONDITION,
        "Read the current evidence-bound asset condition, risk factors, and data-quality gaps.",
    )
    bind(
        DecisionToolName.GET_INSPECTION_CONTEXT,
        "Read inspection targets, SOP guidance, recorded inspection results, and missing inspection evidence.",
    )
    bind(
        DecisionToolName.GET_MAINTENANCE_CONTEXT,
        "Read current event-scoped maintenance history, work-order state, windows, and concurrent-work checks.",
    )
    bind(
        DecisionToolName.GET_PRODUCTION_CONTEXT,
        "Read production orders, WIP, alternatives, and event impact for the fixed decision scope.",
    )
    bind(
        DecisionToolName.GET_RESOURCE_READINESS,
        "Read parts, inventory, technician readiness, maintenance windows, and blocking conditions.",
    )
    if tuple(registered) != MCP_TOOL_NAMES:
        raise RuntimeError("MCP tool registration does not match the decision-tool contract")
    return server


def build_decision_mcp_server(
    *,
    tools: ManufacturingDecisionTools,
    identity: OperationalRequestIdentity,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
):
    """Build a FastMCP server lazily so core backend tests do not require MCP."""

    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - dependency is deployment-specific
        raise RuntimeError(
            "MCP runtime is not installed; install the decision-agent optional dependencies"
        ) from exc
    server = FastMCP(MCP_SERVER_NAME)
    return register_decision_mcp_tools(server, tools=tools, identity=identity, now=now)

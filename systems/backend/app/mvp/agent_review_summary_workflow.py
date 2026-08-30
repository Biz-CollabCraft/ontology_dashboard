"""Minimal orchestration boundary for Agent Review Summary materialization."""

from __future__ import annotations

from typing import Any, Protocol


AGENT_REVIEW_SUMMARY_FLOW_VERSION = "agent-review-summary-flow-v1.0"


class AgentReviewSummaryWorkflowService(Protocol):
    """Service surface required by the read-only summary workflow."""

    def materialize_agent_review_summaries(
        self,
        project_id: str = "manufacturing-demo-project",
        *,
        history_window: str = "24h",
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Create or reuse validated summaries for available snapshots."""


class AgentReviewSummaryWorkflow:
    """Run the polling-watcher AI flow without granting mutation authority."""

    def __init__(self, service: AgentReviewSummaryWorkflowService) -> None:
        self.service = service

    def run(
        self,
        project_id: str = "manufacturing-demo-project",
        *,
        history_window: str = "24h",
        limit: int | None = None,
        trigger: str = "polling_watcher",
    ) -> dict[str, Any]:
        materialization = self.service.materialize_agent_review_summaries(
            project_id,
            history_window=history_window,
            limit=limit,
        )
        materialized_count = int(materialization.get("materialized_count") or 0)
        created_count = int(materialization.get("created_count") or 0)
        reused_count = int(materialization.get("reused_count") or 0)
        failed_count = sum(
            1
            for item in materialization.get("items") or []
            if str(item.get("status") or "") == "failed"
        )
        return {
            "flow_version": AGENT_REVIEW_SUMMARY_FLOW_VERSION,
            "trigger": trigger,
            "read_only": True,
            "mutation_allowed": False,
            "stages": [
                {
                    "stage": "snapshot_scan",
                    "status": "completed",
                    "item_count": materialized_count,
                },
                {
                    "stage": "packet_build",
                    "status": "completed",
                    "item_count": materialized_count,
                },
                {
                    "stage": "summary_materialization",
                    "status": "completed" if failed_count == 0 else "partial",
                    "created_count": created_count,
                    "reused_count": reused_count,
                    "failed_count": failed_count,
                },
                {
                    "stage": "consumer_ready",
                    "status": "completed" if failed_count == 0 else "partial",
                    "consumer_contract": "agent-review-summary-v1.0",
                    "consumers": ["role_workflow_ui", "executive_brief_report"],
                },
            ],
            **materialization,
        }

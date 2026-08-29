"""LLM adapter for read-only Agent Review Summary generation."""

from __future__ import annotations

from typing import Any

from app.infra.llm import LLMProvider
from app.mvp.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    summary_schema,
)


AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT = """
You write a Korean read-only maintenance review summary from one Agent Review Packet.

Hard contract:
- Use only facts, IDs, timestamps, source_refs, limitations, inspection targets, SOP guidance,
  evidence gaps, risk summary, and history summary present in the packet.
- Do not return the input agent_review_packet or any of its packet-only fields.
- Do not create work orders, approvals, maintenance events, replay requests, action IDs,
  state patches, or any closed-loop mutation.
- Do not claim repair completion, auto approval, real downtime reduction, root-cause certainty,
  or actual failure prevention.
- Preserve packet asset_id, generated_at, packet schema version, boundary note, limitations,
  evidence gaps, and source_refs grounding.
- Return JSON only, matching agent-review-summary-v1.0.
- Keep baseline_summary.history_summary, inspection_focus, evidence_gaps, data_footnotes,
  source_refs, boundary_note, confidence_label, limitations, schema_version,
  packet_schema_version, asset_id, generated_at, and mode unchanged.
- Keep baseline_summary.role_summaries role, label, and source_refs unchanged.
- You may improve only title, summary, and role_summaries[*].quote. These fields must stay
  read-only Korean prose grounded in baseline_summary and agent_review_packet.
""".strip()


class AgentReviewSummaryProvider:
    """Generate a candidate summary through the shared LLM provider port."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self.provider = provider
        self.name = getattr(provider, "name", "none")

    def generate(self, packet: dict[str, Any]) -> dict[str, Any]:
        if self.provider is None:
            raise RuntimeError("agent_review_summary_provider_disabled")
        baseline_summary = compose_deterministic_agent_review_summary(packet)
        payload = self.provider.generate_json(
            AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
            {
                "agent_review_packet": packet,
                "baseline_summary": baseline_summary,
                "allowed_output_fields": list(baseline_summary.keys()),
            },
            response_schema=summary_schema(),
            response_schema_name="agent_review_summary",
        )
        payload["mode"] = "llm"
        return payload

"""LLM adapter for read-only Agent Review Summary generation."""

from __future__ import annotations

from typing import Any

from app.infra.llm import LLMProvider


AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT = """
You write a Korean read-only maintenance review summary from one Agent Review Packet.

Hard contract:
- Use only facts, IDs, timestamps, source_refs, limitations, inspection targets, SOP guidance,
  evidence gaps, risk summary, and history summary present in the packet.
- Do not create work orders, approvals, maintenance events, replay requests, action IDs,
  state patches, or any closed-loop mutation.
- Do not claim repair completion, auto approval, real downtime reduction, root-cause certainty,
  or actual failure prevention.
- Preserve packet asset_id, generated_at, packet schema version, boundary note, limitations,
  evidence gaps, and source_refs grounding.
- Return JSON only, matching agent-review-summary-v1.0.
""".strip()


class AgentReviewSummaryProvider:
    """Generate a candidate summary through the shared LLM provider port."""

    def __init__(self, provider: LLMProvider | None) -> None:
        self.provider = provider
        self.name = getattr(provider, "name", "none")

    def generate(self, packet: dict[str, Any]) -> dict[str, Any]:
        if self.provider is None:
            raise RuntimeError("agent_review_summary_provider_disabled")
        payload = self.provider.generate_json(
            AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
            {"agent_review_packet": packet},
        )
        payload["mode"] = "llm"
        return payload

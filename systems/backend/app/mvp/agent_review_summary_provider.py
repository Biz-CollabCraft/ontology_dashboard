"""LLM adapter for read-only Agent Review Summary generation."""

from __future__ import annotations

from typing import Any

from app.mvp.agent_review_summary import (
    compose_deterministic_agent_review_summary,
)
from app.mvp.ports import AgentReviewLLMPort


AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT = """
You write a Korean read-only maintenance review summary from compact grounded context.

Hard contract:
- Use only facts, IDs, timestamps, source_refs, limitations, inspection targets, SOP guidance,
  evidence gaps, risk summary, and history summary present in summary_context.
- Do not return the input context or any packet-only fields.
- Do not create work orders, approvals, maintenance events, replay requests, action IDs,
  state patches, or any closed-loop mutation.
- Do not claim repair completion, auto approval, real downtime reduction, root-cause certainty,
  or actual failure prevention.
- Return JSON only, matching agent-review-summary-editable-v1.0.
- Return only title, summary, and role_summaries[*].quote edits.
- Keep role_summaries[*].role values exactly as provided in baseline_editable_fields.
- All prose must stay read-only Korean and grounded in summary_context.

Role workflow:
- field_operator prose is for the shop-floor operator or line owner. It should say what
  physical location to check, what symptom/evidence to record, and what to hand off to
  maintenance or the production manager. It must not decide approval, work priority, or
  line sequencing.
- process_manager prose is for the production decision owner. It should explain production
  impact, priority/approval review, and line or cell sequencing implications. It must not
  claim that repair, approval, or work execution has already happened.
""".strip()

AGENT_REVIEW_SUMMARY_PROMPT_VERSION = "agent-review-summary-prompt-v1.2-role-workflow"
AGENT_REVIEW_SUMMARY_PAYLOAD_PROFILE = "compact-editable-v1"


class AgentReviewSummaryProvider:
    """Generate a candidate summary through the shared LLM provider port."""

    def __init__(self, provider: AgentReviewLLMPort | None) -> None:
        self.provider = provider
        self.name = getattr(provider, "name", "none")

    def generate(self, packet: dict[str, Any]) -> dict[str, Any]:
        if self.provider is None:
            raise RuntimeError("agent_review_summary_provider_disabled")
        baseline_summary = compose_deterministic_agent_review_summary(packet)
        payload = self.provider.generate_json(
            AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
            build_agent_review_summary_prompt_payload(
                packet=packet,
                baseline_summary=baseline_summary,
            ),
            response_schema=agent_review_summary_editable_schema(),
            response_schema_name="agent_review_summary_editable",
        )
        return _merge_llm_editable_fields(
            baseline_summary=baseline_summary,
            candidate=payload,
        )


def _merge_llm_editable_fields(
    *,
    baseline_summary: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Apply LLM prose edits while preserving grounded summary structure."""

    summary = dict(baseline_summary)
    summary["mode"] = "llm"
    for field in ("title", "summary"):
        value = candidate.get(field)
        if isinstance(value, str) and value.strip():
            summary[field] = value

    candidate_quotes = {
        str(item.get("role")): item.get("quote")
        for item in candidate.get("role_summaries") or []
        if isinstance(item, dict) and isinstance(item.get("quote"), str)
    }
    summary["role_summaries"] = [
        {
            **item,
            "quote": candidate_quotes.get(item["role"]) or item["quote"],
        }
        for item in baseline_summary.get("role_summaries") or []
    ]
    return summary


def build_agent_review_summary_prompt_payload(
    *,
    packet: dict[str, Any],
    baseline_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build compact grounded context for prose-only LLM edits."""

    return {
        "summary_context": {
            "packet_schema_version": str(packet.get("schema_version") or ""),
            "asset_id": str(packet.get("asset_id") or ""),
            "asset_label": str(packet.get("asset_label") or packet.get("asset_id") or ""),
            "generated_at": str(packet.get("generated_at") or ""),
            "source_refs": [str(ref) for ref in packet.get("source_refs") or [] if str(ref)],
            "risk_summary": _pick(
                packet.get("risk_summary") or {},
                "status_grade",
                "failure_probability",
                "review_priority",
                "top_factor_count",
            ),
            "review_draft": _pick(
                packet.get("review_draft") or {},
                "summary",
                "history_summary",
                "boundary_note",
            ),
            "inspection_targets": [
                _pick(
                    target,
                    "component_id",
                    "component_label",
                    "location_label",
                    "basis_refs",
                    "source_ref",
                    "location_source_ref",
                )
                for target in packet.get("inspection_targets") or []
                if isinstance(target, dict)
            ],
            "sop_guidance": [
                _pick(
                    guidance,
                    "component_id",
                    "component_label",
                    "procedure_title",
                    "check_items",
                    "source_ref",
                    "location_source_ref",
                )
                for guidance in packet.get("sop_guidance") or []
                if isinstance(guidance, dict)
            ],
            "evidence_gaps": [
                _pick(gap, "field", "reason", "owner_domain")
                for gap in packet.get("evidence_gaps") or []
                if isinstance(gap, dict)
            ],
            "limitations": [str(item) for item in packet.get("limitations") or []],
            "operation_context": _pick(
                packet.get("operation_context_summary") or {},
                "production_impact",
                "estimated_downtime_minutes",
                "estimated_lost_units",
                "limitations",
            ),
            "maintenance_history": _compact_maintenance_history(
                packet.get("maintenance_history_summary") or {}
            ),
            "model_factors": [
                _pick(factor, "rank", "feature", "display_name", "direction", "source_ref")
                for factor in (packet.get("model_expression_context") or {}).get("top_factors")
                or []
                if isinstance(factor, dict)
            ],
            "ontology_context": _compact_ontology_context(
                packet.get("ontology_context") or {}
            ),
        },
        "baseline_editable_fields": {
            "title": baseline_summary.get("title"),
            "summary": baseline_summary.get("summary"),
            "role_summaries": [
                _pick(item, "role", "label", "quote", "source_refs")
                for item in baseline_summary.get("role_summaries") or []
                if isinstance(item, dict)
            ],
        },
        "allowed_output_fields": ["title", "summary", "role_summaries"],
    }


def agent_review_summary_editable_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "summary", "role_summaries"],
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "role_summaries": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["role", "quote"],
                    "properties": {
                        "role": {"type": "string", "enum": ["field_operator", "process_manager"]},
                        "quote": {"type": "string"},
                    },
                },
            },
        },
    }


def _compact_maintenance_history(history: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": history.get("provider"),
        "open_work_order_exists": history.get("open_work_order_exists"),
        "similar_events_30d": history.get("similar_events_30d"),
        "work_orders": [
            _pick(item, "status", "requested_at", "approved_at", "completed_at")
            for item in history.get("work_orders") or []
            if isinstance(item, dict)
        ],
        "similar_events": [
            _pick(item, "observed_at", "status_grade", "failure_type", "component_label")
            for item in history.get("similar_events") or []
            if isinstance(item, dict)
        ],
    }


def _compact_ontology_context(context: dict[str, Any]) -> dict[str, Any]:
    traversals = []
    for traversal in context.get("traversals") or []:
        if not isinstance(traversal, dict):
            continue
        traversals.append(
            {
                "component_id": traversal.get("component_id"),
                "component_label": traversal.get("component_label"),
                "spare_parts": [
                    _pick(part, "part_label", "source_ref")
                    for part in traversal.get("spare_parts") or []
                    if isinstance(part, dict)
                ],
            }
        )
    return {
        "provider": context.get("provider"),
        "traversals": traversals,
    }


def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}

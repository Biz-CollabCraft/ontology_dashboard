"""Bounded generation decisions; never migrate prose between snapshot keys.

The materialization key owns scope, evidence/context and provider versions.
Unknown semantic changes regenerate. REUSE requires a stored exact-key result;
ON_DEMAND without refresh means pending, not permission for GET to generate.
"""

from __future__ import annotations

from typing import Any
import hashlib
import math
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from copy import deepcopy

from jsonschema import Draft202012Validator
from app.operations.agent_review_summary import validate_agent_review_summary_contract

ROLE_POLICY_VERSION = "role-briefing-policy-v2"
MINOR_PROBABILITY_DELTA = 0.005  # Fixed before temporal v3 evaluation: 0.5 percentage point.
MAX_MINOR_CHANGE_DEFERRAL_SECONDS = 300  # Never leave a continuously changing briefing pending forever.
MODEL_POLICY_VERSION = "exact-materialization-model-v1"
GENERATION_POLICIES = ("click", "always", "hybrid", "demand")


def background_generation_required(packet, previous=None):
    """Demand policy: precompute urgent/unknown risk; ordinary risk waits for a request.

    This is a scheduling gate, never a cache-validity decision. Deliberately
    conservative for unknown risk, and independent of changing snapshot IDs.
    """
    risk = packet.get("risk_summary") or {}
    grade = risk.get("status_grade")
    priority = (packet.get("review_priority") or {}).get("level")
    probability = risk.get("failure_probability")
    threshold = (packet.get("model_expression_context") or {}).get("threshold")
    if previous is None and (packet.get("maintenance_history_summary") or {}).get("open_work_order_exists") is True:
        return True
    if previous is not None:
        for field in ("maintenance_history_summary", "operation_context_summary", "review_priority"):
            if packet.get(field) != previous.get(field):
                return True
        old_risk = previous.get("risk_summary") or {}
        old_probability = old_risk.get("failure_probability")
        if old_risk.get("status_grade") != grade:
            return True
        if type(old_probability) not in (int, float) or type(probability) not in (int, float):
            return True
        if not math.isfinite(old_probability) or abs(probability - old_probability) > MINOR_PROBABILITY_DELTA:
            return True
    if grade not in {"normal", "attention"} or priority == "immediate":
        return True
    if type(probability) not in (int, float) or type(threshold) not in (int, float):
        return True
    return not (math.isfinite(probability) and math.isfinite(threshold)) or probability >= threshold


class SnapshotGuardedRepository:
    """Check the service's current binding immediately before summary storage."""

    def __init__(self, repository, validate_binding, validate_cached=None):
        self.repository = repository
        self.validate_binding = validate_binding
        self.validate_cached = validate_cached

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def save_agent_review_summary(self, **record):
        self.validate_binding()
        return self.repository.save_agent_review_summary(**record)

    def get_agent_review_summary(self, key):
        record = self.repository.get_agent_review_summary(key)
        if record is not None and self.validate_cached is not None:
            if not self.validate_cached(record):
                return None
        return record


@lru_cache(maxsize=1)
def _packet_validator():
    path = Path(__file__).resolve().parents[4] / "contracts/schemas/agent-review-packet.schema.json"
    return Draft202012Validator(json.loads(path.read_text()))


@lru_cache(maxsize=1)
def _runtime_packet_validator():
    """Local compatibility branch for the established runtime producer.

    Only retrieval metadata differs; validate all other canonical packet fields.
    Neither the packet nor the shared canonical schema is rewritten.
    """
    schema = deepcopy(_packet_validator().schema)
    schema["properties"]["sop_retrieval"] = {
        "type": "object",
        "required": ["provider", "query", "top_k", "returned_count", "mutation_allowed"],
        "additionalProperties": False,
        "properties": {
            "provider": {"const": "runtime_product_result"},
            "query": {
                "type": "object",
                "required": ["asset_id", "event_id", "dataset_version_id"],
                "additionalProperties": False,
                "properties": {key: {"type": "string", "minLength": 1} for key in ("asset_id", "event_id", "dataset_version_id")},
            },
            "top_k": {"type": "integer", "const": 0},
            "returned_count": {"type": "integer", "const": 0},
            "mutation_allowed": {"const": False},
        },
    }
    return Draft202012Validator(schema)


def _packet_schema_valid(packet):
    if not isinstance(packet, dict):
        return False
    retrieval = packet.get("sop_retrieval")
    if not isinstance(retrieval, dict) or retrieval.get("provider") != "runtime_product_result":
        return _packet_validator().is_valid(packet)
    if not _runtime_packet_validator().is_valid(packet):
        return False
    query = retrieval["query"]
    basis = packet["snapshot_basis"]
    return (
        query["asset_id"] == packet["asset_id"] == basis["asset_id"]
        and query["event_id"] == basis["event_id"]
        and query["dataset_version_id"] == basis["dataset_version"]
    )


def packet_is_current(packet, *, now=None, require_schema=True):
    """Fail closed for malformed packets and explicit expired/invalid context.

    This checks supplied validity metadata, not external source authenticity.
    Missing expiry does not invent a TTL for historical fixture snapshots.
    """
    now = now or datetime.now(timezone.utc)
    try:
        if require_schema and not _packet_schema_valid(packet):
            return False

        def valid(value):
            if isinstance(value, list):
                return all(valid(item) for item in value)
            if not isinstance(value, dict):
                return True
            for key, item in value.items():
                if key in {"expires_at", "valid_until"} and item is not None:
                    expiry = datetime.fromisoformat(str(item).replace("Z", "+00:00"))
                    if expiry.tzinfo is None or expiry <= now:
                        return False
                if key in {"temporal_status", "freshness_status"} and item in ("expired", "stale", "invalid", "mismatch"):
                    return False
                if not valid(item):
                    return False
            return True

        return valid(packet)
    except (TypeError, ValueError):
        return False


def cached_record_is_valid(record, *, packet, key_payload, materialization_key, now=None):
    """Validate the persisted envelope and prose against the *current* packet."""
    try:
        if not packet_is_current(packet, now=now):
            return False
        if record.get("summary_key") != materialization_key:
            return False
        if record.get("snapshot_basis") != packet.get("snapshot_basis"):
            return False
        for field in ("organization_id", "project_id", "workspace_id", "asset_id", "history_window", "packet_schema_version", "summary_schema_version", "prompt_version", "model_version", "source_sha256"):
            if record.get(field) != key_payload.get(field):
                return False
        if record.get("dataset_version_id") != key_payload.get("dataset_version"):
            return False
        if record.get("event_id") != key_payload.get("event_id"):
            return False
        if (record.get("trace") or {}).get("context_sha256") != key_payload.get("context_sha256"):
            return False
        if record.get("status") not in {"ready", "fallback"}:
            return False
        return not validate_agent_review_summary_contract(record["summary"], packet=packet)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def material_change_required(current, previous, *, current_identity, previous_identity):
    """Scheduling only. A deferred changed key remains ineligible for reads.

    Compare with the last successfully generated packet, not the last poll, so
    small deltas accumulate. Unknown changes and version/validity changes win.
    Restart/missing baseline conservatively generates.
    """
    if previous is None or not packet_is_current(current) or not packet_is_current(previous):
        return True
    variable_identity = {"source_sha256", "context_sha256", "evidence_basis_sha256"}
    if {k: v for k, v in current_identity.items() if k not in variable_identity} != {
        k: v for k, v in (previous_identity or {}).items() if k not in variable_identity
    }:
        return True
    before, after = deepcopy(previous), deepcopy(current)
    old = (before.get("risk_summary") or {}).get("failure_probability")
    new = (after.get("risk_summary") or {}).get("failure_probability")
    if (type(old) not in (int, float) or type(new) not in (int, float)
            or not math.isfinite(old) or not math.isfinite(new)
            or not 0 <= old <= 1 or not 0 <= new <= 1
            or old == new or abs(new - old) > MINOR_PROBABILITY_DELTA):
        return True
    threshold = (before.get("model_expression_context") or {}).get("threshold")
    if type(threshold) in (int, float) and (old >= threshold) != (new >= threshold):
        return True
    for item, probability in ((before, old), (after, new)):
        model = item.get("model_expression_context") or {}
        if model.get("failure_probability") != probability:
            return True
        item["risk_summary"]["failure_probability"] = 0
        model["failure_probability"] = 0
        item["snapshot_basis"].pop("source_sha256", None)
        item.pop("generated_at", None)
        # Only the known producer probability surface is ignored, not other prose.
        draft = item.get("review_draft") or {}
        if isinstance(draft.get("summary"), str):
            draft["summary"] = draft["summary"].replace(f"{probability * 100:.1f}%", "<probability>")
        (item.get("evidence_context") or {}).pop("relation_retrieved_at", None)
    return before != after


def policy_fingerprint(materialization_key: str) -> str:
    """Version the scheduling trace without changing immutable storage identity.

    Prose changes must still bump the existing prompt/schema/model identity.
    These policy versions govern scheduling only, not prose compatibility.
    """
    payload = [materialization_key, ROLE_POLICY_VERSION, MODEL_POLICY_VERSION]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def decide_generation(
    *,
    policy: str = "always",
    current_fingerprint: str,
    previous_fingerprint: str | None = None,
    reuse_eligibility: str = "INELIGIBLE",
    explicit_refresh: bool = False,
    retry_fallback: bool = False,
    model_id: str = "unknown",
    material_change: bool = True,
    input_valid: bool = True,
    background_required: bool = True,
    minor_change_deferral_expired: bool = False,
) -> dict[str, Any]:
    if policy not in GENERATION_POLICIES:
        raise ValueError(f"unknown generation policy: {policy}")
    if not current_fingerprint:
        raise ValueError("current fingerprint is required")
    if reuse_eligibility not in {"EXACT_VALIDATED", "INELIGIBLE"}:
        raise ValueError("reuse eligibility must be explicitly validated")
    exact_cached = reuse_eligibility == "EXACT_VALIDATED"
    if not input_valid:
        reuse_eligibility = "INELIGIBLE"
        trigger, decision, reason = "INVALID_INPUT", "ON_DEMAND", "invalid_or_expired_packet_blocked"
    elif explicit_refresh:
        trigger, decision, reason = "USER_REFRESH", "ON_DEMAND", "explicit_refresh_current_snapshot"
    elif policy == "click":
        trigger = "INITIAL"
        decision = "REUSE" if exact_cached else "ON_DEMAND"
        reason = "exact_stored_snapshot" if exact_cached else "await_explicit_refresh"
    elif exact_cached and not retry_fallback:
        trigger, decision, reason = "INITIAL", "REUSE", "exact_stored_snapshot"
    elif policy == "demand" and not background_required:
        trigger, decision, reason = "AWAIT_DEMAND", "ON_DEMAND", "ordinary_risk_waits_for_explicit_request"
    elif retry_fallback:
        trigger, decision, reason = "RETRY", "PREGENERATE", "retry_existing_fallback"
    elif policy == "hybrid" and not material_change and minor_change_deferral_expired:
        trigger, decision, reason = (
            "MINOR_CHANGE_MAX_WAIT",
            "PREGENERATE",
            "minor_change_max_deferral_elapsed_regenerate",
        )
    elif policy == "hybrid" and not material_change:
        trigger, decision, reason = "MINOR_CHANGE", "ON_DEMAND", "minor_probability_change_deferred_no_reuse"
    else:
        trigger = "AUTO_MATERIAL_CHANGE" if previous_fingerprint else "INITIAL"
        decision = "PREGENERATE"
        reason = (
            "changed_binding_or_unknown_semantics_regenerate"
            if previous_fingerprint else "no_exact_stored_summary_regenerate"
        )
    return {
        "policy": policy,
        "generation_trigger": trigger,
        "generation_decision": decision,
        "generation_action": "GENERATE" if input_valid and (explicit_refresh or decision == "PREGENERATE") else "DEFER",
        "reuse_eligibility": reuse_eligibility,
        "decision_reason": reason,
        "background_required": background_required,
        "minor_change_deferral_expired": minor_change_deferral_expired,
        "previous_fingerprint": previous_fingerprint,
        "current_fingerprint": current_fingerprint,
        "role_policy_version": ROLE_POLICY_VERSION,
        "model_policy_version": MODEL_POLICY_VERSION,
        "model_id": model_id,
        "input_tokens": None,
        "output_tokens": None,
        "latency_ms": None,
        "estimated_cost": None,
        "measurement_status": "not_measured",
    }

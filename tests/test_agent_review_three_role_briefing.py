"""Versioned role prose, legacy reads and cache revalidation boundaries."""
import copy
import json
from pathlib import Path

import pytest

from app.operations.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
    summary_schema,
)
from app.operations.agent_review_summary_provider import (
    _merge_llm_editable_fields,
    build_tool_selected_agent_review_summary_prompt_payload,
)
from app.operations.agent_review_summary_materialization import (
    AgentReviewSummaryMaterializer, _valid_cached_summary,
)
from app.operations.router import _summary_text

ROOT = Path(__file__).resolve().parents[1]
ROLES = ["process_engineer", "maintenance_technician", "process_manager"]


def packet():
    return json.loads((ROOT / "tests/fixtures/agent_review_packets/GS-004.json").read_text())


@pytest.mark.parametrize("scenario", [f"GS-{i:03d}" for i in range(1, 9)])
def test_three_roles_preserve_packet_truth(scenario):
    p = json.loads((ROOT / f"tests/fixtures/agent_review_packets/{scenario}.json").read_text())
    summary = compose_deterministic_agent_review_summary(p)
    assert summary["schema_version"] == "agent-review-summary-v1.1"
    assert [item["role"] for item in summary["role_summaries"]] == ROLES
    assert validate_agent_review_summary_contract(summary, packet=p) == []
    assert summary["source_refs"] == p["source_refs"]


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "wrong_label", "legacy_role", "unknown_version"])
def test_v11_rejects_ambiguous_role_contract(mutation):
    p = packet()
    summary = compose_deterministic_agent_review_summary(p)
    if mutation == "duplicate":
        summary["role_summaries"][1] = copy.deepcopy(summary["role_summaries"][0])
    elif mutation == "missing":
        summary["role_summaries"].pop()
    elif mutation == "wrong_label":
        summary["role_summaries"][1]["label"] = "설비 엔지니어"
    elif mutation == "legacy_role":
        summary["role_summaries"][0]["role"] = "field_operator"
    else:
        summary["schema_version"] = "agent-review-summary-v99"
    assert validate_agent_review_summary_contract(summary, packet=p)


def test_legacy_contract_stays_frozen_and_common_prose_is_explicit_fallback():
    assert summary_schema("agent-review-summary-v1.0")["properties"]["role_summaries"]["items"]["properties"]["role"]["enum"] == ["field_operator", "process_manager"]
    legacy = {"summary": "공통 근거", "role_summaries": [{"role": "field_operator", "quote": "이전 현장 문장"}]}
    assert _summary_text(legacy, "engineering") == "공통 근거"
    assert _summary_text(legacy, "maintenance") == "공통 근거"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "blank"])
def test_provider_does_not_disguise_missing_role_prose_as_llm(mutation):
    baseline = compose_deterministic_agent_review_summary(packet())
    candidate = {k: copy.deepcopy(baseline[k]) for k in ("title", "summary", "role_summaries")}
    if mutation == "missing":
        candidate["role_summaries"].pop()
    elif mutation == "duplicate":
        candidate["role_summaries"][1] = candidate["role_summaries"][0]
    else:
        candidate["role_summaries"][1]["quote"] = " "
    with pytest.raises(ValueError, match="summary_role_quotes_invalid"):
        _merge_llm_editable_fields(baseline_summary=baseline, candidate=candidate)


def test_prose_merge_preserves_envelope_and_role_priorities():
    p = packet()
    baseline = compose_deterministic_agent_review_summary(p)
    candidate = copy.deepcopy(baseline)
    candidate.update(asset_id="invented", generated_at="2099", source_refs=["invented"])
    merged = _merge_llm_editable_fields(baseline_summary=baseline, candidate=candidate)
    for key in ("asset_id", "generated_at", "source_refs", "inspection_focus", "limitations"):
        assert merged[key] == baseline[key]
    payload = build_tool_selected_agent_review_summary_prompt_payload(packet=p, baseline_summary=baseline)
    assert set(payload["role_priorities"]) == set(ROLES)


@pytest.mark.parametrize("mutation", ["old_number", "old_time", "legacy_version", "unknown_ref"])
def test_exact_key_still_revalidates_cached_summary(mutation):
    p = packet()
    summary = compose_deterministic_agent_review_summary(p)
    summary["mode"] = "llm"
    record = {"summary": summary, "status": "ready"}
    assert _valid_cached_summary(record, packet=p)
    if mutation == "old_number":
        summary["role_summaries"][0]["quote"] = "예측 위험도는 99.9%입니다."
    elif mutation == "old_time":
        summary["generated_at"] = "2099-01-01"
    elif mutation == "legacy_version":
        summary["schema_version"] = "agent-review-summary-v1.0"
    else:
        summary["source_refs"] = ["unknown"]
    assert not _valid_cached_summary(record, packet=p)
    class Repository:
        def get_agent_review_summary(self, key):
            return record
    result, trace = AgentReviewSummaryMaterializer(Repository(), None).lookup(
        packet=p, organization_id="org", project_id="project", workspace_id="workspace", history_window="30d")
    assert result is None
    assert trace["materialization"]["status"] == "pending"

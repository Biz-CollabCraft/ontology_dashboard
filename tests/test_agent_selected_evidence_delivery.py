"""Consumer regression for selected evidence, provenance and read audit time."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.dependencies import build_manufacturing_service
from app.operations.agent_review_packet import compose_agent_review_packet
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import AgentReviewSummaryProvider
from app.operations.agent_review_summary_materialization import summary_key_payload
from app.operations.context_providers import compose_default_agent_review_context

ROOT = Path(__file__).resolve().parents[1]


def key(packet):
    return summary_key_payload(packet=packet, project_id="manufacturing-demo-project",
                               history_window="24h", provider=None)


def test_selected_evidence_reaches_actual_provider_and_cache(tmp_path):
    service = build_manufacturing_service(tmp_path / "selection.db", root=ROOT)
    view = service.asset_detail_view_model("CNC-S04-L04-01")
    view["evidence_context"]["selected_basis"] = [{
        "candidate_id": "selected-part", "candidate_type": "fact",
        "source_ref": "maintenance:record-1", "source_version": "record-v1",
        "source_snapshot_id": "snapshot-1", "domain": "maintenance_readiness",
        "relation_path": ["action_requires_part"], "fact_type": "part_readiness",
        "as_of": view["snapshot_basis"]["observed_at"], "freshness_state": "fresh",
        "value_summary": "선별한 부품 준비 근거", "required_for_boundary": False,
    }]
    view["evidence_context"]["rejected_basis"] = [{"value_summary": "REJECTED_PROBE"}]
    view["evidence_context"]["limitations"] = ["승인 여부는 미확인"]
    packet = compose_agent_review_packet(project_id="manufacturing-demo-project",
        view_model=view, sop_retrieval={"provider": "test", "results": []})
    assert "maintenance:record-1" in packet["source_refs"]
    assert "승인 여부는 미확인" in packet["limitations"]

    class Capture:
        name = "capture"
        def generate_json(self, system, payload, **kwargs):
            self.payload = payload
            return {
                "title": "선별 근거 전달 검증",
                "summary": "선별된 근거와 한계가 제공된 상태입니다.",
                "role_summaries": [
                    {"role": "process_engineer", "quote": "선별된 점검 근거를 기준으로 이상 위치를 검토합니다."},
                    {"role": "maintenance_technician", "quote": "선별된 정비 준비 근거와 승인 미확인 한계를 구분해 검토합니다."},
                    {"role": "process_manager", "quote": "선별된 생산 영향 근거와 일정 판단 한계를 구분해 검토합니다."},
                ],
            }

    capture = Capture()
    provider = AgentReviewSummaryProvider(capture)
    provider.generate(packet)
    before = deepcopy(capture.payload)
    selected = before["summary_context"]["selected_evidence"]
    assert selected["selected_basis"][0]["value_summary"] == "선별한 부품 준비 근거"
    assert selected["selected_basis"][0]["source_ref"] == "maintenance:record-1"
    assert selected["limitations"] == ["승인 여부는 미확인"]
    assert "REJECTED_PROBE" not in str(before)

    changed = deepcopy(packet)
    changed["evidence_context"]["selected_basis"][0]["value_summary"] = "변경된 부품 준비 근거"
    provider.generate(changed)
    assert before != capture.payload
    assert key(packet) != key(changed)

    read_again = deepcopy(packet)
    read_again["evidence_context"]["relation_retrieved_at"] = "2026-09-08T01:00:00+00:00"
    provider.generate(read_again)
    assert before == capture.payload
    assert key(packet) == key(read_again)


def test_source_record_survives_history_reordering_into_prompt(tmp_path):
    service = build_manufacturing_service(tmp_path / "history.db", root=ROOT)
    view = service.asset_detail_view_model("CNC-S04-L04-01")
    records = [
        {"description": "기록 A", "occurred_at": "2026-09-01T00:00:00+00:00", "source": "maintenance:A"},
        {"description": "기록 B", "occurred_at": "2026-09-02T00:00:00+00:00", "source_ref": "maintenance:B"},
    ]
    for history in (records, records[::-1]):
        view["equipment_history"] = history
        context = compose_default_agent_review_context(view_model=view)
        mapped = context.maintenance_history_summary["recent_equipment_history"]
        assert {r["description"]: r["source_ref"] for r in mapped} == {
            "기록 A": "maintenance:A", "기록 B": "maintenance:B"}
        packet = compose_agent_review_packet(project_id="manufacturing-demo-project",
            view_model=view, sop_retrieval={"provider": "test", "results": []})
        from app.operations.agent_review_summary_provider import build_tool_selected_agent_review_summary_prompt_payload
        payload = build_tool_selected_agent_review_summary_prompt_payload(
            packet=packet, baseline_summary=compose_deterministic_agent_review_summary(packet))
        supplied = payload["summary_context"]["maintenance_history"]["recent_equipment_history"]
        assert {r["source_ref"] for r in supplied} == {"maintenance:A", "maintenance:B"}


def test_actual_retrieval_time_is_distinct_from_decision_basis(tmp_path):
    service = build_manufacturing_service(tmp_path / "clock.db", root=ROOT)
    observed = "2026-09-01T00:00:00+00:00"
    retrieved = datetime(2026, 9, 7, tzinfo=timezone.utc)

    class Context:
        def contexts(self, *, identity, retrieved_at):
            self.identity, self.retrieved = identity, retrieved_at
            return {}

    repo = Context()
    result = service.evidence_context_for_snapshot(asset_id="asset-1",
        artifact={"artifact_id": "event-1", "observed_at": observed},
        project_id="manufacturing-demo-project", event_id="event-1",
        context_repository=repo, retrieved_at=retrieved)
    assert repo.identity.decision_as_of.isoformat() == observed
    assert repo.retrieved == retrieved
    assert result["decision_as_of"] == observed
    assert result["relation_retrieved_at"] == retrieved.isoformat()

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.maintenance.api_schema import EvidenceSnapshotBasis
from app.maintenance.service import MaintenanceLoopService

ROOT = Path(__file__).resolve().parents[1]
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
ARMS = ("B1", "B2", "B3")
SCENARIOS = (
    "risk_escalation",
    "risk_recovery",
    "artifact_replacement",
    "evidence_history_update",
)


class SequencedProjectionQuery:
    def __init__(self, projections: list[dict[str, Any]]) -> None:
        self.projections = projections
        self.calls = 0

    def event_evidence_projection(self, **_: Any) -> dict[str, Any]:
        index = min(self.calls, len(self.projections) - 1)
        self.calls += 1
        return self.projections[index]


def _projection_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    basis = packet["snapshot_basis"]
    return {
        "schema_version": "event-evidence-projection-v1",
        "contract_type": "event_evidence_projection",
        "event_id": basis["event_id"],
        "evidence_id": f"EVD-{basis['event_id']}",
        "subject": {"equipment_id": basis["asset_id"], "asset_type": "cnc"},
        "artifact_reference": {
            "event_id": basis["event_id"],
            "artifact_id": basis["artifact_id"],
            "asset_id": basis["asset_id"],
            "asset_type": "cnc",
            "observed_at": basis["observed_at"],
            "evidence_payload_reference": basis["evidence_payload_reference"],
            "source_sha256": basis.get("source_sha256"),
        },
        "assessment": {
            "risk_grade": (packet.get("risk_summary") or {}).get("status_grade"),
            "operational_decision_kind": "review",
        },
        "report_projection": {"recommended_actions": []},
        "provenance": {
            "model_version": basis["model_version"],
            "dataset_version": basis["dataset_version"],
            "lineage": {"source_sha256": basis.get("source_sha256")},
        },
    }


def _mutate_projection(
    projection: dict[str, Any], *, scenario: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = deepcopy(projection)
    artifact = current["artifact_reference"]
    assessment = current["assessment"]
    transition: dict[str, Any] = {"scenario": scenario, "decision_relevance_changed": True}

    artifact["artifact_id"] = f"{artifact['artifact_id']}#T1#{scenario}"
    artifact["evidence_payload_reference"] = artifact["artifact_id"]
    artifact["observed_at"] = "2026-09-02T14:30:00+09:00"

    if scenario == "risk_escalation":
        transition.update({"from": assessment.get("risk_grade"), "to": "critical"})
        assessment["risk_grade"] = "critical"
        assessment["operational_decision_kind"] = "urgent_review"
    elif scenario == "risk_recovery":
        transition.update({"from": assessment.get("risk_grade"), "to": "normal"})
        assessment["risk_grade"] = "normal"
        assessment["operational_decision_kind"] = "monitor"
    elif scenario == "artifact_replacement":
        transition.update({"from": projection["artifact_reference"]["artifact_id"], "to": artifact["artifact_id"]})
    elif scenario == "evidence_history_update":
        transition.update({"from": "no_new_maintenance_evidence", "to": "new_maintenance_evidence"})
        current["maintenance_history_revision"] = "T1-new-work-order"
    else:
        raise ValueError(f"unknown scenario: {scenario}")
    return current, transition


def _basis(projection: dict[str, Any]) -> EvidenceSnapshotBasis:
    return EvidenceSnapshotBasis.model_validate(
        MaintenanceLoopService._projection_snapshot_basis(projection)
    )


def _b3_acceptance(
    *, expected: EvidenceSnapshotBasis, projections: list[dict[str, Any]]
) -> tuple[bool, list[str], int]:
    query = SequencedProjectionQuery(projections)
    loop = object.__new__(MaintenanceLoopService)
    loop.event_evidence_query = query
    try:
        loop._event_evidence_projection(
            organization_id="eval-org",
            project_id="eval-project",
            workspace_id="eval-workspace",
            event_id=expected.event_id or "",
            snapshot_basis=expected,
        )
        return True, [], query.calls
    except ValueError as exc:
        message = str(exc)
        fields = []
        if message.startswith("snapshot_basis mismatch:"):
            fields = [item.strip() for item in message.split(":", 1)[1].split(",")]
        return False, fields, query.calls


def run_fault_suite() -> dict[str, Any]:
    manifest = json.loads((GOLD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    packets = [json.loads((ROOT / case["fixture_path"]).read_text(encoding="utf-8")) for case in manifest["cases"]]
    rows: list[dict[str, Any]] = []
    for packet in packets:
        t0 = _projection_from_packet(packet)
        expected = _basis(t0)
        for scenario in SCENARIOS:
            t1, transition = _mutate_projection(t0, scenario=scenario)
            mismatch_fields = MaintenanceLoopService._snapshot_basis_mismatches(
                expected=expected, projection=t1
            )
            for arm in ARMS:
                if arm == "B3":
                    accepted, detected_fields, reads = _b3_acceptance(
                        expected=expected, projections=[t1, t1]
                    )
                    guard_applied = True
                else:
                    accepted, detected_fields, reads = True, [], 0
                    guard_applied = False
                rows.append(
                    {
                        "fixture_id": packet["snapshot_basis"]["event_id"].replace("EVT-", ""),
                        "arm": arm,
                        "scenario": scenario,
                        "t0_snapshot_basis": expected.model_dump(mode="json"),
                        "t1_snapshot_basis": MaintenanceLoopService._projection_snapshot_basis(t1),
                        "transition": transition,
                        "decision_relevance_changed": transition["decision_relevance_changed"],
                        "production_mismatch_fields": mismatch_fields,
                        "snapshot_guard_applied": guard_applied,
                        "snapshot_mismatch_detected": bool(detected_fields),
                        "detected_mismatch_fields": detected_fields,
                        "projection_read_count": reads,
                        "stale_candidate_generated": True,
                        "stale_candidate_accepted": accepted,
                        "stale_output_blocked": not accepted,
                        "simulated_side_effect_allowed": accepted,
                        "temporal_gold_at_accept": {
                            "value": None,
                            "state": "not_measured",
                            "reason": "existing gold answers are point-in-time fixture rubrics, not T1 transition rubrics",
                        },
                    }
                )
    return {
        "status": "measured",
        "execution_kind": "deterministic_temporal_fault_simulation",
        "case_count": len(packets),
        "scenario_count": len(SCENARIOS),
        "sample_size": len(rows),
        "rows": rows,
        "aggregate": aggregate(rows),
    }


def run_recovery_suite() -> dict[str, Any]:
    manifest = json.loads((GOLD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    packets = [json.loads((ROOT / case["fixture_path"]).read_text(encoding="utf-8")) for case in manifest["cases"]]
    rows = []
    for packet in packets:
        current = _projection_from_packet(packet)
        expected = _basis(current)
        stale, _ = _mutate_projection(current, scenario="artifact_replacement")
        accepted, mismatch_fields, reads = _b3_acceptance(
            expected=expected, projections=[stale, current]
        )
        rows.append(
            {
                "fixture_id": packet["snapshot_basis"]["event_id"].replace("EVT-", ""),
                "arm": "B3",
                "accepted_after_requery": accepted,
                "terminal_mismatch_fields": mismatch_fields,
                "projection_read_count": reads,
                "recovered_fresh_state": accepted and reads == 2,
            }
        )
    return {
        "sample_size": len(rows),
        "rows": rows,
        "fresh_state_recovery_rate": sum(row["recovered_fresh_state"] for row in rows) / len(rows),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, Any] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        stale = [row for row in arm_rows if row["stale_candidate_generated"]]
        by_arm[arm] = {
            "runs": len(arm_rows),
            "stale_candidate_generated_rate": len(stale) / len(arm_rows),
            "stale_candidate_accepted_rate": sum(row["stale_candidate_accepted"] for row in stale) / len(stale),
            "snapshot_mismatch_detection_rate": sum(row["snapshot_mismatch_detected"] for row in stale) / len(stale),
            "stale_output_block_rate": sum(row["stale_output_blocked"] for row in stale) / len(stale),
            "simulated_stale_side_effect_allow_rate": sum(row["simulated_side_effect_allowed"] for row in stale) / len(stale),
            "production_snapshot_guard_applied_rate": sum(row["snapshot_guard_applied"] for row in arm_rows) / len(arm_rows),
        }
    return {
        "by_arm": by_arm,
        "comparison_order": ["B3-B1", "B2-B1", "B3-B2"],
        "interpretation_boundary": (
            "B1/B2 side-effect allowance is simulated at the acceptance boundary. "
            "B3 mismatch detection/requery uses MaintenanceLoopService production snapshot logic."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate temporal consistency across B1/B2/B3.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_fault_suite()
    result["recovery"] = run_recovery_suite()
    output = args.output or ROOT / "tests" / "eval" / "results" / "agent_workflow_temporal_consistency.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sample_size": result["sample_size"], "aggregate": result["aggregate"], "recovery": {"sample_size": result["recovery"]["sample_size"], "fresh_state_recovery_rate": result["recovery"]["fresh_state_recovery_rate"]}}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Typed Report projection for Diagnosis-owned Evidence."""

from __future__ import annotations

from typing import Any, Mapping

from .report_schema import (
    ReportConversationActivity,
    ReportDecisionActivity,
    ReportDiagnosisActivity,
    ReportDiagnosisEquipment,
    ReportDiagnosisEvidence,
    ReportDiagnosisEvidenceSnapshot,
    ReportDiagnosisFactor,
    ReportNoteActivity,
)


def _rows(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def project_diagnosis_evidence_snapshot(
    *,
    event: Mapping[str, Any],
    evidence: Mapping[str, Any],
    activity: Mapping[str, Any],
) -> ReportDiagnosisEvidenceSnapshot:
    equipment = event.get("equipment") if isinstance(event.get("equipment"), Mapping) else {}
    model = evidence.get("model") if isinstance(evidence.get("model"), Mapping) else {}
    lineage = evidence.get("lineage") if isinstance(evidence.get("lineage"), Mapping) else {}
    interval = (
        evidence.get("detected_interval")
        if isinstance(evidence.get("detected_interval"), Mapping)
        else {}
    )

    factors = [
        ReportDiagnosisFactor(
            evidence_field_id=str(item.get("evidence_field_id") or ""),
            feature=str(item.get("feature") or ""),
            display_name=str(item.get("display_name") or item.get("feature") or ""),
            value=item.get("value") if isinstance(item.get("value"), (str, int, float, bool)) else None,
            unit=str(item["unit"]) if item.get("unit") is not None else None,
            direction=str(item["direction"]) if item.get("direction") is not None else None,
            contribution=float(item["contribution"]) if item.get("contribution") is not None else None,
            source_type=str(item["source_type"]) if item.get("source_type") is not None else None,
        )
        for item in _rows(evidence.get("top_factors"))
    ]

    decisions = [
        ReportDecisionActivity(
            id=str(item.get("id") or ""),
            actor=str(item.get("actor") or ""),
            decision=str(item.get("decision") or ""),
            note=str(item.get("note") or ""),
            created_at=str(item.get("created_at") or ""),
        )
        for item in _rows(activity.get("decisions"))
    ]
    notes = [
        ReportNoteActivity(
            id=str(item.get("id") or ""),
            actor=str(item.get("actor") or ""),
            body=str(item.get("body") or ""),
            created_at=str(item.get("created_at") or ""),
        )
        for item in _rows(activity.get("notes"))
    ]
    conversations = [
        ReportConversationActivity(
            id=str(item.get("id") or ""),
            thread_id=str(item.get("thread_id") or ""),
            role=str(item.get("role") or ""),
            question=str(item.get("question") or ""),
            intent=str(item.get("intent") or ""),
            answer=str(item.get("answer") or ""),
            created_at=str(item.get("created_at") or ""),
        )
        for item in _rows(activity.get("conversations"))
    ]

    warnings = evidence.get("data_quality_warnings")
    return ReportDiagnosisEvidenceSnapshot(
        event_id=str(event.get("event_id") or evidence.get("event_id") or ""),
        project_id=str(event.get("project_id") or lineage.get("project_id") or ""),
        scenario_id=str(event.get("scenario_id") or ""),
        equipment=ReportDiagnosisEquipment(
            equipment_id=str(equipment.get("equipment_id") or ""),
            display_name=str(equipment["display_name"]) if equipment.get("display_name") is not None else None,
            line=str(equipment["line"]) if equipment.get("line") is not None else None,
            criticality=str(equipment["criticality"]) if equipment.get("criticality") is not None else None,
            assigned_engineer=(
                str(equipment["assigned_engineer"])
                if equipment.get("assigned_engineer") is not None
                else None
            ),
        ),
        evidence=ReportDiagnosisEvidence(
            evidence_id=str(evidence.get("evidence_id") or ""),
            event_id=str(evidence.get("event_id") or event.get("event_id") or ""),
            status=str(evidence.get("status") or ""),
            recommended_decision=str(evidence.get("recommended_decision") or ""),
            confidence=str(evidence.get("confidence") or ""),
            failure_probability=(
                float(evidence["failure_probability"])
                if evidence.get("failure_probability") is not None
                else None
            ),
            threshold=float(evidence["threshold"]) if evidence.get("threshold") is not None else None,
            predicted_failure_type=(
                str(evidence["predicted_failure_type"])
                if evidence.get("predicted_failure_type") is not None
                else None
            ),
            model_version=str(model["model_version"]) if model.get("model_version") is not None else None,
            policy_version=str(model["policy_version"]) if model.get("policy_version") is not None else None,
            dataset_version=(
                str(lineage["dataset_version"]) if lineage.get("dataset_version") is not None else None
            ),
            detected_interval_start=str(interval["start"]) if interval.get("start") is not None else None,
            detected_interval_end=str(interval["end"]) if interval.get("end") is not None else None,
            top_factors=factors,
            data_quality_warnings=[str(item) for item in warnings] if isinstance(warnings, list) else [],
            generated_at=str(evidence["generated_at"]) if evidence.get("generated_at") is not None else None,
        ),
        activity=ReportDiagnosisActivity(
            decisions=decisions,
            notes=notes,
            conversations=conversations,
        ),
    )


__all__ = ["project_diagnosis_evidence_snapshot"]

"""Canonical Maintenance materialization rules."""

from __future__ import annotations

import uuid
from collections.abc import Collection

from app.diagnosis.recommendation_schema import ProducerRecommendation

from .maintenance_schema import (
    EquipmentIdentity,
    MaterializationStrategy,
    OperationalRecommendedAction,
)


def deterministic_recommendation_id(producer: ProducerRecommendation) -> str:
    return f"REC-{uuid.uuid5(uuid.NAMESPACE_URL, producer.materialization_key)}"


def materialize_recommended_action(
    producer: ProducerRecommendation,
    *,
    recommendation_id: str | None = None,
    identity: EquipmentIdentity,
    event_id: str,
    materialization_strategy: MaterializationStrategy = MaterializationStrategy.RUNTIME_GENERATED,
    existing_materialization_keys: Collection[str] = (),
) -> OperationalRecommendedAction:
    """Validate runtime producer output and add Maintenance workflow identity."""

    if materialization_strategy is not MaterializationStrategy.RUNTIME_GENERATED:
        raise ValueError("only runtime_generated producer recommendations can be operationalized")
    if producer.kind == "unavailable":
        raise ValueError("unavailable is not a recommendation kind to materialize")
    if producer.materialization_key in existing_materialization_keys:
        raise ValueError(f"recommendation already materialized: {producer.materialization_key}")
    return OperationalRecommendedAction(
        organization_id=identity.organization_id,
        project_id=identity.project_id,
        workspace_id=identity.workspace_id,
        recommendation_id=recommendation_id or deterministic_recommendation_id(producer),
        materialization_strategy=MaterializationStrategy.RUNTIME_GENERATED,
        asset_id=identity.asset_id,
        equipment_id=identity.equipment_id,
        event_id=event_id,
        source_action_id=producer.source_action_id,
        source_product_result_id=producer.source_product_result_id,
        source_evidence_id=producer.source_evidence_id,
        source_schema_version=producer.source_schema_version,
        source_policy_version=producer.source_policy_version,
        label=producer.label,
        kind=producer.kind,
        requires_human_approval=producer.requires_human_approval,
        basis=producer.basis,
    )


def validate_single_dataset_writer(dataset_version_id: str, writers: Collection[str]) -> str:
    del dataset_version_id
    normalized = {str(writer) for writer in writers if str(writer)}
    if len(normalized) != 1:
        raise ValueError("one Dataset Version must have exactly one materialization writer")
    writer = next(iter(normalized))
    if writer not in {item.value for item in MaterializationStrategy}:
        raise ValueError(f"unsupported materialization_strategy: {writer}")
    return writer


def imported_result_detail_view(result_artifact: dict, *, evidence_detail: dict | None) -> dict:
    """Preserve imported result/recommendation while marking only detail unavailable."""

    return {
        "materialization_strategy": MaterializationStrategy.IMPORTED_PRECOMPUTED.value,
        "result_artifact": result_artifact,
        "recommendations": list((result_artifact.get("evidence_payload") or {}).get("recommended_actions") or []),
        "schema_version": result_artifact.get("schema_version"),
        "provenance": result_artifact.get("provenance") or {},
        "evidence_detail": evidence_detail
        if evidence_detail is not None
        else {"status": "unavailable", "reason": "imported_result_artifact_missing_evidence_detail"},
    }

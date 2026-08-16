from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from ontology_dashboard import dependencies
from ontology_dashboard.adapters.models import (
    DataQuality,
    EvidenceSource,
    PredictionEvidence,
    PredictionModel,
    PredictionResult,
    PredictionSubject,
    PredictionValue,
)
from ontology_dashboard.predictive_maintenance_runtime.models import (
    DashboardEquipment,
    DatasetVersionRuntimeContext,
    GovernedProductResult,
    GovernanceProvenance,
    GraphReadiness,
    PolicyRecommendation,
    ProductFactor,
    ProductResultProvenance,
    SemanticQueryCapability,
    SensorObservation,
)
from ontology_dashboard.predictive_maintenance_runtime.service import (
    PredictiveMaintenanceRuntimeService,
)
from ontology_dashboard.product_result_evidence_projection import (
    event_evidence_projection_to_legacy_evidence,
    product_result_artifact_to_event_evidence_projection,
)


def test_predictive_maintenance_runtime_reports_postgresql_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    dependencies.get_predictive_maintenance_runtime_service.cache_clear()
    monkeypatch.setattr(
        dependencies,
        "database_target",
        lambda: str(tmp_path / "ontology-dashboard.sqlite3"),
    )
    monkeypatch.setattr(dependencies, "migrate", lambda _target: ())

    try:
        with pytest.raises(HTTPException) as captured:
            dependencies.get_predictive_maintenance_runtime_service()
    finally:
        dependencies.get_predictive_maintenance_runtime_service.cache_clear()

    assert captured.value.status_code == 503
    assert "UCI AI4I 2020 Manufacturing Predictive Maintenance" in str(captured.value.detail)
    assert "requires PostgreSQL" in str(captured.value.detail)


def test_runtime_dashboard_result_artifact_projects_to_event_evidence() -> None:
    observed_at = datetime(2026, 8, 6, 1, 30, tzinfo=timezone.utc)
    checksum = "a" * 64
    context = DatasetVersionRuntimeContext(
        organization_id="org-test",
        project_id="project-test",
        workspace_id="workspace-test",
        dataset_id="dataset-test",
        dataset_version_id="dataset-version-test",
        source_version="canonical-ai4i-physics-v3.1",
        bundle_checksum_sha256=checksum,
        version_number=1,
        record_count=10,
        dataset_status="published",
        model_version="independent-logreg-v3.1",
        result_artifact_schema_version="result-artifact-v1.0",
        prediction_task="binary_failure_within_horizon",
        governance=GovernanceProvenance(),
        graph=GraphReadiness(status="ready"),
        semantic_query=SemanticQueryCapability(
            dimensions=["asset_id"],
            canonical_measures=["failure_probability"],
            derived_measures={},
            latest_result_contract="result_artifact",
            supported_grains=["raw"],
        ),
    )
    result = GovernedProductResult(
        source_contract="result_artifact",
        artifact_id="RESULT#CMP-001#2026-08-06T01:30:00+00:00",
        asset_id="CMP-001",
        asset_type="compressor",
        site_id="S01",
        cell_id="L03",
        observed_at=observed_at,
        prediction_horizon_hours=24,
        prediction_task="binary_failure_within_horizon",
        failure_probability=0.82,
        predicted_failure_type="failure_risk",
        status_grade="warning",
        confidence=0.76,
        top_factors=[
            ProductFactor(
                rank=1,
                feature="rotation_raw",
                feature_value=1120.0,
                signed_contribution=0.52,
                direction="risk_up",
                explanation_method="result_artifact_factor",
            ),
            ProductFactor(
                rank=2,
                feature="pressure_raw",
                feature_value=3.2,
                signed_contribution=0.31,
                direction="risk_up",
                explanation_method="result_artifact_factor",
            ),
            ProductFactor(
                rank=3,
                feature="voltage_raw",
                feature_value=221.0,
                signed_contribution=-0.12,
                direction="risk_down",
                explanation_method="result_artifact_factor",
            ),
        ],
        recommended_action=PolicyRecommendation(action="inspect_within_current_shift", priority="high"),
        provenance=ProductResultProvenance(
            dataset_id="dataset-test",
            dataset_version_id="dataset-version-test",
            source_version="canonical-ai4i-physics-v3.1",
            bundle_checksum_sha256=checksum,
            result_artifact_source_sha256=checksum,
            prediction_id="prediction-test",
            prediction_result_id="prediction-result-test",
            model_version="independent-logreg-v3.1",
            schema_version="result-artifact-v1.0",
            prediction_task="binary_failure_within_horizon",
            source_type="derived_result_artifact",
        ),
        governance=GovernanceProvenance(),
        graph=GraphReadiness(status="ready"),
        prediction_result=PredictionResult(
            prediction_id="prediction-result-test",
            organization_id="org-test",
            project_id="project-test",
            workspace_id="workspace-test",
            subject=PredictionSubject(object_type="equipment", object_id="CMP-001", observed_at=observed_at),
            prediction=PredictionValue(
                task="classification",
                status="warning",
                label="failure_risk",
                score=0.82,
                confidence=0.76,
                horizon="24h",
                value="failure_risk",
            ),
            evidence=[
                PredictionEvidence(
                    evidence_id="artifact:RESULT#CMP-001",
                    kind="artifact",
                    label="Governed Result Artifact",
                    value={"source_contract": "result_artifact"},
                    source=EvidenceSource(system="test", reference="fixture"),
                )
            ],
            model=PredictionModel(
                provider="canonical-predictive-maintenance",
                model_name="independent-logreg",
                model_version="independent-logreg-v3.1",
                dataset_version="canonical-ai4i-physics-v3.1",
            ),
            data_quality=DataQuality(status="pass"),
            created_at=observed_at,
        ),
    )
    equipment = DashboardEquipment(
        equipment_id="CMP-001",
        display_name="COMPRESSOR · CMP-001",
        line="S01 / L03",
        criticality="high",
        assigned_engineer="Unassigned · policy review",
        last_maintenance_date="No recorded maintenance",
        estimated_downtime_minutes=120,
    )
    observation = {
        "timestamp": observed_at.isoformat(),
        "product_type": "compressor",
        "rotation_raw": 1120.0,
        "pressure_raw": 3.2,
        "voltage_raw": 221.0,
    }
    service = PredictiveMaintenanceRuntimeService(repository=None)  # type: ignore[arg-type]

    artifact = service._dashboard_result_artifact(
        project_id="project-test",
        workspace_id="workspace-test",
        context=context,
        result=result,
        equipment=equipment,
        observation=observation,
        history=[observation],
        maintenance_context=None,
        window_start=observed_at - timedelta(hours=6),
    )
    projection = product_result_artifact_to_event_evidence_projection(artifact)
    projection["event_id"] = "RESULT#CMP-001#2026-08-06T01:30:00+00:00"
    evidence = event_evidence_projection_to_legacy_evidence(
        projection,
        ranked_factor_evidence=artifact["ranked_factor_evidence"],
    )

    assert artifact["evidence_payload"]["evidence_gaps"][0]["gap_id"] == "gap.maintenance_context.unavailable"
    assert projection["contract_type"] == "event_evidence_projection"
    assert projection["assessment"]["recommended_decision"] == "request_inspection"
    assert service._dashboard_summary_recommended_decision(
        context=context,
        result=result,
        equipment=equipment,
    ) == "request_inspection"
    assert evidence["lineage"]["dataset_version_id"] == "dataset-version-test"
    assert evidence["lineage"]["product_result_artifact"]["artifact_id"] == artifact["artifact_id"]
    assert evidence["top_factors"][0]["evidence_field_id"] == "factor.1.rotation_raw"


def test_runtime_dashboard_history_excludes_current_observation_from_baseline_history() -> None:
    observed_at = datetime(2026, 8, 6, 1, 30, tzinfo=timezone.utc)
    previous_at = observed_at - timedelta(minutes=10)
    checksum = "b" * 64
    service = PredictiveMaintenanceRuntimeService(repository=None)  # type: ignore[arg-type]
    result = GovernedProductResult(
        source_contract="result_artifact",
        artifact_id="RESULT#CMP-001#2026-08-06T01:30:00+00:00",
        asset_id="CMP-001",
        asset_type="compressor",
        site_id="S01",
        cell_id="L03",
        observed_at=observed_at,
        prediction_horizon_hours=24,
        prediction_task="binary_failure_within_horizon",
        failure_probability=0.82,
        predicted_failure_type="failure_risk",
        status_grade="warning",
        confidence=0.76,
        top_factors=[
            ProductFactor(
                rank=1,
                feature="rotation_raw",
                feature_value=1120.0,
                signed_contribution=0.52,
                direction="risk_up",
                explanation_method="result_artifact_factor",
            ),
            ProductFactor(
                rank=2,
                feature="pressure_raw",
                feature_value=3.2,
                signed_contribution=0.31,
                direction="risk_up",
                explanation_method="result_artifact_factor",
            ),
            ProductFactor(
                rank=3,
                feature="voltage_raw",
                feature_value=221.0,
                signed_contribution=-0.12,
                direction="risk_down",
                explanation_method="result_artifact_factor",
            ),
        ],
        recommended_action=PolicyRecommendation(action="request_inspection", priority="high"),
        provenance=ProductResultProvenance(
            dataset_id="dataset-test",
            dataset_version_id="dataset-version-test",
            source_version="canonical-ai4i-physics-v3.1",
            bundle_checksum_sha256=checksum,
            result_artifact_source_sha256=checksum,
            prediction_id="prediction-test",
            prediction_result_id="prediction-result-test",
            model_version="independent-logreg-v3.1",
            schema_version="result-artifact-v1.0",
            prediction_task="binary_failure_within_horizon",
            source_type="derived_result_artifact",
        ),
        governance=GovernanceProvenance(),
        graph=GraphReadiness(status="ready"),
        prediction_result=PredictionResult(
            prediction_id="prediction-result-test",
            organization_id="org-test",
            project_id="project-test",
            workspace_id="workspace-test",
            subject=PredictionSubject(object_type="equipment", object_id="CMP-001", observed_at=observed_at),
            prediction=PredictionValue(
                task="classification",
                status="warning",
                label="failure_risk",
                score=0.82,
                confidence=0.76,
                horizon="24h",
                value="failure_risk",
            ),
            evidence=[
                PredictionEvidence(
                    evidence_id="artifact:RESULT#CMP-001",
                    kind="artifact",
                    label="Governed Result Artifact",
                    value={"source_contract": "result_artifact"},
                    source=EvidenceSource(system="test", reference="fixture"),
                )
            ],
            model=PredictionModel(
                provider="canonical-predictive-maintenance",
                model_name="independent-logreg",
                model_version="independent-logreg-v3.1",
                dataset_version="canonical-ai4i-physics-v3.1",
            ),
            data_quality=DataQuality(status="pass"),
            created_at=observed_at,
        ),
    )
    observations = [
        SensorObservation(
            observed_at=previous_at,
            asset_id="CMP-001",
            asset_type="compressor",
            site_id="S01",
            cell_id="L03",
            is_operating=True,
            operating_state="running",
            source_sha256=checksum,
            measurements={"rotation_raw": 1000.0},
        ),
        SensorObservation(
            observed_at=observed_at,
            asset_id="CMP-001",
            asset_type="compressor",
            site_id="S01",
            cell_id="L03",
            is_operating=True,
            operating_state="running",
            source_sha256=checksum,
            measurements={"rotation_raw": 1120.0},
        ),
    ]

    history, observation = service._dashboard_history_and_observation(observations, result)

    assert observation["timestamp"] == observed_at.isoformat()
    assert [row["timestamp"] for row in history] == [previous_at.isoformat()]

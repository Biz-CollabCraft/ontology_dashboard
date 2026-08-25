"""Comprehensive test suite for the Generator Runtime Prediction Pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_config import PATHS, GeneratorPaths
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.model.publisher import ModelArtifactPublisher
from systems.generator.app.main import app
from systems.generator.app.runtime_pipeline.aggregation_service import AggregationService
from systems.generator.app.runtime_pipeline.notification_service import NotificationService
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineAssetIdMissingError,
    PipelineDuplicateInputError,
    PipelineHistoryInsufficientError,
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineJobNotFailedError,
    PipelineNoActiveModelError,
    PipelineNotificationRetryExhaustedError,
    PipelinePathNotAllowedError,
    PipelineStateTransitionInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_manager import PipelineManager
from systems.generator.app.runtime_pipeline.pipeline_queue import PipelineQueue
from systems.generator.app.runtime_pipeline.pipeline_repository import PipelineRepository
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    AnomalySignalPayload,
    ArtifactReference,
    ModelPredictionResult,
    PipelineQueueItem,
    PipelineRunState,
)
from systems.generator.app.runtime_pipeline.pipeline_service import PipelineService
from systems.generator.app.runtime_pipeline.pipeline_state import PipelineStateManager
from systems.generator.app.runtime_pipeline.pipeline_worker import PipelineWorker
from systems.generator.app.runtime_pipeline.prediction_service import PredictionService
from systems.generator.app.runtime_pipeline.runtime_feature_service import RuntimeFeatureService


class MockEstimator:
    """Mock ML model for controlled anomaly score output."""

    def __init__(self, anomaly_prob: float = 0.1) -> None:
        self.anomaly_prob = anomaly_prob

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = len(X)
        probs = np.zeros((n, 2))
        probs[:, 0] = 1.0 - self.anomaly_prob
        probs[:, 1] = self.anomaly_prob
        return probs

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


@pytest.fixture
def isolated_runtime_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated environment with mock models, database, and directories."""
    data_dir = tmp_path / "data"
    incoming_dir = data_dir / "incoming"
    preprocessed_dir = tmp_path / "data_preprocessed"
    models_store = tmp_path / "models_store"
    artifacts_dir = models_store / "artifacts"
    features_cache_dir = models_store / "cache" / "runtime_features"
    outbox_dir = preprocessed_dir / "notification_outbox"

    for d in [data_dir, incoming_dir, preprocessed_dir, models_store, artifacts_dir, features_cache_dir, outbox_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Monkeypatch PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "data_preprocessed", preprocessed_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)
    monkeypatch.setattr(PATHS, "pipeline_input_roots", [data_dir, preprocessed_dir, tmp_path])
    monkeypatch.setattr(PATHS, "runtime_feature_root", features_cache_dir)
    monkeypatch.setattr(PATHS, "notification_outbox_root", outbox_dir)
    monkeypatch.setattr(PATHS, "pipeline_queue_db", preprocessed_dir / "pipeline_queue" / "queue.db")
    monkeypatch.setattr(PATHS, "pipeline_state_root", preprocessed_dir / "pipeline_runs")

    publisher = ModelArtifactPublisher(artifacts_dir)

    feature_schema = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-feature-schema.schema.json",
        "schema_version": "1.0",
        "features": [
            {
                "feature_name": "feat_air_temp",
                "source_field": "Air temperature [K]",
                "operation": "raw",
                "parameters": {},
                "missing_value_policy": "drop",
            },
            {
                "feature_name": "feat_air_temp_lag1",
                "source_field": "Air temperature [K]",
                "operation": "lag",
                "parameters": {"periods": 1},
                "missing_value_policy": "fill_zero",
            },
            {
                "feature_name": "feat_process_temp",
                "source_field": "Process temperature [K]",
                "operation": "raw",
                "parameters": {},
                "missing_value_policy": "drop",
            },
            {
                "feature_name": "feat_rot_speed",
                "source_field": "Rotational speed [rpm]",
                "operation": "raw",
                "parameters": {},
                "missing_value_policy": "drop",
            },
        ],
    }

    label_schema = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-label-schema.schema.json",
        "schema_version": "1.0",
        "prediction_horizon_hours": 12,
        "target_type": "binary_failure_within_horizon",
    }

    hist_req = {
        "minimum_history_rows": 2,
        "required_columns": [
            "Air temperature [K]",
            "Process temperature [K]",
            "Rotational speed [rpm]",
        ],
        "missing_history_policy": "reject",
    }

    metrics = {
        "metrics_summary": {"f1": 0.88, "precision": 0.90, "recall": 0.86, "accuracy": 0.98},
        "primary_metric": "f1",
    }

    # Model default probabilities: lightgbm=normal(0.1), xgboost=anomaly(0.85), random_forest=anomaly(0.75)
    model_probs = {
        "pdm-lightgbm": 0.1,
        "pdm-xgboost": 0.85,
        "pdm-random_forest": 0.75,
    }
    base_map = {
        "pdm-lightgbm": "lightgbm",
        "pdm-xgboost": "xgboost",
        "pdm-random_forest": "random_forest",
    }

    for model_id, prob in model_probs.items():
        dummy_model = MockEstimator(anomaly_prob=prob)
        publisher.publish_artifact(
            model_id=model_id,
            model_version=f"{model_id}-v1.0",
            base_model=base_map[model_id],
            model_obj=dummy_model,
            dataset_id="canonical-ai4i-v1",
            dataset_version="canonical-ai4i-physics-v3.1",
            feature_dataset_version="feat-v1",
            feature_schema=feature_schema,
            label_schema=label_schema,
            history_requirement=hist_req,
            metrics=metrics,
            training_config={
                "training_config_version": "train-cfg-v1",
                "training_config_sha256": "0" * 64,
                "training_config_uri": "models_store/configs/train-cfg-v1.json",
                "hyperparameters": {},
            },
            provenance={
                "dataset_id": "canonical-ai4i-v1",
                "dataset_version": "canonical-ai4i-physics-v3.1",
                "feature_dataset_version": "feat-v1",
                "feature_dataset_metadata_sha256": "1" * 64,
                "feature_schema_sha256": "2" * 64,
                "label_schema_sha256": "3" * 64,
                "prediction_horizon_hours": 12,
            },
        )

    queue = PipelineQueue(db_path=preprocessed_dir / "pipeline_queue" / "queue.db")
    repository = PipelineRepository(base_dir=preprocessed_dir)
    feat_service = RuntimeFeatureService(cache_dir=features_cache_dir)
    pred_service = PredictionService(
        models_store_dir=artifacts_dir,
        publisher=publisher,
    )
    agg_service = AggregationService()

    sent_signals = []

    class MockNotificationService(NotificationService):
        def send_notification(self, payload: AnomalySignalPayload):
            self.save_to_outbox(payload, status="sent")
            sent_signals.append(payload)
            return {"delivered": True, "status_code": 200}

    notif_service = MockNotificationService(outbox_dir=outbox_dir)
    service = PipelineService(
        repository=repository,
        preprocessing_service=None,
        runtime_feature_service=feat_service,
        prediction_service=pred_service,
        aggregation_service=agg_service,
        notification_service=notif_service,
    )
    worker = PipelineWorker(queue=queue, service=service, max_attempts=5, retry_backoff_seconds=0.01)
    manager = PipelineManager(queue=queue, repository=repository, service=service)

    return {
        "tmp_path": tmp_path,
        "incoming_dir": incoming_dir,
        "artifacts_dir": artifacts_dir,
        "preprocessed_dir": preprocessed_dir,
        "outbox_dir": outbox_dir,
        "publisher": publisher,
        "queue": queue,
        "repository": repository,
        "feat_service": feat_service,
        "pred_service": pred_service,
        "service": service,
        "worker": worker,
        "manager": manager,
        "sent_signals": sent_signals,
    }


def create_sample_observation_jsonl(file_path: Path, num_rows: int = 5, asset_id: str = "M14860") -> tuple[Path, str]:
    """Helper creating valid JSONL observation file with asset_id and timestamps."""
    records = []
    for i in range(num_rows):
        records.append({
            "UDI": i + 1,
            "Product ID": f"{asset_id}_{i+1:04d}",
            "asset_id": asset_id,
            "Type": "M",
            "Air temperature [K]": 298.1 + i * 0.1,
            "Process temperature [K]": 308.6 + i * 0.1,
            "Rotational speed [rpm]": 1551 - i * 10,
            "Torque [Nm]": 42.8 + i * 0.5,
            "Tool wear [min]": i * 5,
            "timestamp": f"2026-08-25T10:{i:02d}:00Z",
        })
    content = "\n".join(json.dumps(r) for r in records) + "\n"
    file_path.write_text(content, encoding="utf-8")
    sha256 = compute_file_sha256(file_path)
    return file_path, sha256


# =====================================================================
# 1. Stage Separation & Preprocessing Dataset Publishing Test
# =====================================================================

def test_full_pipeline_5_stages_and_dataset_publishing(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "obs_01.jsonl", num_rows=5)

    item = env["queue"].enqueue(
        job_id="job-stage-test-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is not None
    assert run_state.status == "succeeded"

    # Verify 5 distinct stages exist
    assert "preprocessing" in run_state.stages
    assert "runtime_feature" in run_state.stages
    assert "prediction" in run_state.stages
    assert "aggregation" in run_state.stages
    assert "notification" in run_state.stages

    # Preprocessing stage must publish both plan and preprocessed dataset
    prep_stage = run_state.stages["preprocessing"]
    assert prep_stage.status == "succeeded"
    roles = [r.role for r in prep_stage.output_refs]
    assert "preprocessing_plan" in roles
    assert "preprocessed_dataset" in roles

    # Verify preprocessed dataset file physically exists
    dataset_ref = next(r for r in prep_stage.output_refs if r.role == "preprocessed_dataset")
    assert Path(dataset_ref.uri).is_file()

    # Runtime feature stage
    feat_stage = run_state.stages["runtime_feature"]
    assert feat_stage.status == "succeeded"
    assert len(feat_stage.output_refs) == 3
    for r in feat_stage.output_refs:
        assert r.role == "runtime_features"
        assert Path(r.uri).is_file()

    # Notification stage & signal
    assert run_state.anomaly_detected is True
    assert run_state.notification_status == "sent"
    assert len(env["sent_signals"]) == 1


# =====================================================================
# 2. Equipment-Isolated Runtime Feature Calculation Test
# =====================================================================

def test_equipment_isolated_feature_calculation(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Create mixed observation file with 2 assets: A and B
    records = [
        # Asset A rows
        {"asset_id": "Asset_A", "Air temperature [K]": 300.0, "Process temperature [K]": 310.0, "Rotational speed [rpm]": 1500, "timestamp": "2026-08-25T10:00:00Z"},
        {"asset_id": "Asset_A", "Air temperature [K]": 305.0, "Process temperature [K]": 315.0, "Rotational speed [rpm]": 1510, "timestamp": "2026-08-25T10:01:00Z"},
        # Asset B rows
        {"asset_id": "Asset_B", "Air temperature [K]": 400.0, "Process temperature [K]": 410.0, "Rotational speed [rpm]": 1600, "timestamp": "2026-08-25T10:00:00Z"},
        {"asset_id": "Asset_B", "Air temperature [K]": 405.0, "Process temperature [K]": 415.0, "Rotational speed [rpm]": 1610, "timestamp": "2026-08-25T10:01:00Z"},
    ]
    src_file = incoming / "mixed_assets.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-asset-iso-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is not None
    assert run_state.status == "succeeded"

    # Check that lag1 for first row of Asset_B is fill_zero (0.0), NOT 305.0 from Asset_A!
    feat_stage = run_state.stages["runtime_feature"]
    feat_ref = feat_stage.output_refs[0]
    matrix = np.load(Path(feat_ref.uri))

    # Column 0 = feat_air_temp, Column 1 = feat_air_temp_lag1
    # Row 0: Asset_A row 1 -> lag1 is 0.0 (fill_zero)
    # Row 1: Asset_A row 2 -> lag1 is 300.0
    # Row 2: Asset_B row 1 -> lag1 MUST BE 0.0, NEVER 305.0 from Asset_A!
    # Row 3: Asset_B row 2 -> lag1 is 400.0
    assert matrix[0, 1] == 0.0
    assert matrix[1, 1] == 300.0
    assert matrix[2, 1] == 0.0, f"Asset leak detected! Expected 0.0, got {matrix[2, 1]}"
    assert matrix[3, 1] == 400.0


def test_missing_asset_id_fails_closed(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Observation data with NO asset ID column
    records = [
        {"Air temperature [K]": 300.0, "Process temperature [K]": 310.0, "Rotational speed [rpm]": 1500, "timestamp": "2026-08-25T10:00:00Z"},
        {"Air temperature [K]": 305.0, "Process temperature [K]": 315.0, "Rotational speed [rpm]": 1510, "timestamp": "2026-08-25T10:01:00Z"},
    ]
    src_file = incoming / "no_id.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-no-id-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is None
    # Verify queue item marked failed immediately (retryable=False)
    q_items = env["queue"].list_items(status="failed")
    assert len(q_items) == 1
    assert q_items[0].error_code == "PIPELINE_ASSET_ID_MISSING"


# =====================================================================
# 3. Non-Retryable vs Retryable (Max 5 Attempts) Tests
# =====================================================================

def test_non_retryable_error_fails_immediately(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "corrupt.jsonl", num_rows=1)

    # Only 1 row -> PIPELINE_HISTORY_INSUFFICIENT (non-retryable)
    item = env["queue"].enqueue(
        job_id="job-non-retry-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    # Single process call should mark it directly as failed
    run_state = env["worker"].process_one()
    assert run_state is None

    items = env["queue"].list_items()
    assert len(items) == 1
    assert items[0].status == "failed"
    assert items[0].attempt == 1


def test_retryable_error_retries_up_to_max_attempts(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "retry_test.jsonl", num_rows=5)

    # Monkeypatch notification service to always fail with 500 server error (retryable)
    from systems.generator.app.runtime_pipeline.pipeline_exception import PipelineNotificationServerError

    class AlwaysFailingNotif(NotificationService):
        def send_notification(self, payload):
            raise PipelineNotificationServerError("Temporary 500 server error")

    env["service"].notification_service = AlwaysFailingNotif(outbox_dir=env["outbox_dir"])


    item = env["queue"].enqueue(
        job_id="job-retry-loop-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    # Attempts 1 to 4 should transition to queued/retry_wait
    for att in range(1, 5):
        run = env["worker"].process_one()
        assert run is None
        items = env["queue"].list_items()
        assert items[0].status == "queued"
        assert items[0].attempt == att + 1

    # Attempt 5 should fail definitively
    run = env["worker"].process_one()
    assert run is None
    items = env["queue"].list_items()
    assert items[0].status == "failed"
    assert items[0].attempt == 5


# =====================================================================
# 4. Failed Job Re-enqueue (retry_failed_job) Transaction Test
# =====================================================================

def test_retry_failed_job_transaction(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "re_enqueue.jsonl", num_rows=1)

    # 1. Enqueue and let it fail
    item = env["queue"].enqueue(
        job_id="job-fail-first",
        source_uri=str(src_file),
        source_checksum=sha256,
    )
    env["worker"].process_one()

    failed_items = env["queue"].list_items(status="failed")
    assert len(failed_items) == 1

    # 2. Call retry_failed_job
    new_item = env["queue"].retry_failed_job("job-fail-first")
    assert new_item.status == "queued"
    assert new_item.retry_of_job_id == "job-fail-first"
    assert new_item.attempt == 1
    assert "retry" in new_item.job_id

    # 3. Cannot re-enqueue a succeeded job
    succeeded_file, s_sha = create_sample_observation_jsonl(incoming / "succ.jsonl", num_rows=5)
    s_item = env["queue"].enqueue(
        job_id="job-succ",
        source_uri=str(succeeded_file),
        source_checksum=s_sha,
    )
    env["worker"].process_one()

    with pytest.raises(PipelineJobNotFailedError):
        env["queue"].retry_failed_job("job-succ")


# =====================================================================
# 5. Path Allowed Roots & Path Traversal Security Test
# =====================================================================

def test_path_security_and_allowed_roots(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # 1. Path traversal rejected
    with pytest.raises(PipelinePathNotAllowedError):
        env["service"].execute_queue_item(
            PipelineQueueItem(
                job_id="job-trav",
                source_uri="../outside.jsonl",
                source_checksum="0" * 64,
            )
        )

    # 2. Outside allowed roots rejected
    outside_file = Path("C:/Windows/temp/outside.jsonl") if os.name == "nt" else Path("/tmp/outside.jsonl")
    with pytest.raises(PipelinePathNotAllowedError):
        env["service"].execute_queue_item(
            PipelineQueueItem(
                job_id="job-outside",
                source_uri=str(outside_file),
                source_checksum="0" * 64,
            )
        )


# =====================================================================
# 6. FastAPI Router Endpoints Test
# =====================================================================

def test_runtime_pipeline_router_api_with_retry_failed(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "api_test.jsonl", num_rows=5)

    PipelineManager.set_instance(env["manager"])
    client = TestClient(app)

    # 1. Enqueue endpoint
    resp = client.post(
        "/internal/runtime-pipeline/enqueue",
        json={
            "job_id": "job-api-01",
            "source_uri": str(src_file),
            "source_checksum": sha256,
            "dataset_id": "canonical-ai4i-v1",
            "dataset_version": "canonical-ai4i-physics-v3.1",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-api-01"

    # 2. Queue list
    resp_q = client.get("/runtime-pipeline/queue")
    assert resp_q.status_code == 200
    assert len(resp_q.json()) >= 1

    # 3. Status endpoint
    resp_stat = client.get("/runtime-pipeline/status")
    assert resp_stat.status_code == 200
    assert "queued_count" in resp_stat.json()

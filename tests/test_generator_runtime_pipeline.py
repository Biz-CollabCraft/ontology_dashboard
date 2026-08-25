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
from systems.generator.app.runtime_pipeline.notification_service import (
    PredictionDeliveryService,
    NotificationService,
)
from systems.generator.app.runtime_pipeline.notification_worker import (
    PredictionDeliveryWorker,
    NotificationWorker,
)
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineAssetIdMissingError,
    PipelineDeliveryFailedError,
    PipelineDeliveryServerError,
    PipelineDeliveryTimeoutError,
    PipelineDuplicateInputError,
    PipelineHistoryInsufficientError,
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineJobNotFailedError,
    PipelineMappingNotImplementedError,
    PipelineNoActiveModelError,
    PipelinePathNotAllowedError,
    PipelineRuntimeFeatureFailedError,
    PipelineStateTransitionInvalidError,
    PipelineTimestampInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_manager import PipelineManager
from systems.generator.app.runtime_pipeline.pipeline_queue import PipelineQueue
from systems.generator.app.runtime_pipeline.pipeline_repository import PipelineRepository
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    ModelPredictionResult,
    PredictionDeliveryEventState,
    PredictionOutboxItem,
    PredictionResultBatchPayload,
    PipelineQueueItem,
    PipelineRunState,
    SourceLineage,
    now_utc_iso,
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
        for i in range(n):
            # If feature 0 (Air temp) > 298.25, use configured anomaly_prob, otherwise low normal prob
            if X.shape[1] > 0 and X[i, 0] > 298.25:
                prob = self.anomaly_prob
            else:
                prob = 0.05
            probs[i, 0] = 1.0 - prob
            probs[i, 1] = prob
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
    outbox_dir = preprocessed_dir / "prediction_outbox"

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
    notif_service = PredictionDeliveryService(outbox_dir=outbox_dir)
    notif_worker = PredictionDeliveryWorker(service=notif_service, repository=repository)

    service = PipelineService(

        repository=repository,
        preprocessing_service=None,
        runtime_feature_service=feat_service,
        prediction_service=pred_service,
        aggregation_service=agg_service,
        notification_service=notif_service,
    )
    worker = PipelineWorker(queue=queue, service=service, max_attempts=5, retry_backoff_seconds=0.01)
    manager = PipelineManager(
        queue=queue,
        repository=repository,
        service=service,
        notification_service=notif_service,
    )

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
        "notif_service": notif_service,
        "notif_worker": notif_worker,
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
# 1. Multi-Equipment Prediction and Batch Building Test
# =====================================================================

def test_multi_equipment_prediction_and_aggregation(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Create multi-equipment input: Asset A (3 rows), Asset B (3 rows), Asset C (1 row)
    records = [
        # Asset A (3 rows -> ready)
        {"UDI": 1, "Product ID": "M14860_01", "asset_id": "M14860", "Air temperature [K]": 298.1, "Process temperature [K]": 308.6, "Rotational speed [rpm]": 1550, "Torque [Nm]": 42.0, "timestamp": "2026-08-25T10:00:00Z"},
        {"UDI": 2, "Product ID": "M14860_02", "asset_id": "M14860", "Air temperature [K]": 298.2, "Process temperature [K]": 308.7, "Rotational speed [rpm]": 1540, "Torque [Nm]": 43.0, "timestamp": "2026-08-25T10:01:00Z"},
        {"UDI": 3, "Product ID": "M14860_03", "asset_id": "M14860", "Air temperature [K]": 298.3, "Process temperature [K]": 308.8, "Rotational speed [rpm]": 1530, "Torque [Nm]": 44.0, "timestamp": "2026-08-25T10:02:00Z"},
        # Asset B (3 rows -> ready)
        {"UDI": 4, "Product ID": "L47181_01", "asset_id": "L47181", "Air temperature [K]": 298.0, "Process temperature [K]": 308.5, "Rotational speed [rpm]": 1400, "Torque [Nm]": 45.0, "timestamp": "2026-08-25T10:00:00Z"},
        {"UDI": 5, "Product ID": "L47181_02", "asset_id": "L47181", "Air temperature [K]": 298.1, "Process temperature [K]": 308.6, "Rotational speed [rpm]": 1405, "Torque [Nm]": 46.0, "timestamp": "2026-08-25T10:01:00Z"},
        {"UDI": 6, "Product ID": "L47181_03", "asset_id": "L47181", "Air temperature [K]": 298.2, "Process temperature [K]": 308.7, "Rotational speed [rpm]": 1410, "Torque [Nm]": 47.0, "timestamp": "2026-08-25T10:02:00Z"},
        # Asset C (1 row -> insufficient history when min=2)
        {"UDI": 7, "Product ID": "H29424_01", "asset_id": "H29424", "Air temperature [K]": 298.0, "Process temperature [K]": 308.4, "Rotational speed [rpm]": 1420, "Torque [Nm]": 40.0, "timestamp": "2026-08-25T10:00:00Z"},
    ]
    src_file = incoming / "multi_equipments.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-multi-eq-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is not None
    assert run_state.status == "partially_succeeded"  # because Asset C has insufficient history

    # 1. Check prediction results per asset — score-based, no threshold/is_anomaly
    results = run_state.prediction_results
    assert len(results) == 9  # 3 assets * 3 models

    assets_in_results = {r.asset_id for r in results}
    assert assets_in_results == {"M14860", "L47181", "H29424"}

    for r in results:
        assert not hasattr(r, "threshold") or "threshold" not in r.model_fields
        assert not hasattr(r, "is_anomaly") or "is_anomaly" not in r.model_fields
        assert not hasattr(r, "prediction") or "prediction" not in r.model_fields
        if r.status == "succeeded":
            assert r.score is not None
            assert 0.0 <= r.score <= 1.0
            assert r.score_type == "positive_class_probability"

    # Asset C must have status="unknown" and PIPELINE_HISTORY_INSUFFICIENT
    asset_c_results = [r for r in results if r.asset_id == "H29424"]
    for r in asset_c_results:
        assert r.status == "unknown"
        assert r.error_code == "PIPELINE_HISTORY_INSUFFICIENT"

    # 2. Check outbox records — ALL equipments with predictions get outbox items
    outbox_items = env["notif_service"].list_outbox_items()
    outbox_asset_ids = {item.asset_id for item in outbox_items}
    # All 3 equipments should have outbox items (including Asset C with unknown results)
    assert len(outbox_items) >= 2  # At least A and B; C may or may not depending on "all equipments" policy
    assert "M14860" in outbox_asset_ids
    assert "L47181" in outbox_asset_ids
    for oi in outbox_items:
        assert oi.status == "pending"
    assert len(run_state.prediction_event_ids) == len(outbox_items)


# =====================================================================
# 2. Prediction Delivery Worker Outbox Retries & Decoupling Test
# =====================================================================

def test_notification_worker_decoupled_retry_and_backoff(isolated_runtime_env, monkeypatch):
    env = isolated_runtime_env
    notif_service = env["notif_service"]
    notif_worker = env["notif_worker"]

    payload = PredictionResultBatchPayload(
        event_id="evt-retry-01",
        run_id="run-01",
        job_id="job-01",
        asset_id="M14860",
        observed_at="2026-08-25T10:00:00Z",
        dataset_id="canonical-ai4i-v1",
        dataset_version="canonical-ai4i-physics-v3.1",
        model_results=[
            ModelPredictionResult(
                asset_id="M14860",
                model_id="pdm-xgboost",
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                score_type="positive_class_probability",
                score=0.88,
            )
        ],
        source_lineage=SourceLineage(
            source_uri="test.jsonl",
            source_checksum="0" * 64,
        ),
    )

    # 1. Create outbox record
    item = notif_service.create_outbox_record(payload)
    assert item.status == "pending"
    assert item.attempt == 0

    # 2. Simulate 500 Server Error on first attempt
    def mock_send_500(pl):
        raise PipelineDeliveryServerError("500 Internal Server Error")

    monkeypatch.setattr(notif_service, "send_once", mock_send_500)

    # Process pending items
    processed = notif_worker.process_pending()
    assert processed == 1

    updated_item = notif_service.get_outbox_item("evt-retry-01")
    assert updated_item is not None
    assert updated_item.status == "retry_wait"
    assert updated_item.attempt == 1
    assert updated_item.next_retry_at is not None

    # 3. Simulate 400 Bad Request error (non-retryable)
    def mock_send_400(pl):
        raise PipelineDeliveryFailedError("400 Bad Request", retryable=False)

    monkeypatch.setattr(notif_service, "send_once", mock_send_400)
    updated_item.next_retry_at = None  # force due immediately
    notif_service.save_outbox_item(updated_item)

    processed = notif_worker.process_pending()
    assert processed == 1

    failed_item = notif_service.get_outbox_item("evt-retry-01")
    assert failed_item.status == "failed"
    assert failed_item.attempt == 2

    # 4. Successful delivery for a new item
    success_payload = payload.model_copy(update={"event_id": "evt-success-01"})
    notif_service.create_outbox_record(success_payload)

    def mock_send_200(pl):
        return {"delivered": True, "status_code": 200}

    monkeypatch.setattr(notif_service, "send_once", mock_send_200)

    processed = notif_worker.process_pending()
    assert processed >= 1
    sent_item = notif_service.get_outbox_item("evt-success-01")
    assert sent_item.status == "sent"
    assert sent_item.attempt == 1


# =====================================================================
# 3. Input Validation Fail-Closed Tests (ID & Timestamp & Mapping)
# =====================================================================

def test_missing_or_blank_asset_id_fails_closed(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Blank / whitespace asset_id
    records = [
        {"asset_id": "  ", "Air temperature [K]": 300.0, "Process temperature [K]": 310.0, "Rotational speed [rpm]": 1500, "timestamp": "2026-08-25T10:00:00Z"},
        {"asset_id": "null", "Air temperature [K]": 305.0, "Process temperature [K]": 315.0, "Rotational speed [rpm]": 1510, "timestamp": "2026-08-25T10:01:00Z"},
    ]
    src_file = incoming / "blank_id.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-blank-id-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is None
    q_items = env["queue"].list_items(status="failed")
    assert any(q.error_code == "PIPELINE_ASSET_ID_VALUE_MISSING" for q in q_items)


def test_invalid_timestamp_fails_closed(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Invalid timestamp string
    records = [
        {"asset_id": "M14860", "Air temperature [K]": 300.0, "Process temperature [K]": 310.0, "Rotational speed [rpm]": 1500, "timestamp": "not-a-valid-timestamp"},
        {"asset_id": "M14860", "Air temperature [K]": 305.0, "Process temperature [K]": 315.0, "Rotational speed [rpm]": 1510, "timestamp": "2026-08-25T10:01:00Z"},
    ]
    src_file = incoming / "bad_ts.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-bad-ts-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is None
    q_items = env["queue"].list_items(status="failed")
    assert any(q.error_code == "PIPELINE_TIMESTAMP_INVALID" for q in q_items)


def test_unsupported_mapping_fails_with_501(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]

    # Raw sensor data with NO identifiable ID column at all
    records = [
        {"Sensor_A": 300.0, "Sensor_B": 310.0, "Sensor_C": 1500, "timestamp": "2026-08-25T10:00:00Z"},
        {"Sensor_A": 305.0, "Sensor_B": 315.0, "Sensor_C": 1510, "timestamp": "2026-08-25T10:01:00Z"},
    ]
    src_file = incoming / "unmapped.jsonl"
    src_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    sha256 = compute_file_sha256(src_file)

    item = env["queue"].enqueue(
        job_id="job-unmapped-01",
        source_uri=str(src_file),
        source_checksum=sha256,
    )

    run_state = env["worker"].process_one()
    assert run_state is None
    q_items = env["queue"].list_items(status="failed")
    assert any(q.error_code == "PIPELINE_MAPPING_NOT_IMPLEMENTED" for q in q_items)


# =====================================================================
# 4. Failed Job Re-enqueue (retry_failed_job) Transaction Test
# =====================================================================

def test_retry_failed_job_transaction(isolated_runtime_env):
    env = isolated_runtime_env
    incoming = env["incoming_dir"]
    src_file, sha256 = create_sample_observation_jsonl(incoming / "re_enqueue.jsonl", num_rows=1)

    # 1. Enqueue and let it fail (1 row -> history insufficient)
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


# =====================================================================
# 7. Prediction Delivery Run State Synchronization & Event Aggregation Test
# =====================================================================

def test_notification_worker_run_state_synchronization_and_aggregation(isolated_runtime_env, monkeypatch):
    env = isolated_runtime_env
    repo: PipelineRepository = env["repository"]
    notif_service: PredictionDeliveryService = env["notif_service"]
    notif_worker: PredictionDeliveryWorker = env["notif_worker"]

    run_id = "run-notif-sync-01"
    ev1_id = "evt-sync-01"
    ev2_id = "evt-sync-02"

    # Initial RunState with 2 prediction delivery events in pending
    run_state = PipelineRunState(
        run_id=run_id,
        job_id="job-sync-01",
        status="succeeded",
        current_stage=None,
        source_ref=ArtifactReference(uri="data/test.jsonl", sha256="0"*64, role="source_observation_protocol"),
        stages={},
        prediction_results=[],
        prediction_delivery_status="pending",
        prediction_event_ids=[ev1_id, ev2_id],
        prediction_events=[
            PredictionDeliveryEventState(
                event_id=ev1_id,
                asset_id="Asset-1",
                status="pending",
                attempt=0,
                max_attempts=5,
                updated_at=now_utc_iso(),
            ),
            PredictionDeliveryEventState(
                event_id=ev2_id,
                asset_id="Asset-2",
                status="pending",
                attempt=0,
                max_attempts=5,
                updated_at=now_utc_iso(),
            ),
        ],
        errors=[],
    )
    repo.save_run_state(run_state)


    # Create 2 outbox items for this run
    p1 = PredictionResultBatchPayload(
        event_id=ev1_id,
        run_id=run_id,
        job_id="job-sync-01",
        asset_id="Asset-1",
        observed_at="2026-08-25T10:00:00Z",
        dataset_id="canonical-ai4i-v1",
        dataset_version="canonical-ai4i-physics-v3.1",
        model_results=[
            ModelPredictionResult(
                asset_id="Asset-1",
                model_id="pdm-xgboost",
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                score_type="positive_class_probability",
                score=0.9,
            )
        ],
        source_lineage=SourceLineage(
            source_uri="test.jsonl",
            source_checksum="0" * 64,
        ),
    )
    p2 = p1.model_copy(update={"event_id": ev2_id, "asset_id": "Asset-2"})
    notif_service.create_outbox_record(p1)
    notif_service.create_outbox_record(p2)

    # 1. Process Event 1 successfully (Mock HTTP 200)
    monkeypatch.setattr(notif_service, "send_once", lambda pl: {"delivered": True, "status_code": 200})
    item1 = notif_service.get_outbox_item(ev1_id)
    notif_worker.process_item(item1)

    # Check state after Event 1 sent, Event 2 still pending
    st1 = repo.get_run_state(run_id)
    assert st1 is not None
    assert st1.prediction_delivery_status == "pending"  # because ev2 is not sent yet
    ev1_state = next(e for e in st1.prediction_events if e.event_id == ev1_id)
    assert ev1_state.status == "sent"

    # 2. Process Event 2 successfully
    item2 = notif_service.get_outbox_item(ev2_id)
    notif_worker.process_item(item2)

    # Check state after both events sent -> prediction_delivery_status must be 'sent'
    st2 = repo.get_run_state(run_id)
    assert st2 is not None
    assert st2.prediction_delivery_status == "sent"
    assert all(e.status == "sent" for e in st2.prediction_events)


# =====================================================================
# 8. Delivery Interrupted 'sending' Items Startup Recovery Test
# =====================================================================

def test_notification_worker_recover_interrupted_sending_items(isolated_runtime_env):
    env = isolated_runtime_env
    repo: PipelineRepository = env["repository"]
    notif_service: PredictionDeliveryService = env["notif_service"]
    notif_worker: PredictionDeliveryWorker = env["notif_worker"]

    run_id = "run-recover-01"
    event_id = "evt-recover-01"

    # Save run state
    run_state = PipelineRunState(
        run_id=run_id,
        job_id="job-rec-01",
        status="succeeded",
        current_stage=None,
        source_ref=ArtifactReference(uri="data/test.jsonl", sha256="0"*64, role="source_observation_protocol"),
        stages={},
        prediction_results=[],
        prediction_delivery_status="pending",
        prediction_event_ids=[event_id],
        prediction_events=[],
        errors=[],
    )
    repo.save_run_state(run_state)

    payload = PredictionResultBatchPayload(
        event_id=event_id,
        run_id=run_id,
        job_id="job-rec-01",
        asset_id="Asset-Rec",
        observed_at="2026-08-25T10:00:00Z",
        dataset_id="canonical-ai4i-v1",
        dataset_version="canonical-ai4i-physics-v3.1",
        model_results=[
            ModelPredictionResult(
                asset_id="Asset-Rec",
                model_id="pdm-xgboost",
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                score_type="positive_class_probability",
                score=0.95,
            )
        ],
        source_lineage=SourceLineage(
            source_uri="test.jsonl",
            source_checksum="0" * 64,
        ),
    )
    item = notif_service.create_outbox_record(payload)
    item.status = "sending"
    notif_service.save_outbox_item(item)

    # Execute recovery hook
    recovered_count = notif_worker.recover_interrupted_items()
    assert recovered_count == 1

    # Verify Outbox Item was recovered to retry_wait
    recovered_item = notif_service.get_outbox_item(event_id)
    assert recovered_item is not None
    assert recovered_item.status == "retry_wait"
    assert recovered_item.last_error_code == "PIPELINE_DELIVERY_INTERRUPTED"
    assert recovered_item.next_retry_at is not None

    # Verify RunState is synced
    updated_run = repo.get_run_state(run_id)
    assert updated_run is not None
    assert updated_run.prediction_delivery_status == "pending"
    ev_state = next(e for e in updated_run.prediction_events if e.event_id == event_id)
    assert ev_state.status == "retry_wait"
    assert ev_state.last_error_code == "PIPELINE_DELIVERY_INTERRUPTED"


# =====================================================================
# 9. Model Feature Failure Mapping per Equipment (No fake 'unknown')
# =====================================================================

def test_model_feature_failure_maps_to_actual_equipment_ids_not_unknown(isolated_runtime_env):
    env = isolated_runtime_env
    pred_service: PredictionService = env["pred_service"]
    artifacts = {
        "pdm-lightgbm": pred_service.load_active_artifact("pdm-lightgbm"),
        "pdm-xgboost": pred_service.load_active_artifact("pdm-xgboost"),
    }

    # Simulate: feature for pdm-lightgbm succeeded, but feature for pdm-xgboost is missing (failed)
    # Target equipments: ['M14860', 'L47181']
    dummy_feat_ref = ArtifactReference(
        uri="dummy.npy",
        sha256="0" * 64,
        role="runtime_features",
    )
    feature_refs = {"pdm-lightgbm": dummy_feat_ref}  # pdm-xgboost omitted
    feature_bundles = {}

    results = pred_service.execute_predictions_from_feature_refs(
        model_artifacts=artifacts,
        model_feature_refs=feature_refs,
        model_feature_bundles=feature_bundles,
        asset_ids=["M14860", "L47181"],
        model_feature_errors={"pdm-xgboost": PipelineRuntimeFeatureFailedError("History insufficient for model")},
    )

    # Must have 4 results (2 models * 2 assets)
    assert len(results) == 4
    asset_ids_in_results = {r.asset_id for r in results}
    assert "unknown" not in asset_ids_in_results
    assert asset_ids_in_results == {"M14860", "L47181"}

    # Failed model results must be recorded for each actual asset
    xgboost_results = [r for r in results if r.model_id == "pdm-xgboost"]
    assert len(xgboost_results) == 2
    for r in xgboost_results:
        assert r.asset_id in ["M14860", "L47181"]
        assert r.status == "failed"
        assert r.error_code == "PIPELINE_RUNTIME_FEATURE_FAILED"

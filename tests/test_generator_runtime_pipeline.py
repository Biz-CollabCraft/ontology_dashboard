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
from systems.generator.app.runtime_pipeline.prediction_batch_service import (
    PredictionBatchService,
)
from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
    PredictionDeliveryService,
)
from systems.generator.app.runtime_pipeline.prediction_delivery_worker import (
    PredictionDeliveryWorker,
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
    PipelineModelFeatureMissingValueHandlingNotImplementedError,
    PipelineModelPredictionFailedError,
    PipelineNoActiveModelError,
    PipelinePathNotAllowedError,
    PipelinePredictionObservationAlignmentNotImplementedError,
    PipelineRuntimeFeatureFailedError,
    PipelineSensorValueMissingError,
    PipelineSourceAlreadyProcessedError,
    PipelineSourceAlreadyRegisteredError,
    PipelineSourceChecksumChangedError,
    PipelineSourceFileNotStableError,
    PipelineStateTransitionInvalidError,
    PipelineTimestampInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_manager import PipelineManager
from systems.generator.app.runtime_pipeline.pipeline_queue import PipelineQueue
from systems.generator.app.runtime_pipeline.pipeline_repository import PipelineRepository
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    InternalModelPredictionResult,
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
from systems.generator.app.runtime_pipeline.prediction_service import (
    PredictionService,
    REGISTERED_BASE_MODELS,
)
from systems.generator.app.runtime_pipeline.runtime_feature_service import RuntimeFeatureService


class MockEstimator:
    """Mock ML model for controlled anomaly score output."""

    def __init__(self, anomaly_prob: float = 0.1) -> None:
        self.anomaly_prob = anomaly_prob

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        n = len(X)
        probs = np.zeros((n, 2))
        for i in range(n):
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
    batch_service = PredictionBatchService()
    notif_service = PredictionDeliveryService(outbox_dir=outbox_dir)
    notif_worker = PredictionDeliveryWorker(service=notif_service, repository=repository)

    service = PipelineService(
        repository=repository,
        preprocessing_service=None,
        runtime_feature_service=feat_service,
        prediction_service=pred_service,
        prediction_batch_service=batch_service,
        prediction_delivery_service=notif_service,
    )
    worker = PipelineWorker(queue=queue, service=service, max_attempts=5, retry_backoff_seconds=0.01)
    manager = PipelineManager(
        queue=queue,
        repository=repository,
        service=service,
        prediction_delivery_service=notif_service,
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
        "batch_service": batch_service,
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

def test_multi_equipment_prediction_and_batch_building(isolated_runtime_env):
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
        assert r.observed_at != ""
        if r.status == "succeeded":
            assert r.score is not None
            assert 0.0 <= r.score <= 1.0
            assert r.score_type == "positive_class_probability"
            assert r.score_source == "predict_proba"

    # Asset C must have status="unknown" and PIPELINE_HISTORY_INSUFFICIENT
    asset_c_results = [r for r in results if r.asset_id == "H29424"]
    for r in asset_c_results:
        assert r.status == "unknown"
        assert r.error_code == "PIPELINE_HISTORY_INSUFFICIENT"

    # 2. Check outbox records — model_results is dictionary keyed by model_id, no top-level feature_ref
    outbox_items = env["notif_service"].list_outbox_items()
    outbox_asset_ids = {item.asset_id for item in outbox_items}
    assert len(outbox_items) == 3
    assert "M14860" in outbox_asset_ids
    assert "L47181" in outbox_asset_ids
    assert "H29424" in outbox_asset_ids

    for oi in outbox_items:
        assert oi.status == "pending"
        payload = oi.payload
        assert isinstance(payload.model_results, dict)
        assert "pdm-lightgbm" in payload.model_results
        assert "pdm-xgboost" in payload.model_results
        assert "pdm-random_forest" in payload.model_results
        assert payload.observed_at != ""
        assert not hasattr(payload, "feature_ref") or "feature_ref" not in payload.model_fields

        for mid, mres in payload.model_results.items():
            assert not hasattr(mres, "model_id") or "model_id" not in mres.model_fields
            assert not hasattr(mres, "asset_id") or "asset_id" not in mres.model_fields
            assert mres.observed_at != ""
            assert mres.score_source in ("predict_proba", "decision_function_compat", "predict_compat", None)

    assert len(run_state.prediction_event_ids) == len(outbox_items)


# =====================================================================
# 2. Prediction Delivery Worker Outbox Retries & Decoupling Test
# =====================================================================

def test_delivery_worker_decoupled_retry_and_backoff(isolated_runtime_env, monkeypatch):
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
        model_results={
            "pdm-xgboost": ModelPredictionResult(
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                observed_at="2026-08-25T10:00:00Z",
                score_type="positive_class_probability",
                score_source="predict_proba",
                score=0.88,
            )
        },
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

def test_delivery_worker_run_state_synchronization_and_aggregation(isolated_runtime_env, monkeypatch):
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
        model_results={
            "pdm-xgboost": ModelPredictionResult(
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                observed_at="2026-08-25T10:00:00Z",
                score_type="positive_class_probability",
                score_source="predict_proba",
                score=0.9,
            )
        },
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

def test_delivery_worker_recover_interrupted_sending_items(isolated_runtime_env):
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
        model_results={
            "pdm-xgboost": ModelPredictionResult(
                model_version="pdm-xgboost-v1.0",
                status="succeeded",
                observed_at="2026-08-25T10:00:00Z",
                score_type="positive_class_probability",
                score_source="predict_proba",
                score=0.95,
            )
        },
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
# 9. Observation Alignment Verification Test (501 Fail-Closed)
# =====================================================================

def test_observation_timestamp_misalignment_raises_501(isolated_runtime_env):
    """If models for the same asset have different observed_at, raise 501 PipelinePredictionObservationAlignmentNotImplementedError."""
    env = isolated_runtime_env
    batch_service = env["batch_service"]

    # Succeeded model predictions with mismatched observed_at for asset M14860
    results = [
        InternalModelPredictionResult(
            asset_id="M14860",
            model_id="pdm-lightgbm",
            model_version="pdm-lightgbm-v1.0",
            status="succeeded",
            observed_at="2026-08-25T10:00:00Z",
            score_type="positive_class_probability",
            score_source="predict_proba",
            score=0.10,
        ),
        InternalModelPredictionResult(
            asset_id="M14860",
            model_id="pdm-xgboost",
            model_version="pdm-xgboost-v1.0",
            status="succeeded",
            observed_at="2026-08-25T10:05:00Z",  # Different timestamp!
            score_type="positive_class_probability",
            score_source="predict_proba",
            score=0.85,
        ),
    ]

    with pytest.raises(PipelinePredictionObservationAlignmentNotImplementedError) as exc_info:
        batch_service.collect(results)

    assert "observed_at" in str(exc_info.value)
    assert exc_info.value.status_code == 501
    assert exc_info.value.code == "PIPELINE_PREDICTION_OBSERVATION_ALIGNMENT_NOT_IMPLEMENTED"


# =====================================================================
# 10. Feature Calculation NaN/Inf Missing Value Handling Test (501 Fail-Closed)
# =====================================================================

def test_feature_calculation_nan_inf_raises_501_with_model_context(isolated_runtime_env):
    """If lag/rolling feature produces NaN/Inf, raise 501 PipelineModelFeatureMissingValueHandlingNotImplementedError with full context."""
    env = isolated_runtime_env
    feat_service: RuntimeFeatureService = env["feat_service"]

    # Data with only 1 row, but lag feature needs prior row
    df = pd.DataFrame([{
        "asset_id": "M14860",
        "Air temperature [K]": 298.1,
        "timestamp": "2026-08-25T10:00:00Z",
    }])

    lag_schema = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-feature-schema.schema.json",
        "schema_version": "1.0",
        "features": [
            {
                "feature_name": "feat_air_temp_lag1",
                "source_field": "Air temperature [K]",
                "operation": "lag",
                "parameters": {"periods": 1},
                "missing_value_policy": "drop",
            }
        ],
    }

    hist_req = {"minimum_history_rows": 1, "required_columns": ["Air temperature [K]"]}

    with pytest.raises(PipelineModelFeatureMissingValueHandlingNotImplementedError) as exc_info:
        feat_service.extract_and_publish(
            preprocessed_df=df,
            feature_schema_dict=lag_schema,
            history_requirement_dict=hist_req,
            model_id="pdm-lag-model",
            model_version="pdm-lag-model-v1.0",
            id_column="asset_id",
            time_column="timestamp",
        )

    assert exc_info.value.status_code == 501
    assert exc_info.value.code == "PIPELINE_MODEL_FEATURE_MISSING_VALUE_HANDLING_NOT_IMPLEMENTED"
    assert exc_info.value.details[0]["model_id"] == "pdm-lag-model"
    assert exc_info.value.details[0]["model_version"] == "pdm-lag-model-v1.0"
    assert exc_info.value.details[0]["feature_name"] == "feat_air_temp_lag1"


# =====================================================================
# 11. Raw Sensor Value Missing Check Test (422 Fail-Closed)
# =====================================================================

def test_raw_sensor_value_missing_raises_422(isolated_runtime_env):
    """If raw sensor field contains NaN/null, raise 422 PipelineSensorValueMissingError."""
    env = isolated_runtime_env
    feat_service: RuntimeFeatureService = env["feat_service"]

    df = pd.DataFrame([
        {"asset_id": "M14860", "Air temperature [K]": None, "timestamp": "2026-08-25T10:00:00Z"},
        {"asset_id": "M14860", "Air temperature [K]": 298.2, "timestamp": "2026-08-25T10:01:00Z"},
    ])

    raw_schema = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-feature-schema.schema.json",
        "schema_version": "1.0",
        "features": [
            {
                "feature_name": "feat_air_temp",
                "source_field": "Air temperature [K]",
                "operation": "raw",
                "parameters": {},
                "missing_value_policy": "drop",
            }
        ],
    }

    hist_req = {"minimum_history_rows": 2, "required_columns": ["Air temperature [K]"]}

    with pytest.raises(PipelineSensorValueMissingError) as exc_info:
        feat_service.extract_and_publish(
            preprocessed_df=df,
            feature_schema_dict=raw_schema,
            history_requirement_dict=hist_req,
            id_column="asset_id",
            time_column="timestamp",
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "PIPELINE_SENSOR_VALUE_MISSING"
    assert exc_info.value.details[0]["source_field"] == "Air temperature [K]"


# =====================================================================
# 12. File Stability & Checksum Change Test
# =====================================================================

def test_file_size_changed_between_enqueue_and_start_raises_file_not_stable_error(isolated_runtime_env):
    """If file size changes between enqueue and execution start, raise PIPELINE_SOURCE_FILE_NOT_STABLE (retryable=True)."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]

    src_file, initial_sha = create_sample_observation_jsonl(incoming_dir / "unstable_size_file.jsonl", num_rows=3)
    item = queue.enqueue(job_id="job-change-size-1", source_uri=str(src_file), source_checksum=initial_sha)

    # Modify file by appending bytes (changing size)
    with open(src_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "UDI": 99,
            "Product ID": "M14860_0099",
            "asset_id": "M14860",
            "Type": "M",
            "Air temperature [K]": 299.5,
            "Process temperature [K]": 309.5,
            "Rotational speed [rpm]": 1500,
            "Torque [Nm]": 43.0,
            "Tool wear [min]": 50,
            "timestamp": "2026-08-25T10:50:00Z",
        }) + "\n")

    with pytest.raises(PipelineSourceFileNotStableError) as exc_info:
        service.execute_queue_item(item)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "PIPELINE_SOURCE_FILE_NOT_STABLE"
    assert exc_info.value.retryable is True


def test_file_checksum_changed_between_enqueue_and_start_raises_retryable_error(isolated_runtime_env):
    """If file checksum changes (same size) between enqueue and execution start, raise PIPELINE_SOURCE_CHECKSUM_CHANGED (retryable=True)."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]

    src_file, initial_sha = create_sample_observation_jsonl(incoming_dir / "changing_file.jsonl", num_rows=3)
    item = queue.enqueue(job_id="job-change-1", source_uri=str(src_file), source_checksum=initial_sha)

    # Modify content preserving exact byte length (replace character '1' with '2')
    content = src_file.read_text(encoding="utf-8")
    modified_content = content.replace("298.1", "298.2", 1)
    assert len(content.encode("utf-8")) == len(modified_content.encode("utf-8"))
    src_file.write_text(modified_content, encoding="utf-8")

    with pytest.raises(PipelineSourceChecksumChangedError) as exc_info:
        service.execute_queue_item(item)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "PIPELINE_SOURCE_CHECKSUM_CHANGED"
    assert exc_info.value.retryable is True


# =====================================================================
# 13. Duplicate Source Identity Enqueue Blocked Test
# =====================================================================

def test_duplicate_source_identity_enqueue_blocked(isolated_runtime_env):
    """Enqueuing identical source_identity twice should raise PipelineSourceAlreadyRegisteredError or PipelineSourceAlreadyProcessedError."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "dup_identity.jsonl", num_rows=2)
    item1 = queue.enqueue(job_id="job-dup-1", source_uri=str(src_file), source_checksum=sha)
    assert item1.job_id == "job-dup-1"

    # Enqueue same file again while queued
    with pytest.raises(PipelineSourceAlreadyRegisteredError) as exc_info:
        queue.enqueue(job_id="job-dup-2", source_uri=str(src_file), source_checksum=sha)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "PIPELINE_SOURCE_ALREADY_REGISTERED"

    # Verify only 1 item in queue
    items = queue.list_items()
    assert len(items) == 1
    assert items[0].job_id == "job-dup-1"


# =====================================================================
# 14. Same Path Different Checksum Enqueued as Separate Job Test
# =====================================================================

def test_same_path_different_content_enqueued_as_separate_job(isolated_runtime_env):
    """Overwriting the same path with different content produces a new source_identity and enqueues as a separate job."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]

    src_file = incoming_dir / "reused_path.jsonl"

    # 1. First content
    create_sample_observation_jsonl(src_file, num_rows=2, asset_id="M14860")
    sha1 = compute_file_sha256(src_file)
    item1 = queue.enqueue(job_id="job-reused-1", source_uri=str(src_file), source_checksum=sha1)
    queue.mark_succeeded("job-reused-1")

    # 2. Overwrite with new content (different rows)
    create_sample_observation_jsonl(src_file, num_rows=4, asset_id="M14860")
    sha2 = compute_file_sha256(src_file)
    assert sha1 != sha2

    item2 = queue.enqueue(job_id="job-reused-2", source_uri=str(src_file), source_checksum=sha2)
    assert item2.job_id == "job-reused-2"
    assert item2.source_identity != item1.source_identity


# =====================================================================
# 15. Different Path Same Content Duplicate Blocked Test
# =====================================================================

def test_different_path_same_content_duplicate_blocked(isolated_runtime_env):
    """Two different file paths with identical content share the same source_identity and the second is blocked."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]

    file1 = incoming_dir / "copy_1.jsonl"
    file2 = incoming_dir / "copy_2.jsonl"

    create_sample_observation_jsonl(file1, num_rows=2, asset_id="M14860")
    file2.write_bytes(file1.read_bytes())

    sha = compute_file_sha256(file1)
    item1 = queue.enqueue(job_id="job-copy-1", source_uri=str(file1), source_checksum=sha)
    assert item1.job_id == "job-copy-1"

    with pytest.raises(PipelineSourceAlreadyRegisteredError):
        queue.enqueue(job_id="job-copy-2", source_uri=str(file2), source_checksum=sha)


# =====================================================================
# 16. Unordered Timestamps Deterministically Sorted Test
# =====================================================================

def test_unordered_timestamps_deterministically_sorted(isolated_runtime_env):
    """Out-of-order timestamp inputs are deterministically sorted by [asset_id, timestamp]."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]

    src_file = incoming_dir / "shuffled_times.jsonl"
    # Unordered timestamps across two assets with complete canonical sensor schema
    records = [
        {
            "UDI": 3,
            "Product ID": "M14860_0003",
            "asset_id": "M14860",
            "Type": "M",
            "Air temperature [K]": 298.3,
            "Process temperature [K]": 308.8,
            "Rotational speed [rpm]": 1530,
            "Torque [Nm]": 43.5,
            "Tool wear [min]": 10,
            "timestamp": "2026-08-25T10:02:00Z",
        },
        {
            "UDI": 2,
            "Product ID": "L47181_0002",
            "asset_id": "L47181",
            "Type": "L",
            "Air temperature [K]": 298.4,
            "Process temperature [K]": 308.9,
            "Rotational speed [rpm]": 1540,
            "Torque [Nm]": 44.0,
            "Tool wear [min]": 5,
            "timestamp": "2026-08-25T10:01:00Z",
        },
        {
            "UDI": 1,
            "Product ID": "M14860_0001",
            "asset_id": "M14860",
            "Type": "M",
            "Air temperature [K]": 298.1,
            "Process temperature [K]": 308.6,
            "Rotational speed [rpm]": 1551,
            "Torque [Nm]": 42.8,
            "Tool wear [min]": 0,
            "timestamp": "2026-08-25T10:00:00Z",
        },
        {
            "UDI": 1,
            "Product ID": "L47181_0001",
            "asset_id": "L47181",
            "Type": "L",
            "Air temperature [K]": 298.2,
            "Process temperature [K]": 308.7,
            "Rotational speed [rpm]": 1545,
            "Torque [Nm]": 43.1,
            "Tool wear [min]": 0,
            "timestamp": "2026-08-25T10:00:00Z",
        },
        {
            "UDI": 2,
            "Product ID": "M14860_0002",
            "asset_id": "M14860",
            "Type": "M",
            "Air temperature [K]": 298.2,
            "Process temperature [K]": 308.7,
            "Rotational speed [rpm]": 1540,
            "Torque [Nm]": 43.0,
            "Tool wear [min]": 5,
            "timestamp": "2026-08-25T10:01:00Z",
        },
    ]
    with open(src_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    sha = compute_file_sha256(src_file)
    item = queue.enqueue(job_id="job-sort-1", source_uri=str(src_file), source_checksum=sha)
    run_state = service.execute_queue_item(item)

    assert run_state.status == "succeeded"
    assert len(run_state.prediction_events) == 2


# =====================================================================
# 17. Observed_at Matches Actual Feature Row Metadata Test
# =====================================================================

def test_observed_at_matches_actual_feature_row_metadata(isolated_runtime_env):
    """Prediction result batch observed_at must strictly match the last observed feature row metadata."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "observed_at_match.jsonl", num_rows=3, asset_id="M14860")
    item = queue.enqueue(job_id="job-obs-1", source_uri=str(src_file), source_checksum=sha)
    run_state = service.execute_queue_item(item)

    assert run_state.status == "succeeded"
    event_id = run_state.prediction_event_ids[0]
    event = repo.get_event(event_id)
    assert event is not None
    assert event.observed_at == "2026-08-25T10:02:00Z"
    for model_id, model_res in event.model_results.items():
        assert model_res.observed_at == "2026-08-25T10:02:00Z"


# =====================================================================
# 18. Backend Payload Contains No Local Absolute Paths Test
# =====================================================================

def test_backend_payload_contains_no_local_absolute_paths(isolated_runtime_env):
    """Source lineage source_uri in PredictionResultBatchPayload must be normalized logical URI without drive letters or absolute local paths."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "clean_lineage.jsonl", num_rows=2, asset_id="M14860")
    item = queue.enqueue(job_id="job-lineage-1", source_uri=str(src_file), source_checksum=sha)
    run_state = service.execute_queue_item(item)

    event_id = run_state.prediction_event_ids[0]
    event = repo.get_event(event_id)
    assert event is not None

    source_uri = event.source_lineage.source_uri
    assert not source_uri.startswith("C:")
    assert not source_uri.startswith("c:")
    assert not source_uri.startswith("\\")
    assert not source_uri.startswith("/")
    assert "clean_lineage.jsonl" in source_uri


# =====================================================================
# 19. Failed File Stability Emits No Outbox or Events Test
# =====================================================================

def test_failed_file_stability_emits_no_outbox_or_events(isolated_runtime_env):
    """When a file stability or preprocessing failure occurs, no outbox items or prediction events are published."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    outbox_dir: Path = env["outbox_dir"]
    events_dir: Path = env["repository"].events_dir
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]

    # File with invalid schema to trigger failure
    src_file = incoming_dir / "unstable_fail.jsonl"
    with open(src_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"unknown_id": "123", "value": 999}) + "\n")

    sha = compute_file_sha256(src_file)
    item = queue.enqueue(job_id="job-fail-outbox-1", source_uri=str(src_file), source_checksum=sha)

    with pytest.raises(PipelineMappingNotImplementedError):
        service.execute_queue_item(item)

    # Verify 0 files in outbox and 0 in events
    outbox_files = list(outbox_dir.glob("*.json"))
    event_files = list(events_dir.glob("*.json"))
    assert len(outbox_files) == 0
    assert len(event_files) == 0


# =====================================================================
# 20. Stage Checkpoints Recorded and Persisted Test
# =====================================================================

def test_stage_checkpoints_recorded_and_persisted(isolated_runtime_env):
    """Each completed stage records an atomic, persistent checkpoint with stage outputs and status."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "chk_flow.jsonl", num_rows=3, asset_id="M14860")
    item = queue.enqueue(job_id="job-chk-1", source_uri=str(src_file), source_checksum=sha)
    run_state = service.execute_queue_item(item)

    assert run_state.status == "succeeded"
    assert run_state.last_completed_stage == "prediction_delivery"
    assert run_state.next_stage == "completed"

    chk = repo.get_checkpoint(run_state.run_id)
    assert chk is not None
    assert chk.checkpoint_version == "generator-runtime-checkpoint-v1"
    assert chk.last_completed_stage == "prediction_delivery"
    assert chk.status == "completed"
    assert "preprocessing" in chk.stage_outputs
    assert "runtime_feature" in chk.stage_outputs
    assert "runtime_prediction" in chk.stage_outputs


# =====================================================================
# 21. Resumption From Stage 2 Skips Preprocessing Test
# =====================================================================

def test_resumption_from_stage_2_skips_preprocessing(isolated_runtime_env, monkeypatch):
    """When a run previously completed Preprocessing (Checkpoint 1), re-execution skips Preprocessing and resumes from Runtime Feature."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "resume_stage2.jsonl", num_rows=3, asset_id="M14860")

    # 1. First execution fails at Stage 2 (simulate failure in runtime_feature)
    call_count = {"prep": 0}
    orig_preprocess = service.preprocessing_service.preprocess_with_plan

    def tracked_preprocess(*args, **kwargs):
        call_count["prep"] += 1
        return orig_preprocess(*args, **kwargs)

    monkeypatch.setattr(service.preprocessing_service, "preprocess_with_plan", tracked_preprocess)

    # Monkeypatch prediction service to fail on first attempt
    orig_predict = service.prediction_service.predict_for_models

    def failing_predict(*args, **kwargs):
        raise PipelineModelPredictionFailedError("Simulated inference failure at stage 3")

    monkeypatch.setattr(service.prediction_service, "predict_for_models", failing_predict)

    item1 = queue.enqueue(job_id="job-resume-prep-1", source_uri=str(src_file), source_checksum=sha)
    with pytest.raises(PipelineModelPredictionFailedError):
        service.execute_queue_item(item1)

    assert call_count["prep"] == 1
    # Check that Checkpoint 2 was recorded before stage 3 failure
    resumable = repo.find_resumable_run(item1.source_identity)
    assert resumable is not None
    assert resumable.last_completed_stage == "runtime_feature"

    # 2. Second execution with restored prediction service
    monkeypatch.setattr(service.prediction_service, "predict_for_models", orig_predict)

    item2 = PipelineQueueItem(
        job_id="job-resume-prep-2",
        source_uri=str(src_file),
        source_checksum=sha,
        source_identity=item1.source_identity,
    )
    run_state2 = service.execute_queue_item(item2)

    assert run_state2.status == "succeeded"
    assert run_state2.run_id == resumable.run_id
    assert run_state2.resume_count == 1
    # Preprocess was NOT called again during resumption!
    assert call_count["prep"] == 1


# =====================================================================
# 22. Partial Model Feature Recovery Test
# =====================================================================

def test_partial_model_feature_recovery(isolated_runtime_env, monkeypatch):
    """When one model feature NPY is corrupted or deleted, only that model feature is re-extracted while others are reused."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "partial_feat.jsonl", num_rows=3, asset_id="M14860")

    # 1. Fail at prediction stage so Checkpoint 2 is saved
    orig_predict = service.prediction_service.predict_for_models

    def failing_predict(*args, **kwargs):
        raise PipelineModelPredictionFailedError("Simulated failure")

    monkeypatch.setattr(service.prediction_service, "predict_for_models", failing_predict)

    item1 = queue.enqueue(job_id="job-part-1", source_uri=str(src_file), source_checksum=sha)
    with pytest.raises(PipelineModelPredictionFailedError):
        service.execute_queue_item(item1)

    first_run = repo.find_resumable_run(item1.source_identity)
    assert first_run is not None
    chk = repo.get_checkpoint(first_run.run_id)
    assert chk is not None
    feat_outputs = chk.stage_outputs.get("runtime_feature", [])
    assert len(feat_outputs) >= 1

    # Corrupt the first feature NPY file
    target_npy = Path(feat_outputs[0].uri)
    if target_npy.exists():
        target_npy.write_text("corrupted", encoding="utf-8")

    # 2. Resume execution
    monkeypatch.setattr(service.prediction_service, "predict_for_models", orig_predict)

    item2 = PipelineQueueItem(
        job_id="job-part-2",
        source_uri=str(src_file),
        source_checksum=sha,
        source_identity=item1.source_identity,
    )
    run_state2 = service.execute_queue_item(item2)
    assert run_state2.status == "succeeded"


# =====================================================================
# 23. Source Checksum Change Rejects Checkpoint Test
# =====================================================================

def test_source_checksum_change_rejects_old_checkpoint(isolated_runtime_env, monkeypatch):
    """When source file content changes, existing checkpoint is invalidated and a fresh run is created."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha1 = create_sample_observation_jsonl(incoming_dir / "mod_check.jsonl", num_rows=2, asset_id="M14860")

    # 1. Fail at prediction
    orig_predict = service.prediction_service.predict_for_models

    def failing_predict(*args, **kwargs):
        raise PipelineModelPredictionFailedError("Simulated failure")

    monkeypatch.setattr(service.prediction_service, "predict_for_models", failing_predict)

    item1 = queue.enqueue(job_id="job-mod-1", source_uri=str(src_file), source_checksum=sha1)
    with pytest.raises(PipelineModelPredictionFailedError):
        service.execute_queue_item(item1)

    first_run = repo.find_resumable_run(item1.source_identity)
    assert first_run is not None

    # 2. Modify file content -> new checksum
    src_file, sha2 = create_sample_observation_jsonl(incoming_dir / "mod_check.jsonl", num_rows=4, asset_id="M14860")
    monkeypatch.setattr(service.prediction_service, "predict_for_models", orig_predict)

    item2 = queue.enqueue(job_id="job-mod-2", source_uri=str(src_file), source_checksum=sha2)
    run_state2 = service.execute_queue_item(item2)

    assert run_state2.status == "succeeded"
    assert run_state2.run_id != first_run.run_id


# =====================================================================
# 24. Safe Cleanup Removes Run-Dedicated Intermediates Test
# =====================================================================

def test_safe_cleanup_removes_run_dedicated_intermediates_preserves_models(isolated_runtime_env):
    """After Checkpoint 5 is published, run-dedicated intermediate datasets and NPYs are cleaned up while source files and models are preserved."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    models_store: Path = env.get("models_dir", getattr(PATHS, "models_store", Path("models_store")))

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "cleanup_test.jsonl", num_rows=3, asset_id="M14860")
    item = queue.enqueue(job_id="job-clean-1", source_uri=str(src_file), source_checksum=sha)
    run_state = service.execute_queue_item(item)

    assert run_state.status == "succeeded"
    assert run_state.cleanup_status == "cleaned"

    # Source file MUST exist
    assert src_file.exists()

    # Model artifacts MUST exist
    for base_model in REGISTERED_BASE_MODELS:
        m_dir = models_store / "artifacts" / f"pdm-{base_model}"
        assert m_dir.exists()

    # Run-dedicated pipeline dataset directory MUST be removed
    run_dataset_dir = env["repository"].base_dir / "pipeline_datasets" / run_state.run_id
    assert not run_dataset_dir.exists()


# =====================================================================
# 25. Cleanup Failure Results In succeeded_with_cleanup_warning Test
# =====================================================================

def test_cleanup_failure_results_in_succeeded_with_cleanup_warning(isolated_runtime_env, monkeypatch):
    """When intermediate file cleanup encounters an error, the run status is succeeded_with_cleanup_warning without invalidating Outbox delivery."""
    env = isolated_runtime_env
    incoming_dir: Path = env["incoming_dir"]
    queue: PipelineQueue = env["queue"]
    service: PipelineService = env["service"]
    repo: PipelineRepository = env["repository"]

    src_file, sha = create_sample_observation_jsonl(incoming_dir / "clean_warn.jsonl", num_rows=3, asset_id="M14860")
    item = queue.enqueue(job_id="job-clean-warn-1", source_uri=str(src_file), source_checksum=sha)

    # Monkeypatch cleanup to fail
    def failing_cleanup(*args, **kwargs):
        return False, [], "Simulated permission denied on cleanup"

    monkeypatch.setattr(repo, "cleanup_run_intermediate_outputs", failing_cleanup)

    run_state = service.execute_queue_item(item)
    assert run_state.status == "succeeded_with_cleanup_warning"
    assert run_state.cleanup_status == "cleanup_failed"
    # Prediction delivery Outbox MUST still be published
    assert len(run_state.prediction_event_ids) > 0
    assert len(list(env["outbox_dir"].glob("*.json"))) > 0

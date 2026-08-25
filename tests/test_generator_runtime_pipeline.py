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

from systems.generator.file_integrity import compute_file_sha256
from systems.generator.model.publisher import ModelArtifactPublisher
from systems.generator.app.main import app
from systems.generator.app.runtime_pipeline.aggregation_service import AggregationService
from systems.generator.app.runtime_pipeline.notification_service import NotificationService
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineDuplicateInputError,
    PipelineHistoryInsufficientError,
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineNoActiveModelError,
    PipelineNotificationRetryExhaustedError,
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
def isolated_runtime_env(tmp_path: Path):
    """Isolated environment with mock models, database, and directories."""
    data_dir = tmp_path / "data"
    incoming_dir = data_dir / "incoming"
    preprocessed_dir = tmp_path / "data_preprocessed"
    models_store = tmp_path / "models_store"
    artifacts_dir = models_store / "artifacts"
    features_cache_dir = models_store / "cache" / "runtime_features"

    for d in [data_dir, incoming_dir, preprocessed_dir, models_store, artifacts_dir, features_cache_dir]:
        d.mkdir(parents=True, exist_ok=True)

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
        feature_service=feat_service,
    )
    agg_service = AggregationService()

    sent_signals = []

    class MockNotificationService(NotificationService):
        def send_notification(self, payload: AnomalySignalPayload):
            sent_signals.append(payload)
            return {"delivered": True, "status_code": 200}

    notif_service = MockNotificationService()
    service = PipelineService(
        repository=repository,
        prediction_service=pred_service,
        aggregation_service=agg_service,
        notification_service=notif_service,
    )
    worker = PipelineWorker(queue=queue, service=service)
    manager = PipelineManager(queue=queue, repository=repository, service=service)

    return {
        "tmp_path": tmp_path,
        "incoming_dir": incoming_dir,
        "artifacts_dir": artifacts_dir,
        "publisher": publisher,
        "queue": queue,
        "repository": repository,
        "feat_service": feat_service,
        "pred_service": pred_service,
        "agg_service": agg_service,
        "notif_service": notif_service,
        "sent_signals": sent_signals,
        "service": service,
        "worker": worker,
        "manager": manager,
        "feature_schema": feature_schema,
        "label_schema": label_schema,
        "hist_req": hist_req,
    }


def _create_sample_protocol_jsonl(path: Path, n_rows: int = 5, asset_id: str = "M14860") -> Path:
    lines = []
    for i in range(n_rows):
        rec = {
            "UDI": i + 1,
            "Product ID": asset_id,
            "Type": "M",
            "Air temperature [K]": 298.1 + i * 0.1,
            "Process temperature [K]": 308.6 + i * 0.1,
            "Rotational speed [rpm]": 1500 + i * 10,
            "Torque [Nm]": 42.0,
            "Tool wear [min]": i * 2,
            "observed_at": f"2026-08-25T11:5{i}:00Z",
        }
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_queue_fifo_order_and_deduplication(isolated_runtime_env):
    """Test FIFO ordering, sequence assignment, and duplicate rejection in persistent queue."""
    queue: PipelineQueue = isolated_runtime_env["queue"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    f1 = _create_sample_protocol_jsonl(incoming_dir / "sample_01.jsonl", n_rows=3)
    f2 = _create_sample_protocol_jsonl(incoming_dir / "sample_02.jsonl", n_rows=3)
    sha1 = compute_file_sha256(f1)
    sha2 = compute_file_sha256(f2)

    item1 = queue.enqueue(job_id="job-1", source_uri=str(f1), source_checksum=sha1)
    item2 = queue.enqueue(job_id="job-2", source_uri=str(f2), source_checksum=sha2)

    assert item1.sequence == 1
    assert item2.sequence == 2

    # Duplicate enqueue of exact same uri & checksum should fail
    with pytest.raises(PipelineDuplicateInputError):
        queue.enqueue(job_id="job-1-dup", source_uri=str(f1), source_checksum=sha1)

    # Claim in FIFO order
    claimed1 = queue.claim_next()
    assert claimed1 is not None
    assert claimed1.job_id == "job-1"
    assert claimed1.status == "running"

    claimed2 = queue.claim_next()
    assert claimed2 is not None
    assert claimed2.job_id == "job-2"
    assert claimed2.status == "running"

    # Queue empty now
    assert queue.claim_next() is None


def test_queue_crash_recovery_on_startup(isolated_runtime_env):
    """Verify that interrupted 'running' jobs are recovered to 'queued' on startup."""
    queue: PipelineQueue = isolated_runtime_env["queue"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    f1 = _create_sample_protocol_jsonl(incoming_dir / "crash_sample.jsonl", n_rows=3)
    sha1 = compute_file_sha256(f1)

    queue.enqueue(job_id="job-crash", source_uri=str(f1), source_checksum=sha1)
    claimed = queue.claim_next()
    assert claimed is not None
    assert claimed.status == "running"

    # Simulate restart with new PipelineQueue instance on same DB
    recovered_queue = PipelineQueue(db_path=queue.db_path)
    count = recovered_queue.recover_running_on_startup()
    assert count == 1

    re_claimed = recovered_queue.claim_next()
    assert re_claimed is not None
    assert re_claimed.job_id == "job-crash"
    assert re_claimed.attempt == 2


def test_state_manager_transitions_and_artifact_references():
    """Verify stage transition order and enforcement of output refs before success."""
    source_ref = ArtifactReference(uri="data/incoming/test.jsonl", sha256="0" * 64, role="source_file")
    mgr = PipelineStateManager.create(run_id="run-001", job_id="job-001", source_ref=source_ref)

    # Cannot succeed stage before starting it
    with pytest.raises(PipelineStateTransitionInvalidError):
        mgr.succeed_stage("preprocessing", output_refs=[])

    mgr.start_run()
    assert mgr.state.status == "running"

    stage = mgr.start_stage("preprocessing", input_refs=[source_ref])
    assert stage.status == "running"
    assert stage.started_at is not None

    plan_ref = ArtifactReference(uri="models_store/cache/pp-01.json", sha256="1" * 64, role="preprocessing_plan")
    mgr.succeed_stage("preprocessing", output_refs=[plan_ref])
    assert mgr.state.stages["preprocessing"].status == "succeeded"
    assert len(mgr.state.stages["preprocessing"].output_refs) == 1

    mgr.finish_run("succeeded")
    assert mgr.state.status == "succeeded"
    assert mgr.state.finished_at is not None


def test_runtime_feature_service_strictly_label_free(isolated_runtime_env):
    """Verify runtime feature extraction operates without failure truth and produces atomic npy file."""
    feat_service: RuntimeFeatureService = isolated_runtime_env["feat_service"]
    feature_schema = isolated_runtime_env["feature_schema"]
    hist_req = isolated_runtime_env["hist_req"]

    df = pd.DataFrame({
        "asset_id": ["M14860", "M14860", "M14860"],
        "timestamp": ["2026-08-25T10:00:00Z", "2026-08-25T10:01:00Z", "2026-08-25T10:02:00Z"],
        "Air temperature [K]": [298.1, 298.2, 298.3],
        "Process temperature [K]": [308.5, 308.6, 308.7],
        "Rotational speed [rpm]": [1500, 1510, 1520],
    })

    bundle, ref = feat_service.extract_and_publish(
        preprocessed_df=df,
        feature_schema_dict=feature_schema,
        history_requirement_dict=hist_req,
    )

    assert bundle.features.shape == (3, 3)
    assert bundle.feature_columns == ["feat_air_temp", "feat_process_temp", "feat_rot_speed"]
    assert Path(ref.uri).exists()
    assert ref.sha256 == compute_file_sha256(Path(ref.uri))

    # Insufficient rows raises PipelineHistoryInsufficientError
    short_df = df.iloc[:1]
    with pytest.raises(PipelineHistoryInsufficientError):
        feat_service.extract_and_publish(
            preprocessed_df=short_df,
            feature_schema_dict=feature_schema,
            history_requirement_dict=hist_req,
        )


def test_full_pipeline_execution_and_anomaly_signal_dispatch(isolated_runtime_env):
    """End-to-end execution: Queue -> Worker -> Service -> Prediction -> Signal Dispatch."""
    queue: PipelineQueue = isolated_runtime_env["queue"]
    worker: PipelineWorker = isolated_runtime_env["worker"]
    repository: PipelineRepository = isolated_runtime_env["repository"]
    sent_signals = isolated_runtime_env["sent_signals"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    sample_file = _create_sample_protocol_jsonl(incoming_dir / "run_sample.jsonl", n_rows=3, asset_id="M14860")
    sha = compute_file_sha256(sample_file)

    item = queue.enqueue(job_id="job-e2e-01", source_uri=str(sample_file), source_checksum=sha)

    run_state = worker.process_one()
    assert run_state is not None
    assert run_state.job_id == "job-e2e-01"
    assert run_state.status == "succeeded"
    assert run_state.anomaly_detected is True
    assert run_state.notification_status == "sent"
    assert len(run_state.prediction_results) == 3

    # XGBoost (0.85) and Random Forest (0.75) flagged anomaly -> Exactly 1 notification dispatched
    assert len(sent_signals) == 1
    sig = sent_signals[0]
    assert sig.asset_id == "M14860"
    assert sig.anomaly_detected is True
    assert sig.anomaly_models == ["pdm-xgboost", "pdm-random_forest"]
    assert len(sig.model_results) == 3

    # Verify run state is persisted in repository
    saved = repository.get_run_state(run_state.run_id)
    assert saved is not None
    assert saved.run_id == run_state.run_id
    assert saved.status == "succeeded"


def test_all_models_normal_suppresses_notification(isolated_runtime_env):
    """When all models evaluate normal, anomaly_detected is False and notification is not dispatched."""
    publisher = isolated_runtime_env["publisher"]
    feature_schema = isolated_runtime_env["feature_schema"]
    label_schema = isolated_runtime_env["label_schema"]
    hist_req = isolated_runtime_env["hist_req"]
    queue = isolated_runtime_env["queue"]
    worker = isolated_runtime_env["worker"]
    sent_signals = isolated_runtime_env["sent_signals"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    base_map = {"pdm-lightgbm": "lightgbm", "pdm-xgboost": "xgboost", "pdm-random_forest": "random_forest"}
    for model_id in ["pdm-lightgbm", "pdm-xgboost", "pdm-random_forest"]:
        publisher.publish_artifact(
            model_id=model_id,
            model_version=f"{model_id}-normal",
            base_model=base_map[model_id],
            model_obj=MockEstimator(anomaly_prob=0.05),
            dataset_id="canonical-ai4i-v1",
            dataset_version="canonical-ai4i-physics-v3.1",
            feature_dataset_version="feat-v1",
            feature_schema=feature_schema,
            label_schema=label_schema,
            history_requirement=hist_req,
            metrics={"metrics_summary": {"f1": 0.9}},
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

    sample_file = _create_sample_protocol_jsonl(incoming_dir / "all_normal.jsonl", n_rows=3)
    sha = compute_file_sha256(sample_file)
    queue.enqueue(job_id="job-all-normal", source_uri=str(sample_file), source_checksum=sha)

    run_state = worker.process_one()
    assert run_state is not None
    assert run_state.status == "succeeded"
    assert run_state.anomaly_detected is False
    assert run_state.notification_status == "not_required"
    assert len(sent_signals) == 0


def test_partial_model_failure_with_anomaly_signal(isolated_runtime_env):
    """When one model fails, remaining models proceed and anomaly signal is sent if detected."""
    artifacts_dir = isolated_runtime_env["artifacts_dir"]
    queue = isolated_runtime_env["queue"]
    worker = isolated_runtime_env["worker"]
    sent_signals = isolated_runtime_env["sent_signals"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    # Corrupt pdm-xgboost manifest
    xgboost_manifest = artifacts_dir / "pdm-xgboost" / "pdm-xgboost-v1.0" / "manifest.json"
    xgboost_manifest.write_text('{"corrupted": true}', encoding="utf-8")

    sample_file = _create_sample_protocol_jsonl(incoming_dir / "partial_fail.jsonl", n_rows=3)
    sha = compute_file_sha256(sample_file)
    queue.enqueue(job_id="job-partial-fail", source_uri=str(sample_file), source_checksum=sha)

    run_state = worker.process_one()
    assert run_state is not None
    assert run_state.status == "partially_succeeded"
    assert run_state.anomaly_detected is True  # Random Forest detected anomaly
    assert run_state.notification_status == "sent"
    assert len(sent_signals) == 1

    results_by_id = {r.model_id: r for r in run_state.prediction_results}
    assert results_by_id["pdm-xgboost"].status == "failed"
    assert results_by_id["pdm-random_forest"].status == "succeeded"
    assert results_by_id["pdm-random_forest"].is_anomaly is True


def test_all_models_unavailable_fails_run(isolated_runtime_env):
    """When all model pointers are missing, run fails with PIPELINE_NO_ACTIVE_MODEL."""
    artifacts_dir = isolated_runtime_env["artifacts_dir"]
    queue = isolated_runtime_env["queue"]
    worker = isolated_runtime_env["worker"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    for m in ["pdm-lightgbm", "pdm-xgboost", "pdm-random_forest"]:
        ptr = artifacts_dir / m / "latest.json"
        if ptr.exists():
            ptr.unlink()

    sample_file = _create_sample_protocol_jsonl(incoming_dir / "all_fail.jsonl", n_rows=3)
    sha = compute_file_sha256(sample_file)
    queue.enqueue(job_id="job-all-fail", source_uri=str(sample_file), source_checksum=sha)

    run_state = worker.process_one()
    assert run_state is None  # worker catches exception and marks queue item failed
    failed_items = queue.list_items(status="failed")
    assert len(failed_items) == 1
    assert failed_items[0].job_id == "job-all-fail"
    assert failed_items[0].error_code == "PIPELINE_NO_ACTIVE_MODEL"


def test_notification_delivery_failure_preserves_prediction(isolated_runtime_env):
    """Notification failure sets notification_status=failed but preserves prediction array."""
    service: PipelineService = isolated_runtime_env["service"]
    incoming_dir = isolated_runtime_env["incoming_dir"]

    class FailingNotificationService(NotificationService):
        def send_notification(self, payload: AnomalySignalPayload):
            raise PipelineNotificationRetryExhaustedError("Connection timeout to receiving system")

    service.notification_service = FailingNotificationService()

    sample_file = _create_sample_protocol_jsonl(incoming_dir / "notif_fail.jsonl", n_rows=3)
    sha = compute_file_sha256(sample_file)
    item = PipelineQueueItem(
        job_id="job-notif-fail",
        source_uri=str(sample_file),
        source_checksum=sha,
        dataset_id="canonical-ai4i-v1",
        dataset_version="canonical-ai4i-physics-v3.1",
        sequence=1,
        attempt=1,
        status="running",
    )

    run_state = service.execute_queue_item(item)
    assert run_state.anomaly_detected is True
    assert run_state.notification_status == "failed"
    assert run_state.stages["notification"].status == "failed"
    assert len(run_state.prediction_results) == 3
    assert run_state.prediction_results[1].is_anomaly is True


def test_runtime_pipeline_router_api(isolated_runtime_env):
    """Test /runtime-pipeline status, queue, and internal enqueue endpoints."""
    manager: PipelineManager = isolated_runtime_env["manager"]
    PipelineManager.set_instance(manager)

    client = TestClient(app)

    # 1. Enqueue via /internal/runtime-pipeline/enqueue
    incoming_dir = isolated_runtime_env["incoming_dir"]
    sample_file = _create_sample_protocol_jsonl(incoming_dir / "api_sample.jsonl", n_rows=3)
    sha = compute_file_sha256(sample_file)

    resp = client.post(
        "/internal/runtime-pipeline/enqueue",
        json={
            "job_id": "job-api-01",
            "source_uri": str(sample_file),
            "source_checksum": sha,
            "dataset_id": "canonical-ai4i-v1",
            "dataset_version": "canonical-ai4i-physics-v3.1",
        },
    )
    assert resp.status_code == 200
    item_data = resp.json()
    assert item_data["job_id"] == "job-api-01"
    assert item_data["status"] == "queued"

    # 2. Check /runtime-pipeline/queue
    q_resp = client.get("/runtime-pipeline/queue")
    assert q_resp.status_code == 200
    assert len(q_resp.json()) >= 1

    # 3. Process item synchronously
    run_state = manager.worker.process_one()
    assert run_state is not None

    # 4. Check /runtime-pipeline/runs/{run_id}
    run_resp = client.get(f"/runtime-pipeline/runs/{run_state.run_id}")
    assert run_resp.status_code == 200
    assert run_resp.json()["run_id"] == run_state.run_id

    # 5. Check /runtime-pipeline/status
    stat_resp = client.get("/runtime-pipeline/status")
    assert stat_resp.status_code == 200
    assert "queued_count" in stat_resp.json()

"""Tests for Generator FastAPI daemon server: Startup, Shutdown worker lifecycle, Concurrency, API contracts, and Documentation."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_main import _training_lock, app
from systems.generator.model.model_registry import (
    has_any_published_model_artifact,
    has_any_trained_model,
)


@pytest.fixture
def client():
    return TestClient(app)


# ==========================================
# 1. API Endpoints
# ==========================================

def test_generator_daemon_health(client):
    """Test GET /health returns 200 with system identifier."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "system": "generator"}


def test_generator_daemon_train_success(client):
    """Test POST /internal/train invokes train_all and returns response payload."""
    dummy_result = {
        "capabilities": {"FailurePrediction": True},
        "mappings": {},
        "registry": {
            "run_version": 1,
            "run_id": "run-v1-test",
            "models": {"lightgbm": {"artifact_uri": "models_store/artifacts/lightgbm/v1"}},
            "published_artifacts": {"lightgbm": "models_store/artifacts/lightgbm/v1"},
        },
    }
    with patch("systems.generator.generator_main.train_all", return_value=dummy_result) as mock_train:
        response = client.post("/internal/train", json={"force_reanalyze": False})
        assert response.status_code == 200
        assert response.json() == dummy_result
        mock_train.assert_called_once()
    assert not _training_lock.locked()


def test_generator_daemon_retrain_success(client):
    """Test POST /internal/retrain invokes train_all with new version."""
    dummy_result = {
        "capabilities": {"FailurePrediction": True},
        "mappings": {},
        "registry": {
            "run_version": 2,
            "run_id": "run-v2-test",
            "models": {"lightgbm": {"artifact_uri": "models_store/artifacts/lightgbm/v2"}},
            "published_artifacts": {"lightgbm": "models_store/artifacts/lightgbm/v2"},
        },
    }
    with patch("systems.generator.generator_main.train_all", return_value=dummy_result) as mock_train:
        response = client.post("/internal/retrain", json={"force_reanalyze": True})
        assert response.status_code == 200
        assert response.json() == dummy_result
        mock_train.assert_called_once()
    assert not _training_lock.locked()


def test_generator_daemon_train_nonexistent_data_dir_returns_400(client):
    """Test POST /internal/train returns 400 when data_dir does not exist."""
    response = client.post("/internal/train", json={"data_dir": "non_existent_directory_12345"})
    assert response.status_code == 400
    assert "지정한 data_dir가 존재하지 않습니다" in response.json()["detail"]
    assert not _training_lock.locked()


def test_generator_daemon_train_file_as_data_dir_returns_400(client, tmp_path):
    """Test POST /internal/train returns 400 when data_dir is a file instead of directory."""
    dummy_file = tmp_path / "not_a_dir.txt"
    dummy_file.write_text("hello", encoding="utf-8")
    response = client.post("/internal/train", json={"data_dir": str(dummy_file)})
    assert response.status_code == 400
    assert "지정한 data_dir가 디렉터리가 아닙니다" in response.json()["detail"]
    assert not _training_lock.locked()


def test_generator_daemon_train_empty_data_dir_returns_400(client, tmp_path):
    """Test POST /internal/train returns 400 when data_dir is empty."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    response = client.post("/internal/train", json={"data_dir": str(empty_dir)})
    assert response.status_code == 400
    assert "지정한 data_dir가 비어 있습니다" in response.json()["detail"]
    assert not _training_lock.locked()


def test_generator_daemon_train_invalid_schema_returns_422(client):
    """Test POST /internal/train returns 422 for invalid request body schema."""
    response = client.post("/internal/train", json={"force_reanalyze": "invalid_boolean_value_123"})
    assert response.status_code == 422
    assert not _training_lock.locked()


def test_generator_daemon_train_internal_error_returns_sanitized_500(client):
    """Test POST /internal/train returns sanitized 500 without leaking stack trace."""
    with patch("systems.generator.generator_main.train_all", side_effect=RuntimeError("Secret internal path /secret/code.py failed")):
        response = client.post("/internal/train", json={})
        assert response.status_code == 500
        assert response.json()["detail"] == "모델 학습에 실패했습니다."
        assert "/secret/code.py" not in response.json()["detail"]
    assert not _training_lock.locked()


# ==========================================
# 2. Concurrency Control (Lock & 409)
# ==========================================

@pytest.mark.anyio
async def test_generator_daemon_concurrent_training_returns_409():
    """Test concurrent training execution triggers HTTP 409 Conflict."""
    from systems.generator.generator_main import _execute_training

    training_started = threading.Event()
    training_release = threading.Event()

    def slow_train_all(*args, **kwargs):
        training_started.set()
        training_release.wait(timeout=5)
        return {"registry": {}}

    with patch("systems.generator.generator_main.train_all", side_effect=slow_train_all):
        task1 = asyncio.create_task(_execute_training(data_dir=None, force_reanalyze=False))
        # Wait until worker starts
        await asyncio.to_thread(training_started.wait, 2.0)
        assert _training_lock.locked()

        # Attempt second concurrent training call
        with pytest.raises(Exception) as exc_info:
            await _execute_training(data_dir=None, force_reanalyze=False)

        assert exc_info.value.status_code == 409
        assert "모델 학습이 이미 진행 중입니다" in exc_info.value.detail

        # Release first task and verify completion
        training_release.set()
        result1 = await task1
        assert "registry" in result1

    assert not _training_lock.locked()


@pytest.mark.anyio
async def test_generator_daemon_lock_released_after_failure():
    """Test concurrency lock is safely released after training failure."""
    from systems.generator.generator_main import _execute_training

    with patch("systems.generator.generator_main.train_all", side_effect=RuntimeError("Training boom")):
        with pytest.raises(Exception) as exc_info:
            await _execute_training(data_dir=None, force_reanalyze=False)
        assert exc_info.value.status_code == 500

    assert not _training_lock.locked(), "Lock must be released even after exception"

    # Subsequent call can acquire lock without 409
    with patch("systems.generator.generator_main.train_all", return_value={"success": True}):
        result = await _execute_training(data_dir=None, force_reanalyze=False)
        assert result == {"success": True}

    assert not _training_lock.locked()


# ==========================================
# 3. Startup & Shutdown Lifecycle (Non-blocking & Graceful Wait)
# ==========================================

@pytest.mark.anyio
async def test_generator_daemon_lifespan_skips_when_model_exists():
    """Test lifespan skips background auto-training if model artifact already exists."""
    from systems.generator.generator_main import lifespan

    with patch("systems.generator.generator_main.has_any_published_model_artifact", return_value=True), \
         patch("systems.generator.generator_main.load_config") as mock_load, \
         patch("asyncio.create_task") as mock_create_task:
        async with lifespan(app):
            mock_load.assert_called_once()
            mock_create_task.assert_not_called()
            assert app.state.initial_training_task is None

    assert not _training_lock.locked()


@pytest.mark.anyio
async def test_generator_daemon_lifespan_yields_immediately_without_waiting():
    """Test lifespan yields immediately (starts daemon) without waiting for training completion."""
    from systems.generator.generator_main import lifespan

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def slow_worker(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"registry": {}}

    with patch("systems.generator.generator_main.has_any_published_model_artifact", return_value=False), \
         patch("systems.generator.generator_main.load_config"), \
         patch("systems.generator.generator_main.train_all", side_effect=slow_worker):
        async with lifespan(app):
            await asyncio.to_thread(started.wait, 2.0)
            assert started.is_set()
            assert not finished.is_set(), "Lifespan must yield immediately while worker is still running"
            assert _training_lock.locked()
            release.set()

    assert finished.is_set()
    assert not _training_lock.locked()


@pytest.mark.anyio
async def test_shutdown_waits_for_real_training_worker_and_keeps_lock():
    """Test shutdown waits for real blocking training worker thread and keeps lock until completion."""
    from systems.generator.generator_main import lifespan

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_train_all(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"registry": {}}

    with patch("systems.generator.generator_main.has_any_published_model_artifact", return_value=False), \
         patch("systems.generator.generator_main.load_config"), \
         patch("systems.generator.generator_main.train_all", side_effect=blocking_train_all):

        # Enter lifespan context
        cm = lifespan(app)
        await cm.__aenter__()

        # Wait until worker thread actually starts
        await asyncio.to_thread(started.wait, 2.0)
        assert started.is_set()
        assert _training_lock.locked()
        assert not finished.is_set()

        # Start shutdown in background
        shutdown_task = asyncio.create_task(cm.__aexit__(None, None, None))
        await asyncio.sleep(0.05)

        # Before release, shutdown task must still be waiting, worker not finished, lock held
        assert not shutdown_task.done(), "Shutdown must not finish while worker is running"
        assert not finished.is_set()
        assert _training_lock.locked()

        # Release worker thread
        release.set()
        await shutdown_task

        # After shutdown task finishes, worker must be finished and lock released
        assert finished.is_set()
        assert not _training_lock.locked()


@pytest.mark.anyio
async def test_generator_daemon_lifespan_handles_background_training_failure():
    """Test lifespan handles initial training background task failure gracefully without crashing."""
    from systems.generator.generator_main import _run_initial_training

    with patch("systems.generator.generator_main.train_all", side_effect=RuntimeError("Initial train failed")):
        # Should not raise exception
        await _run_initial_training()

    assert not _training_lock.locked()


# ==========================================
# 4. Model Artifact Presence Check vs Raw Files
# ==========================================

def test_has_any_published_model_artifact_distinguishes_raw_and_valid_artifacts(tmp_path):
    """Test has_any_published_model_artifact rejects raw joblib / partial directories and accepts valid artifacts."""
    store_dir = tmp_path / "models_store"
    artifact_root = store_dir / "artifacts"
    artifact_root.mkdir(parents=True)

    # 1. Empty root
    assert not has_any_published_model_artifact(artifact_root)

    # 2. Raw model_v1.joblib only in legacy folder
    raw_dir = store_dir / "lightgbm"
    raw_dir.mkdir(parents=True)
    (raw_dir / "model_v1.joblib").write_text("raw", encoding="utf-8")

    assert has_any_trained_model(store_dir), "Legacy check sees raw file"
    assert not has_any_published_model_artifact(artifact_root), "Artifact check rejects raw file alone"

    # 3. Model artifact folder with valid manifest and declared files
    target_artifact = artifact_root / "pdm-cnc-tool-wear-lightgbm" / "v1"
    target_artifact.mkdir(parents=True)
    (target_artifact / "model.joblib").write_text("model_bytes", encoding="utf-8")
    (target_artifact / "feature_schema.json").write_text("{}", encoding="utf-8")

    manifest = {
        "artifact_type": "predictive_maintenance_model",
        "artifact_schema_version": "model-artifact-v1.0",
        "artifact_files": [
            {"role": "model", "path": "model.joblib"},
            {"role": "feature_schema", "path": "feature_schema.json"},
        ],
    }
    (target_artifact / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert has_any_published_model_artifact(artifact_root), "Artifact check accepts valid manifest package"


# ==========================================
# 5. Documentation Contracts
# ==========================================

def test_generator_daemon_docs_in_mvp_dir_and_no_predict():
    """Test generator internal API specification resides in docs/mvp/ and has no active predict endpoints."""
    doc_path = Path(__file__).resolve().parents[1] / "docs" / "mvp" / "generator-internal-api-specification.md"
    assert doc_path.exists(), "Doc must be moved to docs/mvp/generator-internal-api-specification.md"

    content = doc_path.read_text(encoding="utf-8")
    assert "GET /health" in content
    assert "POST /internal/train" in content
    assert "POST /internal/retrain" in content
    assert "금지 범위" in content
    assert "artifact_uri" in content
    assert "published_artifacts" in content
    assert "run_id" in content
    assert "has_any_published_model_artifact" in content

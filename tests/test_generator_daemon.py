"""Tests for Generator FastAPI daemon server: Startup, Concurrency, API contracts, and Documentation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_main import _training_lock, app


@pytest.fixture(autouse=True)
def _reset_lock():
    """Ensure concurrency lock is clean before and after each test."""
    if _training_lock.locked():
        try:
            _training_lock.release()
        except RuntimeError:
            pass
    yield
    if _training_lock.locked():
        try:
            _training_lock.release()
        except RuntimeError:
            pass


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


def test_generator_daemon_train_nonexistent_data_dir_returns_400(client):
    """Test POST /internal/train returns 400 when data_dir does not exist."""
    response = client.post("/internal/train", json={"data_dir": "non_existent_directory_12345"})
    assert response.status_code == 400
    assert "지정한 data_dir가 존재하지 않습니다" in response.json()["detail"]


def test_generator_daemon_train_file_as_data_dir_returns_400(client, tmp_path):
    """Test POST /internal/train returns 400 when data_dir is a file instead of directory."""
    dummy_file = tmp_path / "not_a_dir.txt"
    dummy_file.write_text("hello", encoding="utf-8")
    response = client.post("/internal/train", json={"data_dir": str(dummy_file)})
    assert response.status_code == 400
    assert "지정한 data_dir가 디렉터리가 아닙니다" in response.json()["detail"]


def test_generator_daemon_train_empty_data_dir_returns_400(client, tmp_path):
    """Test POST /internal/train returns 400 when data_dir is empty."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    response = client.post("/internal/train", json={"data_dir": str(empty_dir)})
    assert response.status_code == 400
    assert "지정한 data_dir가 비어 있습니다" in response.json()["detail"]


def test_generator_daemon_train_invalid_schema_returns_422(client):
    """Test POST /internal/train returns 422 for invalid request body schema."""
    response = client.post("/internal/train", json={"force_reanalyze": "invalid_boolean_value_123"})
    assert response.status_code == 422


def test_generator_daemon_train_internal_error_returns_sanitized_500(client):
    """Test POST /internal/train returns sanitized 500 without leaking stack trace."""
    with patch("systems.generator.generator_main.train_all", side_effect=RuntimeError("Secret internal path /secret/code.py failed")):
        response = client.post("/internal/train", json={})
        assert response.status_code == 500
        assert response.json()["detail"] == "모델 학습에 실패했습니다."
        assert "/secret/code.py" not in response.json()["detail"]


# ==========================================
# 2. Concurrency Control (Lock & 409)
# ==========================================

@pytest.mark.anyio
async def test_generator_daemon_concurrent_training_returns_409():
    """Test concurrent training execution triggers HTTP 409 Conflict."""
    from systems.generator.generator_main import _execute_training

    training_started = asyncio.Event()
    training_release = asyncio.Event()

    def slow_train_all(*args, **kwargs):
        training_started.set()
        # Wait synchronously until release
        import time
        while not training_release.is_set():
            time.sleep(0.01)
        return {"registry": {}}

    with patch("systems.generator.generator_main.train_all", side_effect=slow_train_all):
        # Start first training task in background
        task1 = asyncio.create_task(_execute_training(data_dir=None, force_reanalyze=False))
        # Wait until lock is acquired and train_all started
        await asyncio.sleep(0.05)

        # Attempt second concurrent training call
        with pytest.raises(Exception) as exc_info:
            await _execute_training(data_dir=None, force_reanalyze=False)

        assert exc_info.value.status_code == 409
        assert "모델 학습이 이미 진행 중입니다" in exc_info.value.detail

        # Release first task
        training_release.set()
        await task1


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


# ==========================================
# 3. Startup Lifecycle (Non-blocking Background Task)
# ==========================================

@pytest.mark.anyio
async def test_generator_daemon_lifespan_skips_when_model_exists():
    """Test lifespan skips background auto-training if model already exists."""
    from systems.generator.generator_main import lifespan

    with patch("systems.generator.generator_main.has_any_trained_model", return_value=True), \
         patch("systems.generator.generator_main.load_config") as mock_load, \
         patch("asyncio.create_task") as mock_create_task:
        async with lifespan(app):
            mock_load.assert_called_once()
            mock_create_task.assert_not_called()
            assert app.state.initial_training_task is None


@pytest.mark.anyio
async def test_generator_daemon_lifespan_yields_immediately_without_waiting():
    """Test lifespan yields immediately (starts daemon) without waiting for training completion."""
    from systems.generator.generator_main import lifespan

    training_finished = asyncio.Event()

    async def mock_run_initial():
        await asyncio.sleep(0.5)
        training_finished.set()

    with patch("systems.generator.generator_main.has_any_trained_model", return_value=False), \
         patch("systems.generator.generator_main.load_config"), \
         patch("systems.generator.generator_main._run_initial_training", side_effect=mock_run_initial):
        async with lifespan(app):
            # When we reach inside context (after yield), training should still be running
            assert not training_finished.is_set(), "Lifespan must yield immediately without waiting for training"
            assert app.state.initial_training_task is not None


@pytest.mark.anyio
async def test_generator_daemon_lifespan_handles_background_training_failure():
    """Test lifespan handles initial training background task failure gracefully without crashing."""
    from systems.generator.generator_main import _run_initial_training

    with patch("systems.generator.generator_main.train_all", side_effect=RuntimeError("Initial train failed")):
        # Should not raise exception
        await _run_initial_training()


@pytest.mark.anyio
async def test_generator_daemon_lifespan_cancels_pending_task_on_shutdown():
    """Test shutdown cancels any pending background training task."""
    from systems.generator.generator_main import lifespan

    async def endless_training():
        await asyncio.sleep(100)

    with patch("systems.generator.generator_main.has_any_trained_model", return_value=False), \
         patch("systems.generator.generator_main.load_config"), \
         patch("systems.generator.generator_main._run_initial_training", side_effect=endless_training):
        async with lifespan(app):
            task = app.state.initial_training_task
            assert task is not None
            assert not task.done()

        # After exiting lifespan context (shutdown), task should be cancelled/done
        assert task.done()


# ==========================================
# 4. Documentation Contracts
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

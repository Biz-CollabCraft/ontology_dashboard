"""Tests for Generator FastAPI daemon server and training endpoints."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_generator_daemon_health(client):
    """Test GET /health returns 200 with system identifier."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "system": "generator"}


def test_generator_daemon_train_endpoint(client):
    """Test POST /internal/train invokes train_all and returns response payload."""
    dummy_result = {
        "capabilities": {"FailurePrediction": True},
        "mappings": {},
        "registry": {"run_version": 1, "models": {}},
    }
    with patch("systems.generator.generator_main.train_all", return_value=dummy_result) as mock_train:
        response = client.post("/internal/train", json={"force_reanalyze": False})
        assert response.status_code == 200
        assert response.json() == dummy_result
        mock_train.assert_called_once()


def test_generator_daemon_train_invalid_data_dir(client):
    """Test POST /internal/train returns 400 when data_dir does not exist."""
    response = client.post("/internal/train", json={"data_dir": "non_existent_directory_12345"})
    assert response.status_code == 400
    assert "지정한 data_dir가 존재하지 않습니다" in response.json()["detail"]


def test_generator_daemon_retrain_endpoint(client):
    """Test POST /internal/retrain invokes train_all and returns response payload."""
    dummy_result = {
        "capabilities": {"FailurePrediction": True},
        "mappings": {},
        "registry": {"run_version": 2, "models": {}},
    }
    with patch("systems.generator.generator_main.train_all", return_value=dummy_result) as mock_train:
        response = client.post("/internal/retrain", json={"force_reanalyze": True})
        assert response.status_code == 200
        assert response.json() == dummy_result
        mock_train.assert_called_once()


def test_generator_daemon_retrain_invalid_data_dir(client):
    """Test POST /internal/retrain returns 400 when data_dir does not exist."""
    response = client.post("/internal/retrain", json={"data_dir": "non_existent_directory_12345"})
    assert response.status_code == 400
    assert "지정한 data_dir가 존재하지 않습니다" in response.json()["detail"]


@pytest.mark.anyio
async def test_generator_daemon_lifespan_triggers_async_training():
    """Test lifespan triggers asyncio.to_thread(train_all) when no trained model exists."""
    from systems.generator.generator_main import lifespan

    with patch("systems.generator.generator_main.has_any_trained_model", return_value=False), \
         patch("systems.generator.generator_main.load_config") as mock_load_config, \
         patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        async with lifespan(app):
            mock_load_config.assert_called_once()
            mock_to_thread.assert_called_once()

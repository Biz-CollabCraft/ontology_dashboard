"""Tests for Generator FastAPI daemon server and training endpoints."""

from __future__ import annotations

from unittest.mock import patch

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

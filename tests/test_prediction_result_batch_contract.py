from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.diagnosis.runtime_schema import PredictionResultBatch


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples" / "prediction-result-batch"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    [
        "live-predicted.json",
        "maintenance-history-insufficient.json",
    ],
)
def test_prediction_result_batch_examples_match_backend_model(name: str):
    batch = PredictionResultBatch.model_validate(load_example(name))

    assert batch.contract_version == "prediction-result-batch-v1"
    assert batch.producer.system == "systems.generator"
    assert batch.results


def test_prediction_result_batch_keeps_predicted_score_required():
    payload = load_example("live-predicted.json")
    payload["results"][0]["score"] = None

    with pytest.raises(ValidationError, match="predicted batch items require score"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_rejects_failure_reason_on_predicted_item():
    payload = load_example("live-predicted.json")
    payload["results"][0]["failure_reason"] = "model warning"

    with pytest.raises(ValidationError, match="must not carry failure_reason"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_rejects_score_before_prediction_ready():
    payload = load_example("maintenance-history-insufficient.json")
    payload["results"][0]["score"] = 0.2

    with pytest.raises(ValidationError, match="non-predicted batch items must not carry score"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_requires_failure_reason_before_prediction_ready():
    payload = load_example("maintenance-history-insufficient.json")
    payload["results"][0]["failure_reason"] = None

    with pytest.raises(ValidationError, match="non-predicted batch items require failure_reason"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_requires_replay_lineage_for_maintenance_source():
    payload = load_example("maintenance-history-insufficient.json")
    payload["results"][0]["lineage"]["maintenance_event_id"] = None

    with pytest.raises(ValidationError, match="maintenance_replay batch items require lineage fields"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_forbids_product_result_fields():
    payload = load_example("live-predicted.json")
    payload["results"][0]["status_grade"] = "critical"

    with pytest.raises(ValidationError):
        PredictionResultBatch.model_validate(payload)

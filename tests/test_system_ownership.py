from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator

from systems.backend.app.diagnosis.contracts import load_fixture
from systems.backend.app.diagnosis.evidence import build_evidence_package, build_product_result_artifact
from systems.backend.app.diagnosis.predictor import ArtifactPredictor, HeuristicPredictor
from systems.generator.model import train_and_publish_model


def _write_ai4i_fixture(path: Path, rows: int = 120) -> None:
    payload = []
    for index in range(rows):
        failure = 1 if index % 5 == 0 else 0
        payload.append(
            {
                "UDI": index + 1,
                "Product ID": f"M{index:05d}",
                "Type": "M" if index % 3 else "H",
                "Air temperature [K]": 298.0 + (index % 5) * 0.2,
                "Process temperature [K]": 307.5 + (index % 7) * 0.3,
                "Rotational speed [rpm]": 1450 + (index % 11) * 12 - failure * 120,
                "Torque [Nm]": 42.0 + (index % 9) + failure * 18.0,
                "Tool wear [min]": 40 + (index % 30) * 5 + failure * 75,
                "Machine failure": failure,
                "TWF": 0,
                "HDF": 0,
                "PWF": 0,
                "OSF": 0,
                "RNF": 0,
            }
        )
    pd.DataFrame(payload).to_csv(path, index=False)


def test_generator_publishes_model_artifact_and_backend_consumes_it(tmp_path: Path) -> None:
    csv_path = tmp_path / "ai4i.csv"
    _write_ai4i_fixture(csv_path)
    artifact_root = tmp_path / "artifacts"

    artifact_path = train_and_publish_model(
        csv_path=csv_path,
        artifact_uri=artifact_root,
        dataset_version="test-ai4i-v1",
    )

    manifest = json.loads((artifact_path / "manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("schemas/model-artifact.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    assert manifest["artifact_type"] == "predictive_maintenance_model"
    assert manifest["dataset_version"] == "test-ai4i-v1"
    assert manifest["compatibility"]["runtime"] == "ontology_dashboard.systems.backend.diagnosis"

    predictor = ArtifactPredictor(artifact_path)
    fixture = load_fixture("data/fixtures/GS-002-tool-wear-warning.json")
    prediction = predictor.predict(fixture)
    result = build_product_result_artifact(fixture, predictor=predictor)
    evidence = build_evidence_package(fixture, predictor=predictor)

    assert prediction.model_artifact is not None
    assert result["prediction_task"] == "binary_failure_within_horizon"
    assert result["provenance"]["source_type"] == "product_runtime_inference"
    assert result["provenance"]["model_artifact"]["model_version"] == manifest["model_version"]
    assert evidence["model"]["mode"] == "trained"
    assert evidence["model"]["artifact"]["dataset_version"] == "test-ai4i-v1"


def test_week2_fixture_fallback_remains_backend_owned(monkeypatch) -> None:
    monkeypatch.delenv("MODEL_ARTIFACT_URI", raising=False)
    monkeypatch.setenv("ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK", "1")
    fixture = load_fixture("data/fixtures/GS-002-tool-wear-warning.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)

    assert result["schema_version"] == "result-artifact-v1.0"
    assert result["prediction_task"] == "binary_failure_within_horizon"
    assert result["provenance"]["source_type"] == "product_runtime_inference"
    assert result["provenance"]["canonical_source_mutated"] is False


def test_legacy_ml_namespace_is_compatibility_adapter() -> None:
    from ontology_dashboard_manufacturing_ml import HeuristicPredictor as LegacyPredictor
    from ontology_dashboard_manufacturing_ml import build_evidence_package as legacy_evidence

    assert LegacyPredictor.__module__ == "systems.backend.app.diagnosis.predictor"
    assert legacy_evidence.__module__ == "systems.backend.app.diagnosis.evidence"

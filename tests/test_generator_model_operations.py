from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _service(tmp_path: Path, monkeypatch):
    from systems.generator.app.operational_assets.model_selection_service import ModelSelectionService
    service = ModelSelectionService(models_store=tmp_path / "models_store")
    artifact_dir = service.artifacts_root / "pdm-lightgbm" / "1.2.0"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "systems.generator.app.operational_assets.model_selection_service.validate_model_artifact",
        lambda **_: SimpleNamespace(manifest_checksum="1" * 64),
    )
    return service


def test_selected_pointer_does_not_change_latest(tmp_path, monkeypatch):
    from systems.generator.app.operational_assets.model_selection_schema import ModelSelectionRequest
    service = _service(tmp_path, monkeypatch)
    model_root = service.artifacts_root / "pdm-lightgbm"
    latest = {"model_id": "pdm-lightgbm", "model_version": "1.1.0"}
    (model_root / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    result = service.select("pdm-lightgbm", ModelSelectionRequest(model_version="1.2.0", model_artifact_manifest_sha256="1" * 64, reason="운영 검증", actor="system-operator:test"))
    assert result["model_version"] == "1.2.0"
    assert json.loads((model_root / "latest.json").read_text(encoding="utf-8")) == latest


def test_selected_precedes_latest_when_building_candidate(tmp_path, monkeypatch):
    from systems.generator.app.operational_assets.model_selection_schema import ActiveModelSetOperationRequest, ModelSelectionRequest
    service = _service(tmp_path, monkeypatch)
    root = service.artifacts_root / "pdm-lightgbm"
    (root / "latest.json").write_text(json.dumps({"model_version": "1.1.0"}), encoding="utf-8")
    service.select("pdm-lightgbm", ModelSelectionRequest(model_version="1.2.0", model_artifact_manifest_sha256="1" * 64, reason="운영 검증", actor="system-operator:test"))
    result = service.validate_set(ActiveModelSetOperationRequest(model_set_id="production", model_set_version="v2", models=[{"model_id": "pdm-lightgbm", "required": True}], reason="활성화", actor="system-operator:test"))
    assert result["resolved_models"]["pdm-lightgbm"]["resolved_from"] == "selected"
    assert result["payload"]["models"]["pdm-lightgbm"]["model_version"] == "1.2.0"


def test_selection_checksum_mismatch_is_fail_closed(tmp_path, monkeypatch):
    from systems.generator.app.operational_assets.model_selection_schema import ModelSelectionRequest
    from systems.generator.app.operational_assets.model_selection_service import ModelOperationError
    service = _service(tmp_path, monkeypatch)
    with pytest.raises(ModelOperationError) as error:
        service.select("pdm-lightgbm", ModelSelectionRequest(model_version="1.2.0", model_artifact_manifest_sha256="2" * 64, reason="운영 검증", actor="system-operator:test"))
    assert error.value.code == "MODEL_SELECTION_CONFLICT"
    assert not (service.artifacts_root / "pdm-lightgbm" / "selected.json").exists()

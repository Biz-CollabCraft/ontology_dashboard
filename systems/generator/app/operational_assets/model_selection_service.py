from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from systems.generator.app.runtime_pipeline.active_model_set_service import ActiveModelSetService
from systems.generator.app.runtime_pipeline.pipeline_schema import ActiveModelConfig, ActiveModelSet
from systems.generator.model.publisher import ModelActivationInProgressError, ModelActivationLock, ModelArtifactContractValidationError, validate_model_artifact
from systems.generator.generator_config import PATHS

from .model_selection_schema import ActiveModelSetOperationRequest, ModelSelectionRequest


class ModelOperationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class ModelSelectionService:
    def __init__(self, models_store: Path | None = None) -> None:
        self.models_store = Path(models_store or PATHS.models_store)
        self.artifacts_root = self.models_store / "artifacts"
        self.active_sets = ActiveModelSetService(models_store_dir=self.models_store)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _validate_id(value: str, field: str) -> str:
        if not value or value in {".", ".."} or any(ch in value for ch in ("/", "\\", ":")):
            raise ModelOperationError(422, "MODEL_ARTIFACT_PATH_UNSUPPORTED", f"{field}가 올바르지 않습니다.")
        return value

    def _model_root(self, model_id: str) -> Path:
        model_id = self._validate_id(model_id, "model_id")
        root = (self.artifacts_root / model_id).resolve()
        if self.artifacts_root.resolve() not in root.parents:
            raise ModelOperationError(422, "MODEL_ARTIFACT_PATH_UNSUPPORTED", "Model Artifact 경로가 허용 root를 벗어났습니다.")
        return root

    def _validate_artifact(self, model_id: str, version: str, expected_sha: str | None = None) -> dict[str, Any]:
        version = self._validate_id(version, "model_version")
        artifact_dir = self._model_root(model_id) / version
        try:
            validated = validate_model_artifact(
                artifact_dir=artifact_dir,
                expected_model_id=model_id,
                expected_model_version=version,
                load_model=False,
                artifacts_root=self.artifacts_root,
            )
        except ModelArtifactContractValidationError as exc:
            status = 404 if exc.reason == "artifact_not_found" else 422
            code = "MODEL_ARTIFACT_NOT_FOUND" if status == 404 else "MODEL_ARTIFACT_INTEGRITY_ERROR"
            raise ModelOperationError(status, code, exc.message) from exc
        actual = validated.manifest_checksum
        if expected_sha is not None and actual != expected_sha:
            raise ModelOperationError(409, "MODEL_SELECTION_CONFLICT", "요청 checksum과 Model Artifact manifest checksum이 일치하지 않습니다.")
        return {"model_id": model_id, "model_version": version, "manifest_sha256": actual}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ModelOperationError(404, "MODEL_SELECTION_NOT_FOUND", "모델 선택 포인터가 없습니다.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelOperationError(422, "MODEL_SELECTION_INTEGRITY_ERROR", "모델 선택 포인터를 읽을 수 없습니다.") from exc
        if not isinstance(data, dict):
            raise ModelOperationError(422, "MODEL_SELECTION_INTEGRITY_ERROR", "모델 선택 포인터는 JSON object여야 합니다.")
        return data

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / f".tmp-{uuid.uuid4().hex}-{path.name}"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            if json.loads(path.read_text(encoding="utf-8")) != payload:
                raise OSError("pointer read-back mismatch")
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def list_models(self) -> dict[str, Any]:
        items = []
        if not self.artifacts_root.exists():
            return {"items": items}
        active = None
        try:
            active = self.active_sets.load_active_model_set()
        except Exception:
            pass
        for root in sorted(p for p in self.artifacts_root.iterdir() if p.is_dir()):
            versions = sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "manifest.json").exists())
            latest = self._optional_pointer(root / "latest.json")
            selected = self._optional_pointer(root / "selected.json")
            active_config = active.models.get(root.name) if active else None
            items.append({
                "model_id": root.name,
                "versions": versions,
                "latest_version": latest.get("model_version") if latest else None,
                "selected_version": selected.get("model_version") if selected else None,
                "active_version": active_config.model_version if active_config else None,
                "selection": selected,
                "selection_pending_activation": bool(selected and (not active_config or selected.get("model_version") != active_config.model_version)),
            })
        return {"items": items}

    def _optional_pointer(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    def get_selection(self, model_id: str) -> dict[str, Any]:
        return self._read_json(self._model_root(model_id) / "selected.json")

    def select(self, model_id: str, request: ModelSelectionRequest) -> dict[str, Any]:
        artifact = self._validate_artifact(model_id, request.model_version, request.model_artifact_manifest_sha256)
        pointer = self._model_root(model_id) / "selected.json"
        try:
            with ModelActivationLock(pointer.parent / ".selected.lock", model_id=model_id, requested_version=request.model_version):
                current = self._optional_pointer(pointer)
                if current and current.get("model_version") == request.model_version:
                    if current.get("model_artifact_manifest_sha256") != artifact["manifest_sha256"]:
                        raise ModelOperationError(409, "MODEL_SELECTION_CONFLICT", "같은 버전의 기존 선택 checksum이 다릅니다.")
                    return {**current, "idempotent": True}
                payload = {
                    "schema_version": "model-selection-v1", "model_id": model_id,
                    "model_version": request.model_version,
                    "model_artifact_manifest_sha256": artifact["manifest_sha256"],
                    "selected_at": self._now(), "selected_by": request.actor,
                    "reason": request.reason, "selection_id": str(uuid.uuid4()),
                }
                self._atomic_json(pointer, payload)
        except ModelActivationInProgressError as exc:
            raise ModelOperationError(409, "MODEL_SELECTION_LOCKED", str(exc)) from exc
        except OSError as exc:
            raise ModelOperationError(500, "MODEL_SELECTION_WRITE_FAILED", str(exc)) from exc
        return {**payload, "idempotent": False}

    def clear(self, model_id: str, expected_selection_id: str) -> dict[str, Any]:
        root = self._model_root(model_id)
        try:
            with ModelActivationLock(root / ".selected.lock", model_id=model_id, requested_version="latest-fallback"):
                selected = self._read_json(root / "selected.json")
                if selected.get("selection_id") != expected_selection_id:
                    raise ModelOperationError(409, "MODEL_SELECTION_CONFLICT", "선택 revision이 변경되었습니다.")
                latest = self._read_json(root / "latest.json")
                version = str(latest.get("model_version") or latest.get("version") or "")
                self._validate_artifact(model_id, version)
                (root / "selected.json").unlink()
        except ModelActivationInProgressError as exc:
            raise ModelOperationError(409, "MODEL_SELECTION_LOCKED", str(exc)) from exc
        return {"model_id": model_id, "cleared_selection_id": expected_selection_id, "fallback_version": version}

    def _resolve_candidate(self, model_id: str, explicit_version: str | None) -> tuple[str, str]:
        root = self._model_root(model_id)
        source = "explicit"
        version = explicit_version
        if not version:
            selected_path = root / "selected.json"
            selected = self._read_json(selected_path) if selected_path.exists() else None
            if selected is not None:
                if selected.get("schema_version") != "model-selection-v1" or selected.get("model_id") != model_id:
                    raise ModelOperationError(422, "MODEL_SELECTION_INTEGRITY_ERROR", "selected.json identity가 올바르지 않습니다.")
                version, source = str(selected.get("model_version") or ""), "selected"
                expected_sha = str(selected.get("model_artifact_manifest_sha256") or "")
                if len(expected_sha) != 64:
                    raise ModelOperationError(422, "MODEL_SELECTION_INTEGRITY_ERROR", "selected.json checksum이 올바르지 않습니다.")
                self._validate_artifact(model_id, version, expected_sha)
                return version, source
            else:
                latest = self._read_json(root / "latest.json")
                version, source = str(latest.get("model_version") or latest.get("version") or ""), "latest"
        self._validate_artifact(model_id, version or "")
        return version or "", source

    def validate_set(self, request: ActiveModelSetOperationRequest) -> dict[str, Any]:
        seen: set[str] = set()
        resolved: dict[str, Any] = {}
        for candidate in request.models:
            if candidate.model_id in seen:
                raise ModelOperationError(422, "ACTIVE_MODEL_SET_INVALID", "Active Model Set에 중복 모델이 있습니다.")
            seen.add(candidate.model_id)
            version, source = self._resolve_candidate(candidate.model_id, candidate.model_version)
            resolved[candidate.model_id] = {"model_version": version, "required": candidate.required, "resolved_from": source}
        payload = {
            "model_set_id": request.model_set_id,
            "model_set_version": request.model_set_version,
            "updated_at": self._now(),
            "models": {key: {"model_version": value["model_version"], "required": value["required"]} for key, value in resolved.items()},
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"status": "validated", "payload": payload, "payload_sha256": digest, "resolved_models": resolved}

    def activate(self, request: ActiveModelSetOperationRequest) -> dict[str, Any]:
        validated = self.validate_set(request)
        active = ActiveModelSet.model_validate(validated["payload"])
        saved = self.active_sets.update_active_model_set(active)
        return {"status": "active", "payload": saved.model_dump(mode="json"), "payload_sha256": validated["payload_sha256"]}

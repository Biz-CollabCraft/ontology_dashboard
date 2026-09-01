from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from systems.generator.generator_config import PATHS


ASSET_TYPES = {"preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config"}
IDENTITY_FIELDS = {
    "preprocessing_plan": ("preprocessing_plan_id", "preprocessing_plan_version"),
    "feature_schema": (None, "feature_schema_version"),
    "label_schema": (None, "label_schema_version"),
    "history_requirement": (None, "history_requirement_version"),
    "training_config": (None, "training_config_version"),
}


class ManagedContractError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _safe(value: str) -> str:
    clean = value.strip()
    if not clean or ".." in clean or "/" in clean or "\\" in clean:
        raise ManagedContractError("SYSTEM_CONTRACT_IDENTITY_INVALID", "Unsafe contract identifier")
    return clean


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class ManagedContractService:
    def _path(self, asset_type: str, asset_id: str, version: str, payload: dict[str, Any] | None = None) -> Path:
        asset_type, asset_id, version = _safe(asset_type), _safe(asset_id), _safe(version)
        if asset_type not in ASSET_TYPES:
            raise ManagedContractError("SYSTEM_CONTRACT_ASSET_TYPE_UNSUPPORTED", "Unsupported managed asset type")
        if asset_type == "preprocessing_plan":
            if payload is None:
                root = PATHS.models_store / "cache" / "preprocessing_plans"
                matches = list(root.glob(f"*/*/{asset_id}.json")) if root.exists() else []
                for candidate in matches:
                    try:
                        data = json.loads(candidate.read_text(encoding="utf-8"))
                        if data.get("preprocessing_plan_version") == version:
                            return candidate
                    except Exception:
                        continue
                raise ManagedContractError("SYSTEM_CONTRACT_BASE_VERSION_NOT_FOUND", "Preprocessing Plan version not found", 404)
            dataset_id = _safe(str(payload.get("dataset_id", "")))
            dataset_version = _safe(str(payload.get("dataset_version", "")))
            return PATHS.models_store / "cache" / "preprocessing_plans" / dataset_id / dataset_version / f"{asset_id}.json"
        roots = {
            "feature_schema": PATHS.models_store / "schemas" / "features",
            "label_schema": PATHS.models_store / "schemas" / "labels",
            "history_requirement": PATHS.models_store / "schemas" / "history",
            "training_config": PATHS.models_store / "training_configs",
        }
        return roots[asset_type] / f"{version}.json"

    def validate(self, asset_type: str, asset_id: str, version: str, payload: dict[str, Any]) -> str:
        if asset_type not in IDENTITY_FIELDS:
            raise ManagedContractError("SYSTEM_CONTRACT_ASSET_TYPE_UNSUPPORTED", "Unsupported managed asset type")
        id_field, version_field = IDENTITY_FIELDS[asset_type]
        if (id_field and payload.get(id_field) != asset_id) or payload.get(version_field) != version:
            raise ManagedContractError("SYSTEM_CONTRACT_IDENTITY_INVALID", "Payload identity does not match request")
        if asset_type == "preprocessing_plan" and (not payload.get("dataset_id") or not payload.get("dataset_version")):
            raise ManagedContractError("SYSTEM_CONTRACT_DATASET_IDENTITY_MISSING", "Preprocessing Plan requires dataset identity")
        return hashlib.sha256(canonical_bytes(payload)).hexdigest()

    def read(self, asset_type: str, asset_id: str, version: str) -> dict[str, Any]:
        path = self._path(asset_type, asset_id, version)
        if not path.is_file():
            raise ManagedContractError("SYSTEM_CONTRACT_BASE_VERSION_NOT_FOUND", "Managed contract version not found", 404)
        value = json.loads(path.read_text(encoding="utf-8"))
        self.validate(asset_type, asset_id, version, value)
        return value

    def publish(self, asset_type: str, asset_id: str, version: str, expected_sha256: str, payload: dict[str, Any]) -> dict[str, Any]:
        checksum = self.validate(asset_type, asset_id, version, payload)
        if checksum != expected_sha256:
            raise ManagedContractError("SYSTEM_CONTRACT_INTEGRITY_ERROR", "Payload checksum does not match request")
        path = self._path(asset_type, asset_id, version, payload)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ManagedContractError("SYSTEM_CONTRACT_VERSION_EXISTS", "Managed contract version already exists", 409)
        temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp, "xb") as handle:
                handle.write(canonical_bytes(payload))
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, path)
            except FileExistsError as exc:
                raise ManagedContractError("SYSTEM_CONTRACT_VERSION_EXISTS", "Managed contract version already exists", 409) from exc
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != checksum:
                path.unlink(missing_ok=True)
                raise ManagedContractError("SYSTEM_CONTRACT_INTEGRITY_ERROR", "Published contract checksum verification failed")
        finally:
            temp.unlink(missing_ok=True)
        logical_uri = f"models_store/{path.relative_to(PATHS.models_store).as_posix()}"
        return {"asset_type": asset_type, "asset_id": asset_id, "version": version, "sha256": checksum, "logical_uri": logical_uri, "published": True}

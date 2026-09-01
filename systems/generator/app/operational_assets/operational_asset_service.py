from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from systems.generator.generator_config import PATHS, PROJECT_ROOT

from .operational_asset_schema import AssetValidation, OperationalAssetInventory, OperationalAssetItem


class OperationalAssetInventoryService:
    """Describe assets visible to Generator without exposing physical paths."""

    def __init__(self) -> None:
        self._roots = {
            "ontology": PATHS.ontology.resolve(),
            "models_store": PATHS.models_store.resolve(),
            "data": PATHS.data_dir.resolve(),
            "data_preprocessed": PATHS.data_preprocessed.resolve(),
            "contracts": (PROJECT_ROOT / "contracts").resolve(),
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _logical_uri(self, path: Path) -> str:
        resolved = path.resolve(strict=True)
        for name, root in self._roots.items():
            if resolved == root or root in resolved.parents:
                suffix = resolved.relative_to(root).as_posix()
                return name if not suffix else f"{name}/{suffix}"
        raise ValueError("asset path is outside configured Generator roots")

    @staticmethod
    def _load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return None, [f"json_parse_failed: {exc}"]
        return (value, []) if isinstance(value, dict) else (None, ["json_object_required"])

    @staticmethod
    def _validate_official_schema(data: dict[str, Any], schema_filename: str | None) -> list[str]:
        if schema_filename is None:
            return []
        schema_path = PROJECT_ROOT / "contracts" / "schemas" / schema_filename
        if not schema_path.is_file():
            return [f"official_schema_missing: {schema_filename}"]
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema).validate(data)
        except Exception as exc:
            return [f"official_schema_invalid: {exc}"]
        return []

    def _item(self, *, path: Path, asset_type: str, asset_key: str, version: str,
              schema_id: str | None, active: bool = False,
              errors: list[str] | None = None, validated: bool = False) -> OperationalAssetItem:
        problems = list(errors or [])
        logical_uri = self._logical_uri(path)
        checksum = self._sha256(path)
        return OperationalAssetItem(
            asset_type=asset_type, asset_key=asset_key or path.stem,
            version=version or "unversioned",
            registry_status="invalid" if problems else ("verified" if validated else "discovered"),
            lifecycle_status="published" if not problems else None,
            logical_uri=logical_uri, sha256=checksum, schema_id=schema_id,
            size_bytes=path.stat().st_size, active=active and not problems,
            validation=AssetValidation(
                status="invalid" if problems else ("valid" if validated else "not_validated"),
                checked_at=datetime.now(timezone.utc), errors=problems,
            ),
        )

    def _mapping_items(self) -> Iterable[OperationalAssetItem]:
        root = PATHS.mapping_root.resolve()
        if not root.exists():
            return []
        items: list[OperationalAssetItem] = []
        for path in sorted(root.rglob("*.json")):
            data, errors = self._load_json(path)
            data = data or {}
            mapping_id = str(data.get("mapping_id") or path.stem)
            version = str(data.get("mapping_version") or "unversioned")
            errors.extend(self._validate_official_schema(data, "generator-static-mapping-table.schema.json") if data else [])
            items.append(self._item(
                path=path, asset_type="static_mapping", asset_key=mapping_id,
                version=version, schema_id="generator-static-mapping-table",
                active=mapping_id == PATHS.extraction_mapping_id and version == PATHS.extraction_mapping_version,
                errors=errors, validated=not errors,
            ))
        return items

    def _json_assets(self, root: Path, filename: str, asset_type: str, schema_id: str,
                     schema_filename: str | None = None) -> Iterable[OperationalAssetItem]:
        if not root.exists():
            return []
        items: list[OperationalAssetItem] = []
        for path in sorted(root.rglob(filename)):
            data, errors = self._load_json(path)
            data = data or {}
            declared_files = data.get("artifact_files") if asset_type == "model_artifact" else data.get("files")
            if isinstance(declared_files, list):
                for declared in declared_files:
                    if not isinstance(declared, dict) or not declared.get("path") or not declared.get("sha256"):
                        errors.append("declared_file_contract_invalid")
                        continue
                    member = (path.parent / str(declared["path"])).resolve()
                    if path.parent.resolve() not in member.parents or not member.is_file():
                        errors.append(f"declared_file_missing: {declared['path']}")
                        continue
                    if self._sha256(member) != str(declared["sha256"]):
                        errors.append(f"declared_file_checksum_mismatch: {declared['path']}")
            asset_key = str(data.get("model_id") or data.get("dataset_id") or data.get("model_set_id") or path.parent.name)
            version = str(data.get("model_version") or data.get("feature_dataset_version") or data.get("preprocessing_plan_version") or data.get("model_set_version") or path.parent.name)
            errors.extend(self._validate_official_schema(data, schema_filename) if data else [])
            items.append(self._item(path=path, asset_type=asset_type, asset_key=asset_key,
                                    version=version, schema_id=schema_id, errors=errors,
                                    validated=schema_filename is not None and not errors))
        return items

    def _versioned_config_assets(
        self,
        roots: Iterable[Path],
        *,
        asset_type: str,
        version_fields: tuple[str, ...],
        schema_id: str,
        official_schema: str | None = None,
    ) -> Iterable[OperationalAssetItem]:
        items: list[OperationalAssetItem] = []
        seen_paths: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.json")):
                resolved = path.resolve()
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                data, errors = self._load_json(resolved)
                data = data or {}
                version = next((str(data[field]) for field in version_fields if data.get(field)), resolved.stem)
                errors.extend(self._validate_official_schema(data, official_schema) if data else [])
                items.append(self._item(
                    path=resolved, asset_type=asset_type, asset_key=schema_id,
                    version=version, schema_id=schema_id, errors=errors,
                    validated=official_schema is not None and not errors,
                ))
        return items

    def _contract_asset(self, filename: str, asset_type: str) -> OperationalAssetItem | None:
        path = PROJECT_ROOT / "contracts" / "schemas" / filename
        if not path.is_file():
            return None
        data, errors = self._load_json(path)
        data = data or {}
        if data:
            try:
                jsonschema.Draft202012Validator.check_schema(data)
            except Exception as exc:
                errors.append(f"json_schema_invalid: {exc}")
        return self._item(
            path=path, asset_type=asset_type,
            asset_key=str(data.get("$id") or path.stem), version="current",
            schema_id=str(data.get("$id") or path.stem), errors=errors,
            validated=not errors,
        )

    def build_inventory(self) -> OperationalAssetInventory:
        assets: list[OperationalAssetItem] = list(self._mapping_items())
        assets.extend(self._json_assets(PATHS.models_store / "cache" / "preprocessing_plans", "pp-*.json", "preprocessing_plan", "generator-preprocessing-plan"))
        assets.extend(self._json_assets(PATHS.models_store / "cache" / "features", "feature_metadata.json", "feature_dataset_bundle", "generator-feature-dataset-bundle"))
        assets.extend(self._json_assets(PATHS.models_store / "artifacts", "manifest.json", "model_artifact", "model-artifact-v1.0", "model-artifact.schema.json"))
        assets.extend(self._versioned_config_assets(
            [PATHS.models_store / "schemas" / "features", PATHS.data_dir / "schemas" / "features"],
            asset_type="feature_schema", version_fields=("feature_schema_version", "schema_version"),
            schema_id="feature-schema",
        ))
        assets.extend(self._versioned_config_assets(
            [PATHS.models_store / "schemas" / "labels", PATHS.data_dir / "schemas" / "labels"],
            asset_type="label_schema", version_fields=("label_schema_version", "schema_version"),
            schema_id="label-schema",
        ))
        assets.extend(self._versioned_config_assets(
            [PATHS.models_store / "schemas" / "history", PATHS.data_dir / "schemas" / "history"],
            asset_type="history_requirement", version_fields=("history_requirement_version", "schema_version"),
            schema_id="history-requirement",
        ))
        assets.extend(self._versioned_config_assets(
            [PATHS.models_store / "training_configs", PATHS.data_dir / "training_configs"],
            asset_type="training_config", version_fields=("training_config_version",),
            schema_id="generator-training-config", official_schema="generator-training-config.schema.json",
        ))
        for filename, asset_type in (
            ("generator-gen-data-sensor-stream-record.schema.json", "protocol_contract"),
            ("generator-protocol-record.schema.json", "protocol_contract"),
            ("generator-dataset-input-manifest.schema.json", "dataset_contract"),
            ("dataset-manifest.schema.json", "dataset_contract"),
            ("dataset-bundle-manifest.schema.json", "dataset_contract"),
        ):
            contract = self._contract_asset(filename, asset_type)
            if contract is not None:
                assets.append(contract)
        for latest in sorted((PATHS.models_store / "artifacts").glob("*/latest.json")) if (PATHS.models_store / "artifacts").exists() else []:
            pointer_data, pointer_errors = self._load_json(latest)
            if pointer_errors or not pointer_data:
                continue
            model_id = str(pointer_data.get("model_id") or latest.parent.name)
            model_version = str(pointer_data.get("model_version") or "")
            for item in assets:
                if item.asset_type == "model_artifact" and item.asset_key == model_id and item.version == model_version:
                    item.active = item.validation.status == "valid"
                    item.pointer_ref = self._logical_uri(latest)
        preprocessing_root = PATHS.models_store / "cache" / "preprocessing_plans"
        for latest in sorted(preprocessing_root.rglob("latest.json")) if preprocessing_root.exists() else []:
            pointer_data, pointer_errors = self._load_json(latest)
            if pointer_errors or not pointer_data:
                continue
            target_name = str(pointer_data.get("path") or "")
            for item in assets:
                if item.asset_type == "preprocessing_plan" and target_name and item.logical_uri.endswith(target_name):
                    item.active = item.validation.status != "invalid"
                    item.pointer_ref = self._logical_uri(latest)
        pointer = PATHS.models_store / "active-model-set.json"
        if pointer.is_file():
            data, errors = self._load_json(pointer)
            data = data or {}
            errors.extend(self._validate_official_schema(data, "generator-active-model-set.schema.json") if data else [])
            dependencies = []
            model_entries = (data.get("models") or {}).items() if isinstance(data.get("models"), dict) else []
            for model_id, config in model_entries:
                if isinstance(config, dict) and config.get("model_version"):
                    dependencies.append({"asset_type": "model_artifact", "asset_key": str(model_id), "version": str(config["model_version"])})
            item = self._item(
                path=pointer, asset_type="active_model_set",
                asset_key=str(data.get("model_set_id") or "active-model-set"),
                version=str(data.get("model_set_version") or "unversioned"),
                schema_id="generator-active-model-set", active=not errors, errors=errors,
                validated=not errors,
            )
            item.dependencies = dependencies
            assets.append(item)
        identities: dict[tuple[str, str, str], list[OperationalAssetItem]] = {}
        for item in assets:
            key = (item.asset_type, item.asset_key, item.version)
            identities.setdefault(key, []).append(item)
        for same_identity in identities.values():
            if len({item.sha256 for item in same_identity}) > 1:
                for item in same_identity:
                    item.registry_status = "conflicted"
                    item.validation.status = "invalid"
                    item.validation.errors.append("duplicate_identity_checksum_conflict")
        unique_assets: list[OperationalAssetItem] = []
        for same_identity in identities.values():
            representative = same_identity[0]
            if len(same_identity) > 1:
                representative.validation.errors.extend(
                    f"conflicting_uri: {item.logical_uri}" for item in same_identity[1:]
                )
            unique_assets.append(representative)
        return OperationalAssetInventory(
            contract_version="generator-operational-asset-inventory-v1",
            source_system="systems/generator",
            generated_at=datetime.now(timezone.utc),
            generator_runtime_version=os.getenv("GENERATOR_RUNTIME_VERSION", "").strip() or "unconfigured",
            assets=unique_assets,
        )

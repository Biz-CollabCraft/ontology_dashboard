from __future__ import annotations

from typing import Any
import json
from pathlib import Path

import jsonschema

from .ports import OperationalAssetInventoryPort, OperationalAssetRegistryPort
from .system_operation_exception import OperationalAssetNotFound


class SystemOperationService:
    def __init__(self, registry: OperationalAssetRegistryPort, inventory: OperationalAssetInventoryPort | None = None) -> None:
        self.registry = registry
        self.inventory = inventory

    def reconcile(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        schema_path = Path(__file__).resolve().parents[4] / "contracts" / "schemas" / "generator-operational-asset-inventory.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(snapshot)
        identities: set[tuple[str, str, str]] = set()
        for item in snapshot["assets"]:
            identity = (item["asset_type"], item["asset_key"], item["version"])
            if identity in identities:
                raise ValueError(f"duplicate operational asset identity: {identity}")
            identities.add(identity)
        return self.registry.reconcile(snapshot)

    def refresh(self) -> dict[str, Any]:
        if self.inventory is None:
            raise RuntimeError("Generator operational asset inventory client is not configured")
        return self.reconcile(self.inventory.fetch_inventory())

    def list_assets(self, *, asset_type: str | None = None, registry_status: str | None = None,
                    validation_status: str | None = None, active: bool | None = None,
                    search: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        items, total = self.registry.list_assets(
            asset_type=asset_type, registry_status=registry_status,
            validation_status=validation_status, active=active,
            search=search.strip() if search else None,
            limit=min(max(limit, 1), 200), offset=max(offset, 0),
        )
        return {"items": items, "total": total}

    def get_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self.registry.get_asset(asset_id)
        if asset is None:
            raise OperationalAssetNotFound(asset_id)
        versions = self._resolve_dependencies(self.registry.list_versions(asset_id))
        asset["versions"] = versions
        if versions:
            representative = sorted(
                versions,
                key=lambda item: (bool(item["is_active"]), item["last_seen_at"], item["version"], item["id"]),
                reverse=True,
            )[0]
            active_count = sum(bool(item["is_active"]) for item in versions)
            asset.update({
                "current_version": representative["version"],
                "registry_status": "conflicted" if active_count > 1 else representative["registry_status"],
                "lifecycle_status": representative["lifecycle_status"],
                "validation_status": representative["validation_status"],
                "active": bool(representative["is_active"]),
                "logical_uri": representative["logical_uri"],
                "sha256": representative["sha256"],
                "schema_id": representative["schema_id"],
                "schema_version": representative["schema_version"],
                "last_seen_at": representative["last_seen_at"],
            })
        return asset

    def list_versions(self, asset_id: str) -> list[dict[str, Any]]:
        if self.registry.get_asset(asset_id) is None:
            raise OperationalAssetNotFound(asset_id)
        return self._resolve_dependencies(self.registry.list_versions(asset_id))

    def latest_reconciliation(self) -> dict[str, Any] | None:
        return self.registry.latest_reconciliation()

    def _resolve_dependencies(self, versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in versions:
            resolved: list[dict[str, Any]] = []
            for dependency in item.get("dependencies") or []:
                value = dict(dependency)
                target = self.registry.resolve_dependency(
                    str(value.get("asset_type") or ""),
                    str(value.get("asset_key") or ""),
                    str(value.get("version") or ""),
                )
                if target is None:
                    value["resolution_status"] = "missing"
                elif target.get("version_id") is None:
                    value.update({"resolved_asset_id": target["asset_id"], "resolution_status": "version_missing"})
                else:
                    value.update({
                        "resolved_asset_id": target["asset_id"],
                        "resolved_version_id": target["version_id"],
                        "resolution_status": "unavailable" if target["registry_status"] == "unavailable" else "resolved",
                    })
                resolved.append(value)
            item["dependencies"] = resolved
        return versions

from __future__ import annotations

import os
from typing import Any

import httpx


class GeneratorOperationalAssetInventoryUnavailable(RuntimeError):
    pass


class GeneratorOperationalAssetInventoryClient:
    def __init__(self, endpoint: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.endpoint = (endpoint if endpoint is not None else os.getenv("GENERATOR_OPERATIONAL_ASSET_INVENTORY_URL", "")).strip()
        self.client = client

    def fetch_inventory(self) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not self.endpoint or not token:
            raise GeneratorOperationalAssetInventoryUnavailable("Generator operational asset inventory is not configured")
        try:
            headers = {"X-System-Operations-Token": token}
            response = self.client.get(self.endpoint, headers=headers) if self.client else httpx.get(self.endpoint, headers=headers, timeout=10.0)
        except httpx.HTTPError as exc:
            raise GeneratorOperationalAssetInventoryUnavailable(str(exc)) from exc
        if response.is_error:
            raise GeneratorOperationalAssetInventoryUnavailable(f"Generator inventory returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise GeneratorOperationalAssetInventoryUnavailable("Generator inventory response must be an object")
        return payload

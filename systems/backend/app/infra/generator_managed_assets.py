from __future__ import annotations

import os
from typing import Any

import httpx


class GeneratorManagedAssetClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("GENERATOR_INTERNAL_API_URL", "")).strip().rstrip("/")
        self.client = client

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not self.base_url or not token:
            raise RuntimeError("Generator managed contract API is not configured")
        headers = {"X-System-Operations-Token": token}
        if self.client:
            response = self.client.request(method, f"{self.base_url}{path}", headers=headers, json=payload)
        else:
            response = httpx.request(method, f"{self.base_url}{path}", headers=headers, json=payload, timeout=60.0)
        if response.is_error:
            raise RuntimeError(f"Generator managed contract API returned HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("Generator managed contract response must be an object")
        return value

    def read(self, asset_type: str, asset_id: str, version: str) -> dict[str, Any]:
        return self._request("GET", f"/internal/operational-contracts/{asset_type}/{asset_id}/versions/{version}")

    def publish(self, asset_type: str, asset_id: str, version: str, checksum: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/internal/operational-contracts/{asset_type}/{asset_id}/publish", {"version": version, "expected_sha256": checksum, "payload": payload})

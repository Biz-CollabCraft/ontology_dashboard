from __future__ import annotations

import os
from typing import Any

import httpx


class GeneratorMappingManagementUnavailable(RuntimeError):
    pass


class GeneratorMappingManagementClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        configured = base_url if base_url is not None else os.getenv("GENERATOR_MAPPING_MANAGEMENT_URL", "")
        self.base_url = configured.strip().rstrip("/")
        self.client = client

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not self.base_url or not token:
            raise GeneratorMappingManagementUnavailable("Generator Mapping management is not configured")
        headers = {"X-System-Operations-Token": token}
        try:
            if self.client:
                response = self.client.request(method, f"{self.base_url}{path}", headers=headers, json=payload)
            else:
                response = httpx.request(method, f"{self.base_url}{path}", headers=headers, json=payload, timeout=15.0)
        except httpx.HTTPError as exc:
            raise GeneratorMappingManagementUnavailable(str(exc)) from exc
        if response.is_error:
            raise GeneratorMappingManagementUnavailable(f"Generator Mapping API returned HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise GeneratorMappingManagementUnavailable("Generator Mapping response must be an object")
        return value

    def read_mapping(self, mapping_id: str, version: str) -> dict[str, Any]:
        return self._request("GET", f"/{mapping_id}/versions/{version}")

    def validate_mapping(self, mapping_id: str, version: str, mapping: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/validate", {"mapping_id": mapping_id, "mapping_version": version, "mapping": mapping})

    def publish_mapping(self, request_id: str, mapping_id: str, version: str, checksum: str, mapping: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/publish", {"request_id": request_id, "mapping_id": mapping_id, "mapping_version": version, "expected_sha256": checksum, "mapping": mapping})

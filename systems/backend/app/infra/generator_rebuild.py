from __future__ import annotations

import os
from typing import Any
import httpx


class GeneratorRebuildUnavailable(RuntimeError):
    pass


class GeneratorRebuildClient:
    def __init__(self, rebuild_url: str | None = None, mapping_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.rebuild_url = (rebuild_url if rebuild_url is not None else os.getenv("GENERATOR_REBUILD_URL", "")).strip().rstrip("/")
        self.mapping_url = (mapping_url if mapping_url is not None else os.getenv("GENERATOR_MAPPING_MANAGEMENT_URL", "")).strip().rstrip("/")
        self.client = client

    def _request(self, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not url or not token:
            raise GeneratorRebuildUnavailable("Generator rebuild is not configured")
        try:
            response = self.client.post(url, headers={"X-System-Operations-Token": token}, json=payload) if self.client else httpx.post(url, headers={"X-System-Operations-Token": token}, json=payload, timeout=300.0)
        except httpx.HTTPError as exc:
            raise GeneratorRebuildUnavailable(str(exc)) from exc
        if response.is_error:
            raise GeneratorRebuildUnavailable(f"Generator returned HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise GeneratorRebuildUnavailable("Generator response must be an object")
        return value

    def rebuild(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(f"{self.rebuild_url}/extraction", payload)

    def read_mapping(self, mapping_id: str, mapping_version: str) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        url = f"{self.mapping_url}/{mapping_id}/versions/{mapping_version}"
        if not self.mapping_url or not token:
            raise GeneratorRebuildUnavailable("Generator Mapping management is not configured")
        try:
            response = self.client.get(url, headers={"X-System-Operations-Token": token}) if self.client else httpx.get(url, headers={"X-System-Operations-Token": token}, timeout=15.0)
        except httpx.HTTPError as exc:
            raise GeneratorRebuildUnavailable(str(exc)) from exc
        if response.is_error or not isinstance(response.json(), dict):
            raise GeneratorRebuildUnavailable(f"Generator Mapping API returned HTTP {response.status_code}")
        return response.json()

    def activate(self, mapping_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request(f"{self.mapping_url}/{mapping_id}/activate", payload)

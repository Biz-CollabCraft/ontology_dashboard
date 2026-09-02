from __future__ import annotations

import os
from typing import Any

import httpx


class GeneratorModelOperationClient:
    def __init__(self, base_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("GENERATOR_INTERNAL_API_URL", "")).strip().rstrip("/")
        self.client = client

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not self.base_url or not token:
            raise RuntimeError("Generator model operation API is not configured")
        headers = {"X-System-Operations-Token": token}
        response = self.client.request(method, f"{self.base_url}{path}", headers=headers, json=payload) if self.client else httpx.request(method, f"{self.base_url}{path}", headers=headers, json=payload, timeout=60.0)
        if response.is_error:
            detail = response.json().get("detail", {}) if response.headers.get("content-type", "").startswith("application/json") else {}
            code = detail.get("code", "MODEL_OPERATION_GENERATOR_ERROR") if isinstance(detail, dict) else "MODEL_OPERATION_GENERATOR_ERROR"
            raise RuntimeError(f"{code}: Generator returned HTTP {response.status_code}")
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("Generator model operation response must be an object")
        return value

    def list_models(self): return self._request("GET", "/internal/model-operations/models")
    def get_selection(self, model_id: str): return self._request("GET", f"/internal/model-operations/models/{model_id}/selection")
    def select(self, model_id: str, body: dict[str, Any]): return self._request("POST", f"/internal/model-operations/models/{model_id}/select", body)
    def clear(self, model_id: str, body: dict[str, Any]): return self._request("POST", f"/internal/model-operations/models/{model_id}/clear-selection", body)
    def get_active(self): return self._request("GET", "/internal/model-operations/active-model-set")
    def validate_set(self, body: dict[str, Any]): return self._request("POST", "/internal/model-operations/active-model-set/validate", body)
    def activate_set(self, body: dict[str, Any]): return self._request("POST", "/internal/model-operations/active-model-set/activate", body)
    def rollback_set(self, body: dict[str, Any]): return self._request("POST", "/internal/model-operations/active-model-set/rollback", body)

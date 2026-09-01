from __future__ import annotations

import os
from typing import Any

import httpx


class GeneratorDownstreamUnavailable(RuntimeError):
    pass


class GeneratorDownstreamClient:
    """HTTP client for Generator's canonical pipeline-stage APIs."""

    def __init__(self, base_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.base_url = (
            base_url if base_url is not None else os.getenv("GENERATOR_INTERNAL_API_URL", "")
        ).strip().rstrip("/")
        self.client = client

    def execute(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        if stage not in {"preprocessing", "feature", "training"}:
            raise GeneratorDownstreamUnavailable(f"Unsupported downstream stage: {stage}")
        if not self.base_url:
            raise GeneratorDownstreamUnavailable("Generator internal API is not configured")
        body = dict(payload)
        endpoint = "/train" if stage == "training" else f"/{stage}"
        if stage == "training":
            body["activation_policy"] = "publish_only"
        try:
            if self.client:
                response = self.client.post(f"{self.base_url}{endpoint}", json=body)
            else:
                response = httpx.post(f"{self.base_url}{endpoint}", json=body, timeout=600.0)
        except httpx.HTTPError as exc:
            raise GeneratorDownstreamUnavailable(str(exc)) from exc
        if response.is_error:
            raise GeneratorDownstreamUnavailable(
                f"Generator {stage} returned HTTP {response.status_code}: {response.text[:500]}"
            )
        value = response.json()
        if not isinstance(value, dict):
            raise GeneratorDownstreamUnavailable(f"Generator {stage} response must be an object")
        return value

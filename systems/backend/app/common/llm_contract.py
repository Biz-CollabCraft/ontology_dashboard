"""Transport-independent structured generation contract and failure type."""
from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def generate_json(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = "structured_response",
    ) -> dict[str, Any]: ...

    def generate_json_with_metadata(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str = "structured_response",
    ) -> dict[str, Any]: ...


class ProviderUnavailable(RuntimeError):
    pass

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManagedContractPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: dict[str, Any]

    @field_validator("expected_sha256")
    @classmethod
    def checksum_must_be_nonzero(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("expected_sha256 cannot be zero")
        return value


class ManagedContractPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_type: Literal["preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config"]
    asset_id: str
    version: str
    sha256: str
    logical_uri: str
    published: bool

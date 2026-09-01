from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MappingValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping: dict[str, Any]


class MappingValidationResponse(BaseModel):
    status: str
    mapping_sha256: str
    normalized_mapping: dict[str, Any]
    errors: list[dict[str, Any]] = Field(default_factory=list)


class MappingPublishRequest(MappingValidationRequest):
    request_id: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class MappingPublishResponse(BaseModel):
    mapping_id: str
    mapping_version: str
    mapping_sha256: str
    logical_uri: str
    published_at: str
    idempotent: bool


class MappingActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activated_by_job_id: str = Field(min_length=1)

    @field_validator("mapping_sha256")
    @classmethod
    def reject_zero_checksum(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("mapping_sha256 cannot be the zero checksum")
        return value


class MappingActivationResponse(BaseModel):
    mapping_id: str
    mapping_version: str
    mapping_sha256: str
    activated_by_job_id: str
    activated_at: str
    idempotent: bool

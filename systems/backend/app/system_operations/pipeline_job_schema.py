from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PipelineJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_type: Literal["mapping_rebuild"] = "mapping_rebuild"
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_uri: str = Field(min_length=1)
    replay_scope: Literal["full_source"] = "full_source"
    activate_on_success: bool = True
    idempotency_key: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("mapping_sha256")
    @classmethod
    def reject_zero_checksum(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("mapping_sha256 cannot be zero")
        return value

    @field_validator("source_uri")
    @classmethod
    def safe_source_uri(cls, value: str) -> str:
        clean = value.strip().replace("\\", "/")
        if clean.startswith("/") or ".." in clean.split("/"):
            raise ValueError("source_uri must be a safe logical relative path")
        return clean

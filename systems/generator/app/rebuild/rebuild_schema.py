from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractionRebuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    replay_scope: Literal["full_source"] = "full_source"
    max_records: int = Field(default=10000, gt=0)

    @field_validator("mapping_sha256")
    @classmethod
    def reject_zero_checksum(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("mapping_sha256 cannot be the zero checksum")
        return value


class ExtractionRebuildResponse(BaseModel):
    job_id: str
    run_id: str
    status: Literal["succeeded", "no_data"]
    source_identity: str | None
    mapping_id: str
    mapping_version: str
    mapping_sha256: str
    processed_records: int
    rejected_records: int
    published_datasets: list[dict]

from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class ImpactAnalysisCreate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mapping_id:str=Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_version:str=Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    mapping_sha256:str=Field(pattern=r"^[a-f0-9]{64}$")
    rebuild_job_id:str=Field(min_length=1)
    include_stages:list[Literal["preprocessing","feature","training"]]=Field(min_length=1)
    @field_validator("mapping_sha256")
    @classmethod
    def nonzero(cls,v):
        if v=="0"*64: raise ValueError("mapping checksum cannot be zero")
        return v


class DownstreamRebuildCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_action_ids: list[str] = Field(min_length=1)
    training_selection: dict | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("expected_snapshot_sha256")
    @classmethod
    def snapshot_must_be_nonzero(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("snapshot checksum cannot be zero")
        return value

    @field_validator("selected_action_ids")
    @classmethod
    def actions_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("selected_action_ids must be unique")
        return value

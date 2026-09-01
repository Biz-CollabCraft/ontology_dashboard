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

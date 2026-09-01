from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MappingDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    target_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    base_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class MappingDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    payload: dict[str, Any]


class MappingDraftPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ManagedAssetType = Literal[
    "preprocessing_plan", "feature_schema", "label_schema",
    "history_requirement", "training_config",
]


class ManagedAssetDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_type: ManagedAssetType
    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    target_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    base_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class ManagedAssetDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    payload: dict[str, Any]
    reason: str = Field(min_length=1, max_length=1000)


class ManagedAssetDraftPublish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    expected_payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=1000)

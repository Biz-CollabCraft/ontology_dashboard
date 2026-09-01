from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ManagedContractPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    expected_sha256: str = Field(pattern=r"^(?!0{64}$)[a-f0-9]{64}$")
    payload: dict[str, Any]


class ManagedContractPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_type: Literal["preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config"]
    asset_id: str
    version: str
    sha256: str
    logical_uri: str
    published: bool

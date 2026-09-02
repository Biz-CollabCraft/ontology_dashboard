from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SHA256_PATTERN = r"^[a-f0-9]{64}$"


class ModelSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    model_artifact_manifest_sha256: str = Field(..., pattern=SHA256_PATTERN)
    reason: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(..., min_length=1)


class ModelSelectionClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_selection_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(..., min_length=1)


class ModelSetCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    model_version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]+$")
    required: bool = True


class ActiveModelSetOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_set_id: str = Field(..., min_length=1)
    model_set_version: str = Field(..., min_length=1)
    models: list[ModelSetCandidate] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(..., min_length=1)


class ModelSetRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_set_id: str = Field(..., min_length=1)
    model_set_version: str = Field(..., min_length=1)
    models: list[ModelSetCandidate] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(..., min_length=1)
    action: Literal["rollback"] = "rollback"

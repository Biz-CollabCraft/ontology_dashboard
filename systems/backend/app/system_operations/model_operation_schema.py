from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ModelSelectRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    model_version: str = Field(..., min_length=1)
    model_artifact_manifest_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(..., min_length=1)


class ModelSelectionClearRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    expected_selection_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ModelSetOperationRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    model_set_id: str = Field(..., min_length=1)
    model_set_version: str = Field(..., min_length=1)
    models: list[dict[str, Any]] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class ModelSetRollbackRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)

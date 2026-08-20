"""Pydantic schemas for Generator training API (/train)."""

from __future__ import annotations

import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

FEATURE_DATASET_VERSION_PATTERN = r"^feature-dataset-[0-9a-f]{16}$"


class TrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_dataset_version: str = Field(
        ...,
        description="불변 Feature Dataset 식별자 (예: feature-dataset-c3d4e5f678901234)",
        examples=["feature-dataset-c3d4e5f678901234"],
    )
    activation_policy: Literal["latest", "manual"] = Field(
        default="latest",
        description="학습 성공 후 Model Artifact 활성화 정책 (기본값: latest)",
    )

    @field_validator("feature_dataset_version")
    @classmethod
    def validate_feature_dataset_version(cls, v: str) -> str:
        if not isinstance(v, str) or not re.match(FEATURE_DATASET_VERSION_PATTERN, v):
            raise ValueError(
                f"feature_dataset_version 형식이 올바르지 않습니다: '{v}'. "
                f"'feature-dataset-<16자리 hex>' 형식이어야 합니다."
            )
        return v


class ModelResultItem(BaseModel):
    base_model: str
    status: Literal["succeeded", "failed"]
    model_id: str
    model_version: str
    artifact_uri: str
    activation_status: Literal["activated", "published_only", "activation_failed"] = Field(
        default="activated",
        description="Model Artifact 활성화 상태",
    )
    active_model_version: str | None = Field(
        default=None,
        description="현재 활성화된 모델 버전",
    )


class FailedModelItem(BaseModel):
    base_model: str
    code: str
    error_id: str


class TrainingResponse(BaseModel):
    request_id: str
    run_id: str
    status: Literal["succeeded", "partially_succeeded", "failed"]
    feature_dataset_version: str
    results: list[ModelResultItem] = Field(default_factory=list)
    failed_models: list[FailedModelItem] = Field(default_factory=list)


class ModelActivationResponse(BaseModel):
    base_model: str
    previous_model_version: str | None = None
    active_model_version: str
    status: Literal["activated"] = "activated"


class ActiveModelResponse(BaseModel):
    base_model: str
    active_model_version: str
    artifact_uri: str
    updated_at: str

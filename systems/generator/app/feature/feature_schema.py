"""Pydantic schemas and contract definitions for feature domain with identifier verification."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


IDENTIFIER_PATTERN = r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$"


def _validate_safe_identifier(val: str, field_name: str) -> str:
    if not val or not str(val).strip():
        raise ValueError(f"{field_name} must not be empty")
    if not re.match(IDENTIFIER_PATTERN, val) or ".." in val or "/" in val or "\\" in val:
        raise ValueError(f"{field_name} contains invalid characters or path traversal sequences: {val!r}")
    return val


class FeatureRequest(BaseModel):
    dataset_id: str = Field(..., min_length=1, max_length=128, description="Dataset identifier")
    dataset_version: str = Field(..., min_length=1, max_length=64, description="Dataset version string")
    failure_dataset_id: str = Field(..., min_length=1, max_length=128, description="Failure events dataset identifier")
    failure_dataset_version: str = Field(..., min_length=1, max_length=64, description="Failure events dataset version string")
    preprocessing_plan_version: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Preprocessing plan version identifier (e.g. preprocessing-plan-a1b2c3d4e5f67890)",
    )
    mapping_version: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Ontology mapping version identifier (e.g. ontology-mapping-b2c3d4e5f6789012)",
    )
    feature_schema_version: str = Field(..., min_length=1, max_length=64, description="Feature schema version string")
    label_schema_version: str = Field(..., min_length=1, max_length=64, description="Label schema version string")
    prediction_horizon_hours: int = Field(24, gt=0, description="Prediction horizon in hours (must be > 0)")
    rebuild_npy: bool = Field(False, description="Whether to build/rebuild NPY outputs (default: False)")

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "dataset_id")

    @field_validator("dataset_version")
    @classmethod
    def validate_dataset_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "dataset_version")

    @field_validator("failure_dataset_id")
    @classmethod
    def validate_failure_dataset_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "failure_dataset_id")

    @field_validator("failure_dataset_version")
    @classmethod
    def validate_failure_dataset_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "failure_dataset_version")

    @field_validator("preprocessing_plan_version")
    @classmethod
    def validate_preprocessing_plan_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "preprocessing_plan_version")

    @field_validator("mapping_version")
    @classmethod
    def validate_mapping_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "mapping_version")

    @field_validator("feature_schema_version")
    @classmethod
    def validate_feature_schema_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "feature_schema_version")

    @field_validator("label_schema_version")
    @classmethod
    def validate_label_schema_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "label_schema_version")

    @model_validator(mode="after")
    def _validate_request(self) -> "FeatureRequest":
        if self.prediction_horizon_hours <= 0:
            raise ValueError("prediction_horizon_hours must be greater than 0")
        return self


class FeatureOutputsPayload(BaseModel):
    feature_dataset_version: str
    row_count: int
    feature_count: int
    features_uri: str
    labels_uri: str
    metadata_uri: str


class FeatureResponse(BaseModel):
    request_id: str
    run_id: str
    status: Literal["succeeded", "failed"] = "succeeded"
    dataset_id: str
    dataset_version: str
    failure_dataset_id: str
    failure_dataset_version: str
    preprocessing_plan_version: str
    mapping_version: str
    feature_schema_version: str
    label_schema_version: str
    outputs: FeatureOutputsPayload

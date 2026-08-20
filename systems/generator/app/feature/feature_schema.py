"""Pydantic schemas and contract definitions for feature domain with identifier verification."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


IDENTIFIER_PATTERN = r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$"
PLAN_VERSION_PATTERN = r"^extraction-plan-[0-9a-f]{16}$"
MAPPING_VERSION_PATTERN = r"^ontology-mapping-[0-9a-f]{16}$"


def _validate_safe_identifier(val: str, field_name: str) -> str:
    if not re.match(IDENTIFIER_PATTERN, val) or ".." in val or "/" in val or "\\" in val:
        raise ValueError(f"{field_name} contains invalid characters or path traversal sequences: {val!r}")
    return val


class FeatureRequest(BaseModel):
    dataset_id: str = Field(..., min_length=1, max_length=128, description="Dataset identifier")
    dataset_version: str = Field(..., min_length=1, max_length=64, description="Dataset version string")
    failure_dataset_id: str = Field(..., min_length=1, max_length=128, description="Failure events dataset identifier")
    failure_dataset_version: str = Field(..., min_length=1, max_length=64, description="Failure events dataset version string")
    extraction_plan_version: str = Field(
        ...,
        pattern=PLAN_VERSION_PATTERN,
        description="Content-based extraction plan version (e.g. extraction-plan-0123456789abcdef)",
    )
    mapping_version: str = Field(
        ...,
        pattern=MAPPING_VERSION_PATTERN,
        description="Content-based ontology mapping version (e.g. ontology-mapping-0123456789abcdef)",
    )
    feature_schema_version: str = Field(..., min_length=1, max_length=64, description="Feature schema version string")
    label_schema_version: str = Field(..., min_length=1, max_length=64, description="Label schema version string")
    prediction_horizon_hours: int = Field(24, gt=0, description="Prediction horizon in hours (must be > 0)")
    rebuild_npy: bool = Field(True, description="Whether to build/rebuild NPY outputs")

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
        if not self.rebuild_npy:
            raise ValueError("rebuild_npy must be true for POST /feature execution")
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
    extraction_plan_version: str
    mapping_version: str
    feature_schema_version: str
    label_schema_version: str
    outputs: FeatureOutputsPayload

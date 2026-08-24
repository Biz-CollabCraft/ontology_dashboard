"""Pydantic schemas for Feature Dataset generation API."""

from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_identifier(value: str, field_name: str) -> str:
    """Validate identifier contains no path traversal or dangerous characters."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name}은(는) 문자열이어야 합니다.")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{field_name}은(는) 빈 문자열일 수 없습니다.")
    if ".." in trimmed or "/" in trimmed or "\\" in trimmed:
        raise ValueError(f"{field_name}에 허용되지 않는 경로 문자('..', '/', '\\')가 포함되어 있습니다: '{value}'")
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", trimmed):
        raise ValueError(f"{field_name}에 유효하지 않은 특수문자가 포함되어 있습니다: '{value}'")
    return trimmed


class FeatureRequest(BaseModel):
    """Request payload for POST /feature."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(..., description="Observation dataset identifier")
    dataset_version: str = Field(..., description="Observation dataset version")

    failure_dataset_id: str = Field(..., description="Failure dataset identifier")
    failure_dataset_version: str = Field(..., description="Failure dataset version")

    preprocessing_plan_id: str = Field(..., description="Immutable Preprocessing Plan unique ID (pp-{UUID})")
    preprocessing_plan_version: str = Field(..., description="Preprocessing Plan content hash version")

    feature_schema_version: str = Field(..., description="Feature schema specification version")
    label_schema_version: str = Field(..., description="Label schema specification version")

    prediction_horizon_hours: int = Field(default=24, gt=0, description="Prediction horizon in hours")
    rebuild_npy: bool = Field(default=False, description="Whether to force recalculation and overwrite existing bundle")

    @field_validator(
        "dataset_id",
        "dataset_version",
        "failure_dataset_id",
        "failure_dataset_version",
        "preprocessing_plan_id",
        "preprocessing_plan_version",
        "feature_schema_version",
        "label_schema_version",
    )
    @classmethod
    def validate_id_fields(cls, v: str, info) -> str:
        return _validate_identifier(v, info.field_name)


class FeatureOutputsPayload(BaseModel):
    """Payload describing published Feature Dataset Bundle artifacts."""

    feature_dataset_version: str = Field(..., description="Canonical deterministic fingerprint of feature dataset")
    row_count: int = Field(..., ge=0, description="Total number of aligned sample rows")
    feature_count: int = Field(..., ge=0, description="Total number of feature columns")
    features_uri: str = Field(..., description="Logical relative URI to features.npy")
    labels_uri: str = Field(..., description="Logical relative URI to labels.npy")
    metadata_uri: str = Field(..., description="Logical relative URI to feature_metadata.json")


class FeatureResponse(BaseModel):
    """Success response for POST /feature."""

    request_id: str = Field(..., description="Unique request tracing ID")
    run_id: str = Field(..., description="Feature processing execution run ID")
    status: str = Field(default="succeeded", description="Execution status")

    dataset_id: str = Field(..., description="Observation dataset identifier")
    dataset_version: str = Field(..., description="Observation dataset version")
    failure_dataset_id: str = Field(..., description="Failure dataset identifier")
    failure_dataset_version: str = Field(..., description="Failure dataset version")

    preprocessing_plan_id: str = Field(..., description="Consumed Preprocessing Plan ID")
    preprocessing_plan_version: str = Field(..., description="Consumed Preprocessing Plan version")

    feature_schema_version: str = Field(..., description="Applied Feature schema version")
    label_schema_version: str = Field(..., description="Applied Label schema version")

    outputs: FeatureOutputsPayload = Field(..., description="Output bundle artifact references")

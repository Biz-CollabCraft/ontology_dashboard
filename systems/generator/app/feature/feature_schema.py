"""Pydantic schemas and contract definitions for feature domain."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class FeatureRequest(BaseModel):
    dataset_id: str = Field(..., min_length=1, description="Dataset identifier")
    dataset_version: str = Field(..., min_length=1, description="Dataset version string")
    extraction_plan_version: str = Field(..., min_length=1, description="Content-based extraction plan version")
    mapping_version: str = Field(..., min_length=1, description="Content-based ontology mapping version")
    feature_schema_version: str = Field(..., min_length=1, description="Feature schema version string")
    label_schema_version: str = Field(..., min_length=1, description="Label schema version string")
    prediction_horizon_hours: int = Field(24, gt=0, description="Prediction horizon in hours (must be > 0)")
    rebuild_npy: bool = Field(True, description="Whether to build/rebuild NPY outputs")

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
    extraction_plan_version: str
    mapping_version: str
    feature_schema_version: str
    label_schema_version: str
    outputs: FeatureOutputsPayload

"""Pydantic schemas and contract models for Extraction domain."""

from __future__ import annotations

import re
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


IDENTIFIER_PATTERN = r"^[a-zA-Z0-9_-][a-zA-Z0-9_.-]*$"


def _validate_safe_identifier(val: str, field_name: str) -> str:
    if not re.match(IDENTIFIER_PATTERN, val) or ".." in val or "/" in val or "\\" in val:
        raise ValueError(f"{field_name} contains invalid characters or path traversal sequences: {val!r}")
    return val


class ExtractionRequest(BaseModel):
    dataset_id: str = Field(..., min_length=1, max_length=128, description="Dataset identifier")
    dataset_version: str = Field(..., min_length=1, max_length=64, description="Dataset version string")
    source_uri: Optional[str] = Field(None, description="Relative path under allowed data roots")
    force_reanalyze: bool = Field(False, description="Whether to bypass cache and force re-analysis")
    duplicate_policy: Literal["error", "aggregate"] = Field(
        "error",
        description="Policy when duplicate time index entries occur",
    )
    aggregation: Optional[Literal["mean", "first", "sum"]] = Field(
        None,
        description="Aggregation function when duplicate_policy is aggregate",
    )

    @field_validator("dataset_id")
    @classmethod
    def validate_dataset_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "dataset_id")

    @field_validator("dataset_version")
    @classmethod
    def validate_dataset_version(cls, v: str) -> str:
        return _validate_safe_identifier(v, "dataset_version")

    @model_validator(mode="after")
    def _validate_duplicate_policy_and_aggregation(self) -> "ExtractionRequest":
        if self.duplicate_policy == "aggregate" and not self.aggregation:
            raise ValueError("aggregation must be specified when duplicate_policy is 'aggregate'")
        if self.duplicate_policy == "error" and self.aggregation:
            raise ValueError("aggregation cannot be specified when duplicate_policy is 'error'")
        return self


class ExtractionStructureResponse(BaseModel):
    structure_type: Literal["tabular_column_as_attribute", "tabular_row_as_attribute", "wide_pivot"]
    confidence: float = 1.0
    reason: str = ""


class ExtractionColumnsResponse(BaseModel):
    selected_columns: list[str] = Field(default_factory=list)
    id_column: Optional[str] = None
    time_column: Optional[str] = None
    attribute_column: Optional[str] = None
    value_column: Optional[str] = None


class ExtractionPlanResponse(BaseModel):
    structure_type: Literal["tabular_column_as_attribute", "tabular_row_as_attribute", "wide_pivot"] = "tabular_column_as_attribute"
    selected_columns: list[str] = Field(default_factory=list)
    id_column: Optional[str] = None
    time_column: Optional[str] = None
    attribute_column: Optional[str] = None
    value_column: Optional[str] = None
    duplicate_policy: Literal["error", "aggregate"] = "error"
    aggregation: Optional[Literal["mean", "first", "sum"]] = None

    @model_validator(mode="after")
    def _validate_duplicate_policy(self) -> "ExtractionPlanResponse":
        if self.duplicate_policy == "aggregate" and not self.aggregation:
            raise ValueError("duplicate_policy='aggregate' requires a non-null aggregation function")
        if self.duplicate_policy == "error" and self.aggregation:
            raise ValueError("duplicate_policy='error' must not specify an aggregation function")
        return self


class ExtractionResultPayload(BaseModel):
    extraction_type: str
    id_column: Optional[str] = None
    time_column: Optional[str] = None
    attribute_column: Optional[str] = None
    value_column: Optional[str] = None
    duplicate_policy: str
    aggregation: Optional[str] = None
    mapping_version: str
    mapping_uri: str


class ExtractionResponse(BaseModel):
    request_id: str
    run_id: str
    status: Literal["succeeded", "failed"] = "succeeded"
    dataset_id: str
    dataset_version: str
    extraction_plan_version: str
    result: ExtractionResultPayload


class ErrorEnvelopeBody(BaseModel):
    code: str
    message: str
    path: str
    request_id: str
    error_id: str
    details: list[Any] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    error: ErrorEnvelopeBody

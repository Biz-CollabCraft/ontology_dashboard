"""Pydantic schemas and contract definitions for Generator Protocol Extraction."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"


def _validate_safe_identifier(v: str, field_name: str) -> str:
    cleaned = str(v).strip()
    if not cleaned:
        raise ValueError(f"{field_name}은(는) 빈 문자열일 수 없습니다.")
    if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"{field_name}에 안전하지 않은 경로 탐색 문자('..', '/', '\\')가 포함되어 있습니다: '{v}'")
    if not re.match(IDENTIFIER_PATTERN, cleaned):
        raise ValueError(f"{field_name}의 형식이 올바르지 않습니다: '{v}' (허용: 영숫자, '.', '_', '-')")
    return cleaned


class ExtractionRequest(BaseModel):
    """Request payload for POST /extraction."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(..., min_length=1, description="Unique API request identifier")
    idempotency_key: str = Field(..., min_length=1, description="Idempotent execution key")
    run_id: str = Field(..., min_length=1, description="Unique extraction run identifier")
    source_uri: str = Field(..., min_length=1, description="Source protocol log file path")
    source_sha256: str = Field(..., pattern=SHA256_PATTERN, description="Expected SHA-256 checksum of source file")
    source_direction: Literal["published", "received"] = Field(
        default="received",
        description="Target transmission direction to extract. Only matching direction records are consumed."
    )
    source_run_manifest_uri: Optional[str] = Field(
        default=None,
        description="Optional upstream gen_data run manifest URI to verify finalization"
    )
    source_run_manifest_sha256: Optional[str] = Field(
        default=None,
        pattern=SHA256_PATTERN,
        description="Optional upstream gen_data run manifest SHA-256 checksum"
    )
    source_schema_version: str = Field(..., min_length=1, description="Source sensor protocol schema version")
    protocol_version: str = Field(..., min_length=1, description="Protocol version string")
    mapping_id: str = Field(..., min_length=1, description="Approved static mapping table identifier")
    mapping_version: str = Field(..., min_length=1, description="Approved static mapping version string")
    mapping_sha256: str = Field(..., pattern=SHA256_PATTERN, description="SHA-256 checksum of mapping table definition")
    dataset_id: str = Field(..., pattern=IDENTIFIER_PATTERN, description="Target Canonical Observation dataset ID")
    dataset_version: str = Field(..., pattern=IDENTIFIER_PATTERN, description="Target dataset version string")

    @field_validator("request_id", "idempotency_key", "run_id")
    @classmethod
    def validate_keys(cls, v: str) -> str:
        cleaned = str(v).strip()
        if not cleaned:
            raise ValueError("식별자 필드는 빈 문자열일 수 없습니다.")
        if ".." in cleaned or "/" in cleaned or "\\" in cleaned:
            raise ValueError(f"식별자에 안전하지 않은 문자('..', '/', '\\')가 포함되어 있습니다: '{v}'")
        return cleaned

    @field_validator("dataset_id", "dataset_version")
    @classmethod
    def validate_dataset_identifiers(cls, v: str) -> str:
        return _validate_safe_identifier(v, "dataset identifier")

    @field_validator("source_uri")
    @classmethod
    def validate_source_uri(cls, v: str) -> str:
        cleaned = str(v).strip().replace("\\", "/")
        if not cleaned:
            raise ValueError("source_uri는 빈 문자열일 수 없습니다.")
        if ".." in cleaned.split("/"):
            raise ValueError(f"source_uri에 상위 디렉터리 탐색(..)이 포함될 수 없습니다: '{v}'")
        return cleaned


class ExtractionTimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_time: str
    max_time: str


class ExtractionResultPayload(BaseModel):
    """Payload body included in ExtractionResponse."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    dataset_version: str
    manifest_uri: str
    manifest_sha256: str = Field(..., pattern=SHA256_PATTERN)
    observations_uri: str
    observations_sha256: str = Field(..., pattern=SHA256_PATTERN)
    provenance_uri: str
    provenance_sha256: str = Field(..., pattern=SHA256_PATTERN)
    rejected_uri: str
    rejected_sha256: str = Field(..., pattern=SHA256_PATTERN)
    total_records_processed: int = Field(..., ge=0)
    observations_count: int = Field(..., ge=0)
    rejected_count: int = Field(..., ge=0)
    asset_ids: list[str] = Field(default_factory=list)
    time_range: Optional[ExtractionTimeRange] = None


class ExtractionResponse(BaseModel):
    """Response returned by POST /extraction."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    idempotency_key: str
    run_id: str
    status: Literal["succeeded"] = "succeeded"
    dataset_id: str
    dataset_version: str
    result: ExtractionResultPayload


# --- Internal Domain Record Models ---

class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    observed_at: str
    measurement_key: str
    source_observation_id: str
    source_sequence: int
    source_direction: str
    source_status_code: Optional[str] = None
    source_quality: Optional[str] = None
    mapping_id: str
    mapping_version: str
    mapping_sha256: str
    extraction_run_id: str


class RejectedRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    source_offset: Optional[int] = None
    source_sequence: Optional[int] = None
    source_observation_id: Optional[str] = None
    error_code: str
    error_message: str
    mapping_id: Optional[str] = None
    mapping_version: Optional[str] = None
    run_id: Optional[str] = None
    raw_record_checksum: Optional[str] = None
    rejected_at: str

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AssetType = Literal[
    "static_mapping", "preprocessing_plan", "feature_schema", "label_schema",
    "history_requirement", "training_config", "feature_dataset_bundle",
    "model_artifact", "active_model_set", "protocol_contract", "dataset_contract",
]
RegistryStatus = Literal["discovered", "verified", "invalid", "conflicted"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetValidation(StrictModel):
    status: Literal["valid", "invalid", "not_validated"]
    checked_at: datetime
    errors: list[str] = Field(default_factory=list)


class OperationalAssetItem(StrictModel):
    asset_type: AssetType
    asset_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    registry_status: RegistryStatus
    lifecycle_status: str | None = None
    logical_uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_id: str | None = None
    schema_version: str | None = None
    content_type: str = "application/json"
    size_bytes: int = Field(ge=0)
    active: bool = False
    pointer_ref: str | None = None
    dependencies: list[dict[str, str]] = Field(default_factory=list)
    validation: AssetValidation

    @field_validator("sha256")
    @classmethod
    def reject_zero_checksum(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("sha256 must not be the all-zero placeholder")
        return value


class OperationalAssetInventory(StrictModel):
    contract_version: Literal["generator-operational-asset-inventory-v1"]
    source_system: Literal["systems/generator"]
    generated_at: datetime
    generator_runtime_version: str = Field(min_length=1)
    assets: list[OperationalAssetItem]

"""Feature Schema Provider defining recipe operations and target leakage guards."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from typing import Any

from systems.generator.app.feature.feature_exception import (
    FeatureSchemaMismatchError,
    FeatureContractError,
)

LEAKAGE_FORBIDDEN_COLUMNS = {
    "target",
    "label",
    "failure",
    "failure_type",
    "failure_occurred_at",
    "degradation_start",
    "degradation_started_at",
    "exclusion",
    "exclusion_start",
    "exclusion_end",
    "maintenance_start",
    "maintenance_started_at",
    "maintenance_end",
    "maintenance_completed_at",
    "is_failure",
    "failed",
}


@dataclass(frozen=True)
class FeatureItem:
    """Individual feature calculation recipe definition."""
    feature_name: str
    source_field: str
    dtype: str = "float64"
    operation: str = "raw"  # raw, rolling_mean, rolling_std, rolling_max, rolling_min, lag, diff, ewm_mean
    parameters: dict[str, Any] = field(default_factory=dict)
    missing_value_policy: str = "drop"


@dataclass
class FeatureSchemaSpec:
    """Declared Feature Schema Specification."""
    schema_version: str
    features: list[FeatureItem]

    @property
    def feature_names(self) -> list[str]:
        return [f.feature_name for f in self.features]

    def compute_checksum(self) -> str:
        """Compute canonical SHA-256 hash of declared features."""
        canonical_list = [
            {
                "feature_name": f.feature_name,
                "source_field": f.source_field,
                "dtype": f.dtype,
                "operation": f.operation,
                "parameters": dict(sorted(f.parameters.items())),
                "missing_value_policy": f.missing_value_policy,
            }
            for f in self.features
        ]
        serialized = json.dumps(
            {"schema_version": self.schema_version, "features": canonical_list},
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class FeatureSchemaProvider:
    """Loads and validates Feature Schema definitions."""

    # Built-in standard industrial recipes
    STANDARD_FEATURE_COLUMNS = [
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
    ]

    def get_feature_schema(
        self,
        schema_version: str,
        available_columns: list[str] | None = None,
        custom_items: list[FeatureItem] | None = None,
    ) -> FeatureSchemaSpec:
        """Resolve feature schema specification and validate against target leakage."""
        if not schema_version or not schema_version.strip():
            raise FeatureContractError("feature_schema_version이 지정되지 않았습니다.")

        if custom_items is not None:
            features = custom_items
        else:
            # Generate or match standard schema items, strictly filtering out ID, timestamp, and target leakage
            cols_to_use = []
            for c in (available_columns or self.STANDARD_FEATURE_COLUMNS):
                c_lower = c.lower()
                if any(forbidden in c_lower for forbidden in LEAKAGE_FORBIDDEN_COLUMNS):
                    continue
                if c_lower in ("udi", "product id", "product_id", "type", "asset_id", "timestamp", "datetime", "date", "time"):
                    continue
                cols_to_use.append(c)

            features = [
                FeatureItem(feature_name=col, source_field=col, operation="raw")
                for col in cols_to_use
            ]

        if not features:
            raise FeatureSchemaMismatchError(f"Feature Schema '{schema_version}'에 정의된 Feature가 없습니다.")

        # Validate leakage and naming
        seen_names = set()
        for item in features:
            if item.feature_name in seen_names:
                raise FeatureSchemaMismatchError(f"중복된 Feature 이름이 선언되었습니다: '{item.feature_name}'")
            seen_names.add(item.feature_name)

            lower_name = item.feature_name.lower()
            if any(forbidden in lower_name for forbidden in LEAKAGE_FORBIDDEN_COLUMNS):
                raise FeatureSchemaMismatchError(
                    f"Target leakage 위험 컬럼은 Feature Schema에 포함될 수 없습니다: '{item.feature_name}'"
                )

        return FeatureSchemaSpec(schema_version=schema_version.strip(), features=features)

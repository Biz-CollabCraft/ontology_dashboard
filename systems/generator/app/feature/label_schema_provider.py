"""Label Schema Provider defining labeling parameters and prediction horizons."""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass

from systems.generator.app.feature.feature_exception import (
    FeatureSchemaMismatchError,
    FeatureContractError,
)


@dataclass
class LabelSchemaSpec:
    """Declared Label Schema Specification."""
    schema_version: str
    prediction_horizon_hours: int
    lead_time_hours: int = 0
    target_column: str = "failure"

    def compute_checksum(self) -> str:
        """Compute canonical SHA-256 hash of label schema configuration."""
        data = {
            "schema_version": self.schema_version,
            "prediction_horizon_hours": self.prediction_horizon_hours,
            "lead_time_hours": self.lead_time_hours,
            "target_column": self.target_column,
        }
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class LabelSchemaProvider:
    """Loads and validates Label Schema definitions."""

    def get_label_schema(
        self,
        schema_version: str,
        requested_horizon_hours: int | None = None,
    ) -> LabelSchemaSpec:
        """Resolve label schema specification and verify horizon alignment."""
        if not schema_version or not schema_version.strip():
            raise FeatureContractError("label_schema_version이 지정되지 않았습니다.")

        # Default standard horizon is 24 hours if not specified in version
        horizon = requested_horizon_hours or 24
        if "h" in schema_version:
            import re
            m = re.search(r"(\d+)h", schema_version)
            if m:
                horizon = int(m.group(1))

        if requested_horizon_hours is not None and requested_horizon_hours != horizon:
            raise FeatureSchemaMismatchError(
                f"요청된 prediction_horizon_hours ({requested_horizon_hours})와 "
                f"Label Schema '{schema_version}'의 설정 ({horizon})이 일치하지 않습니다."
            )

        return LabelSchemaSpec(
            schema_version=schema_version.strip(),
            prediction_horizon_hours=horizon,
            lead_time_hours=0,
            target_column="failure",
        )

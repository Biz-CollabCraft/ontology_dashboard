"""Provider for looking up, registering, and validating Feature Schema allowlists."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional
import pandas as pd
from pydantic import BaseModel, Field

from systems.generator.generator_config import PATHS
from systems.generator.app.feature.feature_exception import FeatureSchemaMismatchError

logger = logging.getLogger(__name__)

FORBIDDEN_LEAKAGE_COLUMNS = {
    "datetime", "observed_at", "machineID", "asset_id", "label",
    "period_start", "anchor", "failure_point", "exclusion_end", "degradation_start",
    "Machine failure", "TWF", "HDF", "PWF", "OSF", "RNF", "UDI", "Product ID"
}


class FeatureSchemaDefinition(BaseModel):
    feature_schema_version: str
    feature_names: list[str]
    description: Optional[str] = None
    target: str = "label"
    prediction_task: str = "binary_failure_within_horizon"

    def compute_checksum(self) -> str:
        canonical = json.dumps(
            {
                "feature_schema_version": self.feature_schema_version,
                "feature_names": self.feature_names,
                "target": self.target,
                "prediction_task": self.prediction_task,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FeatureSchemaProvider:
    """Provides and validates Feature Schemas by version string."""

    def __init__(self, schemas_dir: Optional[Path] = None) -> None:
        self._custom_dir = schemas_dir
        self._registered_schemas: dict[str, FeatureSchemaDefinition] = {}
        self._register_default_schemas()

    @property
    def schemas_dir(self) -> Path:
        if self._custom_dir is not None:
            return self._custom_dir
        return PATHS.models_store / "cache" / "schemas"

    def _register_default_schemas(self) -> None:
        self._registered_schemas["pdm-feature-v1"] = FeatureSchemaDefinition(
            feature_schema_version="pdm-feature-v1",
            feature_names=[
                "voltage__Voltage__rolling_mean__window_5",
                "voltage__Voltage__rolling_std__window_5",
                "rotation__Rotation__rolling_mean__window_5",
                "rotation__Rotation__gradient__default",
            ],
            description="Standard PDM voltage and rotation rolling features v1",
        )
        self._registered_schemas["pdm-feature-v2"] = FeatureSchemaDefinition(
            feature_schema_version="pdm-feature-v2",
            feature_names=[
                "temperature__AirTemperature__rolling_mean__window_5",
                "temperature__AirTemperature__rolling_std__window_5",
                "vibration__Vibration__rolling_mean__window_5",
                "vibration__Vibration__ema__span_10",
                "voltage__Voltage__rolling_mean__window_5",
                "voltage__Voltage__rolling_std__window_5",
            ],
            description="Multi-sensor PDM features v2",
        )
        self._registered_schemas["ai4i-feature-v1"] = FeatureSchemaDefinition(
            feature_schema_version="ai4i-feature-v1",
            feature_names=[
                "Air temperature [K]",
                "Process temperature [K]",
                "Rotational speed [rpm]",
                "Torque [Nm]",
                "Tool wear [min]",
            ],
            description="AI4I 2020 predictive maintenance feature schema v1",
        )

    def register_schema(self, schema: FeatureSchemaDefinition) -> None:
        self._registered_schemas[schema.feature_schema_version] = schema

    def get_schema(self, version: str) -> FeatureSchemaDefinition:
        """Lookup Feature Schema by version from registry or disk."""
        if version in self._registered_schemas:
            return self._registered_schemas[version]

        schema_file = self.schemas_dir / f"{version}.json"
        if schema_file.is_file():
            try:
                with open(schema_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return FeatureSchemaDefinition(**data)
            except Exception as exc:
                raise FeatureSchemaMismatchError(
                    f"Feature Schema 파일 '{schema_file}'을 파싱할 수 없습니다: {exc}"
                ) from exc

        contracts_file = PATHS.models_store.parent / "contracts" / "schemas" / f"{version}.json"
        if contracts_file.is_file():
            try:
                with open(contracts_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return FeatureSchemaDefinition(**data)
            except Exception as exc:
                raise FeatureSchemaMismatchError(
                    f"Contracts Schema 파일 '{contracts_file}'을 파싱할 수 없습니다: {exc}"
                ) from exc

        raise FeatureSchemaMismatchError(
            f"요청한 Feature Schema 버전 '{version}'을 찾을 수 없습니다."
        )

    def validate_and_filter_features(
        self,
        schema_version: str,
        available_df: pd.DataFrame,
        plan: dict[str, Any],
    ) -> tuple[list[str], pd.DataFrame]:
        """Validate feature schema allowlist rules and extract columns in exact schema declaration order."""
        schema = self.get_schema(schema_version)
        declared_names = schema.feature_names

        # 1. Non-empty
        if not declared_names:
            raise FeatureSchemaMismatchError(
                f"Feature Schema '{schema_version}'의 feature_names가 비어 있습니다."
            )

        # 2. No duplicate names
        if len(declared_names) != len(set(declared_names)):
            raise FeatureSchemaMismatchError(
                f"Feature Schema '{schema_version}'에 중복된 Feature 이름이 포함되어 있습니다: {declared_names}"
            )

        # 3. Forbidden leakage check (including dynamic id/time from plan)
        forbidden = set(FORBIDDEN_LEAKAGE_COLUMNS)
        if plan.get("id_column"):
            forbidden.add(plan["id_column"])
        if plan.get("time_column"):
            forbidden.add(plan["time_column"])

        leaked = [f for f in declared_names if f in forbidden]
        if leaked:
            raise FeatureSchemaMismatchError(
                f"Feature Schema '{schema_version}'에 금지된 메타/누수 컬럼이 포함되어 있습니다: {leaked}"
            )

        # 4. Check all declared features exist in available_df
        missing = [f for f in declared_names if f not in available_df.columns]
        if missing:
            raise FeatureSchemaMismatchError(
                f"Feature Schema '{schema_version}'에 선언된 Feature {missing}가 데이터셋에 존재하지 않습니다. "
                f"사용 가능한 컬럼: {list(available_df.columns)}"
            )

        # 5. Check all declared features are numeric
        non_numeric = [f for f in declared_names if not pd.api.types.is_numeric_dtype(available_df[f])]
        if non_numeric:
            raise FeatureSchemaMismatchError(
                f"Feature Schema '{schema_version}'의 Feature {non_numeric}가 수치형(numeric)이 아닙니다."
            )

        # 6. Return exact declared list in declaration order (NO alphabetical sorting!)
        return declared_names, available_df[declared_names]

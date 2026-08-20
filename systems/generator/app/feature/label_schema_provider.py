"""Provider and validator for registered Label Schemas."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

from systems.generator.app.feature.feature_exception import (
    LabelSchemaMismatchError,
)


class LabelSchemaDefinition(BaseModel):
    label_schema_version: str
    prediction_task: Literal["binary_failure_within_horizon"] = "binary_failure_within_horizon"
    target_name: str = "label"
    prediction_horizon_hours: int = 24
    positive_class: int = 1
    anchor_semantic: str = "failure_point"
    exclusion_policy: str = "active_failure_drop"


class LabelSchemaProvider:
    """Manages registered Label Schemas and validates requests against their definitions."""

    def __init__(self, schemas: Optional[dict[str, LabelSchemaDefinition]] = None) -> None:
        self._schemas: dict[str, LabelSchemaDefinition] = schemas or {
            "pdm-label-v1": LabelSchemaDefinition(
                label_schema_version="pdm-label-v1",
                prediction_task="binary_failure_within_horizon",
                target_name="label",
                prediction_horizon_hours=24,
                positive_class=1,
                anchor_semantic="failure_point",
                exclusion_policy="active_failure_drop",
            ),
            "pdm-label-1h": LabelSchemaDefinition(
                label_schema_version="pdm-label-1h",
                prediction_task="binary_failure_within_horizon",
                target_name="label",
                prediction_horizon_hours=1,
                positive_class=1,
                anchor_semantic="failure_point",
                exclusion_policy="active_failure_drop",
            ),
            "ai4i-label-v1": LabelSchemaDefinition(
                label_schema_version="ai4i-label-v1",
                prediction_task="binary_failure_within_horizon",
                target_name="label",
                prediction_horizon_hours=24,
                positive_class=1,
                anchor_semantic="failure_point",
                exclusion_policy="active_failure_drop",
            ),
            "ai4i-label-1h": LabelSchemaDefinition(
                label_schema_version="ai4i-label-1h",
                prediction_task="binary_failure_within_horizon",
                target_name="label",
                prediction_horizon_hours=1,
                positive_class=1,
                anchor_semantic="failure_point",
                exclusion_policy="active_failure_drop",
            ),
        }

    def register_schema(self, schema: LabelSchemaDefinition) -> None:
        self._schemas[schema.label_schema_version] = schema

    def get_schema(self, schema_version: str) -> Optional[LabelSchemaDefinition]:
        return self._schemas.get(schema_version)

    def validate_label_schema(
        self,
        schema_version: str,
        requested_horizon_hours: int,
    ) -> LabelSchemaDefinition:
        """Validate that requested label schema exists and strictly adheres to domain contracts."""
        schema = self.get_schema(schema_version)
        if not schema:
            raise LabelSchemaMismatchError(
                f"등록되지 않은 Label Schema 버전입니다: '{schema_version}'.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.label_schema_version != schema_version:
            raise LabelSchemaMismatchError(
                f"Label Schema 내부 버전('{schema.label_schema_version}')이 요청 버전('{schema_version}')과 일치하지 않습니다.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.prediction_task != "binary_failure_within_horizon":
            raise LabelSchemaMismatchError(
                f"Label Schema의 prediction_task가 'binary_failure_within_horizon'이 아닙니다: '{schema.prediction_task}'.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.target_name != "label":
            raise LabelSchemaMismatchError(
                f"Label Schema의 target_name이 'label'이 아닙니다: '{schema.target_name}'.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.positive_class != 1:
            raise LabelSchemaMismatchError(
                f"Label Schema의 positive_class가 1이 아닙니다: {schema.positive_class}.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.prediction_horizon_hours != requested_horizon_hours:
            raise LabelSchemaMismatchError(
                f"요청된 prediction_horizon_hours({requested_horizon_hours})가 Label Schema의 horizon({schema.prediction_horizon_hours})과 일치하지 않습니다.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.anchor_semantic != "failure_point":
            raise LabelSchemaMismatchError(
                f"Label Schema의 anchor_semantic이 'failure_point'가 아닙니다: '{schema.anchor_semantic}'.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        if schema.exclusion_policy != "active_failure_drop":
            raise LabelSchemaMismatchError(
                f"Label Schema의 exclusion_policy가 'active_failure_drop'이 아닙니다: '{schema.exclusion_policy}'.",
                code="LABEL_SCHEMA_MISMATCH",
            )

        return schema

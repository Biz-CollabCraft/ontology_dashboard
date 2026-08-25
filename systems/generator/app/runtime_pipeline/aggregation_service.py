"""Service for aggregating multi-model prediction results and determining anomaly verdict."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ModelPredictionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class AggregationVerdict:
    anomaly_detected: Optional[bool]
    overall_status: Literal["succeeded", "partially_succeeded", "failed"]
    anomaly_models: list[str]
    succeeded_models: list[str]
    failed_models: list[str]


class AggregationService:
    """Aggregates model results according to Section 12 multi-model judgment policy."""

    def aggregate(self, results: list[ModelPredictionResult]) -> AggregationVerdict:
        """Evaluate multi-model predictions and return combined anomaly verdict."""
        if not results:
            return AggregationVerdict(
                anomaly_detected=None,
                overall_status="failed",
                anomaly_models=[],
                succeeded_models=[],
                failed_models=[],
            )

        anomaly_models = [r.model_id for r in results if r.status == "succeeded" and r.is_anomaly is True]
        succeeded_models = [r.model_id for r in results if r.status == "succeeded"]
        failed_models = [r.model_id for r in results if r.status != "succeeded"]

        # Policy 1: At least one anomaly detected
        if anomaly_models:
            overall_status: Literal["succeeded", "partially_succeeded", "failed"] = (
                "partially_succeeded" if failed_models else "succeeded"
            )
            return AggregationVerdict(
                anomaly_detected=True,
                overall_status=overall_status,
                anomaly_models=anomaly_models,
                succeeded_models=succeeded_models,
                failed_models=failed_models,
            )

        # Policy 2: No anomalies, but some models failed or are unknown -> Prohibit normal verdict!
        if failed_models:
            return AggregationVerdict(
                anomaly_detected=None,
                overall_status="partially_succeeded" if succeeded_models else "failed",
                anomaly_models=[],
                succeeded_models=succeeded_models,
                failed_models=failed_models,
            )

        # Policy 3: All models succeeded and all are normal
        return AggregationVerdict(
            anomaly_detected=False,
            overall_status="succeeded",
            anomaly_models=[],
            succeeded_models=succeeded_models,
            failed_models=[],
        )

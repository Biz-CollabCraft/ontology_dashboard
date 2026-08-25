"""Service for aggregating multi-model prediction results per equipment and determining anomaly verdict."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal, Optional

from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ModelPredictionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EquipmentAggregationVerdict:
    """Verdict for a single equipment across all evaluated models."""
    asset_id: str
    anomaly_detected: Optional[bool]
    status: Literal["succeeded", "partially_succeeded", "failed", "unknown"]
    anomaly_models: list[str]
    succeeded_models: list[str]
    failed_models: list[str]
    model_results: list[ModelPredictionResult]


@dataclass
class AggregationVerdict:
    """Overall aggregation verdict summarizing all equipments."""
    anomaly_detected: Optional[bool]
    overall_status: Literal["succeeded", "partially_succeeded", "failed"]
    equipment_verdicts: dict[str, EquipmentAggregationVerdict]
    anomalous_assets: list[str] = field(default_factory=list)

    @property
    def anomaly_models(self) -> list[str]:
        """Flattened list of all anomalous model IDs across all equipments."""
        models: set[str] = set()
        for ev in self.equipment_verdicts.values():
            models.update(ev.anomaly_models)
        return sorted(models)


class AggregationService:
    """Aggregates model results per equipment according to multi-model judgment policy."""

    def aggregate(self, results: list[ModelPredictionResult]) -> AggregationVerdict:
        """Evaluate multi-model predictions per equipment and return combined verdict."""
        if not results:
            return AggregationVerdict(
                anomaly_detected=None,
                overall_status="failed",
                equipment_verdicts={},
                anomalous_assets=[],
            )

        # Group results by asset_id
        grouped: dict[str, list[ModelPredictionResult]] = {}
        for r in results:
            grouped.setdefault(r.asset_id, []).append(r)

        equipment_verdicts: dict[str, EquipmentAggregationVerdict] = {}
        anomalous_assets: list[str] = []
        any_success = False
        any_failure = False

        for asset_id, asset_results in grouped.items():
            anomaly_models = [r.model_id for r in asset_results if r.status == "succeeded" and r.is_anomaly is True]
            succeeded_models = [r.model_id for r in asset_results if r.status == "succeeded"]
            failed_models = [r.model_id for r in asset_results if r.status != "succeeded"]

            if anomaly_models:
                ev_status: Literal["succeeded", "partially_succeeded", "failed", "unknown"] = (
                    "partially_succeeded" if failed_models else "succeeded"
                )
                eq_verdict = EquipmentAggregationVerdict(
                    asset_id=asset_id,
                    anomaly_detected=True,
                    status=ev_status,
                    anomaly_models=anomaly_models,
                    succeeded_models=succeeded_models,
                    failed_models=failed_models,
                    model_results=asset_results,
                )
                anomalous_assets.append(asset_id)
                any_success = True
                if failed_models:
                    any_failure = True
            elif failed_models:
                # No anomalies, but some models failed or unknown -> prohibit normal verdict!
                ev_status = "partially_succeeded" if succeeded_models else "failed"
                eq_verdict = EquipmentAggregationVerdict(
                    asset_id=asset_id,
                    anomaly_detected=None,
                    status=ev_status,
                    anomaly_models=[],
                    succeeded_models=succeeded_models,
                    failed_models=failed_models,
                    model_results=asset_results,
                )
                if succeeded_models:
                    any_success = True
                any_failure = True
            else:
                # All models succeeded and all are normal
                eq_verdict = EquipmentAggregationVerdict(
                    asset_id=asset_id,
                    anomaly_detected=False,
                    status="succeeded",
                    anomaly_models=[],
                    succeeded_models=succeeded_models,
                    failed_models=[],
                    model_results=asset_results,
                )
                any_success = True

            equipment_verdicts[asset_id] = eq_verdict

        # Overall status calculation
        if not any_success:
            overall_status: Literal["succeeded", "partially_succeeded", "failed"] = "failed"
        elif any_failure:
            overall_status = "partially_succeeded"
        else:
            overall_status = "succeeded"

        # Overall anomaly_detected calculation
        overall_anomaly = True if anomalous_assets else (False if not any_failure else None)

        return AggregationVerdict(
            anomaly_detected=overall_anomaly,
            overall_status=overall_status,
            equipment_verdicts=equipment_verdicts,
            anomalous_assets=anomalous_assets,
        )

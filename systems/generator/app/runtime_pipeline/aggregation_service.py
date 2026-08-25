"""Service and builder for grouping multi-model prediction results per equipment into batches."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ModelPredictionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EquipmentModelBatch:
    """Collected model execution results for a single equipment without threshold verdict."""
    asset_id: str
    status: Literal["succeeded", "partially_succeeded", "failed", "unknown"]
    succeeded_models: list[str]
    failed_models: list[str]
    model_results: list[ModelPredictionResult]


@dataclass
class PredictionBatchSummary:
    """Summary of collected prediction results across all equipments."""
    overall_status: Literal["succeeded", "partially_succeeded", "failed"]
    equipment_batches: dict[str, EquipmentModelBatch]
    total_equipments: int
    succeeded_equipments: list[str] = field(default_factory=list)
    partially_succeeded_equipments: list[str] = field(default_factory=list)
    failed_equipments: list[str] = field(default_factory=list)


# Alias for backward compatibility if referenced
EquipmentAggregationVerdict = EquipmentModelBatch
AggregationVerdict = PredictionBatchSummary


class ModelResultCollector:
    """Collects and organizes model execution results per equipment for downstream delivery."""

    def collect(self, results: list[ModelPredictionResult]) -> PredictionBatchSummary:
        """Group model results by asset_id and assess per-equipment execution status."""
        if not results:
            return PredictionBatchSummary(
                overall_status="failed",
                equipment_batches={},
                total_equipments=0,
                succeeded_equipments=[],
                partially_succeeded_equipments=[],
                failed_equipments=[],
            )

        # Group results by asset_id
        grouped: dict[str, list[ModelPredictionResult]] = {}
        for r in results:
            grouped.setdefault(r.asset_id, []).append(r)

        equipment_batches: dict[str, EquipmentModelBatch] = {}
        succeeded_equipments: list[str] = []
        partially_succeeded_equipments: list[str] = []
        failed_equipments: list[str] = []

        any_success = False
        any_failure = False

        for asset_id, asset_results in grouped.items():
            succeeded_models = [r.model_id for r in asset_results if r.status == "succeeded"]
            failed_models = [r.model_id for r in asset_results if r.status != "succeeded"]

            if succeeded_models and not failed_models:
                batch_status: Literal["succeeded", "partially_succeeded", "failed", "unknown"] = "succeeded"
                succeeded_equipments.append(asset_id)
                any_success = True
            elif succeeded_models and failed_models:
                batch_status = "partially_succeeded"
                partially_succeeded_equipments.append(asset_id)
                any_success = True
                any_failure = True
            else:
                batch_status = "failed"
                failed_equipments.append(asset_id)
                any_failure = True

            equipment_batches[asset_id] = EquipmentModelBatch(
                asset_id=asset_id,
                status=batch_status,
                succeeded_models=succeeded_models,
                failed_models=failed_models,
                model_results=asset_results,
            )

        if not any_success:
            overall_status: Literal["succeeded", "partially_succeeded", "failed"] = "failed"
        elif any_failure:
            overall_status = "partially_succeeded"
        else:
            overall_status = "succeeded"

        return PredictionBatchSummary(
            overall_status=overall_status,
            equipment_batches=equipment_batches,
            total_equipments=len(grouped),
            succeeded_equipments=succeeded_equipments,
            partially_succeeded_equipments=partially_succeeded_equipments,
            failed_equipments=failed_equipments,
        )


# Backward-compatible alias
class AggregationService(ModelResultCollector):
    def aggregate(self, results: list[ModelPredictionResult]) -> PredictionBatchSummary:
        return self.collect(results)

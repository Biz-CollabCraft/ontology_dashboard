"""Service for organizing multi-model prediction results per equipment into batches with observation alignment verification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelinePredictionObservationAlignmentNotImplementedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    InternalModelPredictionResult,
    ModelPredictionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class EquipmentModelBatch:
    """Collected model execution results for a single equipment formatted for delivery."""
    asset_id: str
    status: Literal["succeeded", "partially_succeeded", "failed", "unknown"]
    observed_at: str
    succeeded_models: list[str]
    failed_models: list[str]
    model_results: dict[str, ModelPredictionResult]


@dataclass
class PredictionBatchSummary:
    """Summary of collected prediction results across all equipments."""
    overall_status: Literal["succeeded", "partially_succeeded", "failed"]
    equipment_batches: dict[str, EquipmentModelBatch]
    total_equipments: int
    succeeded_equipments: list[str] = field(default_factory=list)
    partially_succeeded_equipments: list[str] = field(default_factory=list)
    failed_equipments: list[str] = field(default_factory=list)


class PredictionBatchService:
    """Organizes model execution results per equipment and validates observation timestamp alignment."""

    def collect(self, results: list[InternalModelPredictionResult]) -> PredictionBatchSummary:
        """Group model results by asset_id, verify observation alignment, and construct model_results dictionary."""
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
        grouped: dict[str, list[InternalModelPredictionResult]] = {}
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

            # Observation timestamp alignment check for succeeded models
            observed_times = {
                r.observed_at
                for r in asset_results
                if r.status == "succeeded" and r.observed_at
            }
            if len(observed_times) > 1:
                raise PipelinePredictionObservationAlignmentNotImplementedError(
                    f"동일 설비 '{asset_id}'에 대한 모델별 예측 대상 관측 시각(observed_at)이 불일치합니다: {sorted(observed_times)}",
                    details=[{
                        "asset_id": asset_id,
                        "observed_times": sorted(observed_times),
                        "model_observed_times": {r.model_id: r.observed_at for r in asset_results},
                    }],
                    retryable=False,
                )

            if observed_times:
                batch_observed_at = next(iter(observed_times))
            else:
                batch_observed_at = next((r.observed_at for r in asset_results if r.observed_at), "")

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

            # Construct K-V dictionary: model_id -> ModelPredictionResult
            model_results_dict: dict[str, ModelPredictionResult] = {}
            for r in asset_results:
                model_results_dict[r.model_id] = r.to_payload_result()

            equipment_batches[asset_id] = EquipmentModelBatch(
                asset_id=asset_id,
                status=batch_status,
                observed_at=batch_observed_at,
                succeeded_models=succeeded_models,
                failed_models=failed_models,
                model_results=model_results_dict,
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


ModelResultCollector = PredictionBatchService

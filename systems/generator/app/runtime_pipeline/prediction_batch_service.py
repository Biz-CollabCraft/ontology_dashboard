"""Service for organizing multi-model prediction results per equipment into batches with observation alignment verification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelinePredictionObservationAlignmentNotImplementedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    InternalModelPredictionResult,
    ModelPredictionResult,
    PredictionResultBatchItem,
    PredictionResultBatchLineage,
    PredictionResultBatchProducer,
    PredictionResultBatchSourceRef,
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


def _batch_item_status(result: ModelPredictionResult) -> str:
    if result.status == "succeeded":
        return "predicted"
    if result.error_code == "PIPELINE_HISTORY_INSUFFICIENT" or result.status == "unknown":
        return "history_insufficient"
    if result.error_code and "MODEL_ARTIFACT" in result.error_code:
        return "failed_model_artifact"
    if result.error_code and "FEATURE" in result.error_code:
        return "failed_feature_execution"
    return "failed_model_inference"


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

    def build_payload(
        self,
        *,
        run_id: str,
        job_id: str,
        asset_id: str,
        batch: EquipmentModelBatch,
        source_lineage: Any,
        runtime_version: str,
    ):
        """Build the canonical #129 Prediction Result Batch handoff payload."""
        import hashlib
        import json
        from systems.generator.app.runtime_pipeline.pipeline_schema import (
            PredictionResultBatchPayload,
        )

        source_ref = PredictionResultBatchSourceRef(
            uri=source_lineage.source_uri,
            sha256=source_lineage.source_checksum,
        )
        lineage = PredictionResultBatchLineage(
            simulation_session_id=None,
            overlay_branch_id=None,
            history_segment_id=None,
            maintenance_event_id=None,
            maintenance_action_id=None,
            state_version=None,
        )
        items: list[PredictionResultBatchItem] = []
        for model_id, model_result in batch.model_results.items():
            status = _batch_item_status(model_result)
            item_seed = {
                "asset_id": asset_id,
                "observed_at": batch.observed_at,
                "source_kind": "live_sensor",
                "source_ref": source_ref.model_dump(mode="json"),
                "output_status": status,
                "score": model_result.score if status == "predicted" else None,
                "model_id": model_id,
                "model_version": model_result.model_version,
                "model_artifact_manifest_sha256": model_result.manifest_checksum
                or (model_result.artifact_ref.sha256 if model_result.artifact_ref else None),
                "feature_schema_version": model_result.feature_schema_version or "unknown",
                "history_requirement_version": model_result.history_requirement_version or "unknown",
                "feature_schema_sha256": model_result.feature_ref.sha256 if model_result.feature_ref else None,
                "history_requirement_sha256": None,
                "lineage": lineage.model_dump(mode="json"),
                "failure_reason": None if status == "predicted" else (model_result.error_message or model_result.error_code or "prediction unavailable"),
            }
            canonical_json = json.dumps(item_seed, sort_keys=True, separators=(",", ":"))
            payload_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            event_id = f"evt-{hashlib.sha256((run_id + ':' + model_id + ':' + payload_sha256).encode('utf-8')).hexdigest()[:32]}"
            items.append(
                PredictionResultBatchItem(
                    event_id=event_id,
                    payload_sha256=payload_sha256,
                    **item_seed,
                )
            )

        return PredictionResultBatchPayload(
            batch_id=f"{run_id}:{job_id}:{asset_id}",
            producer=PredictionResultBatchProducer(
                runtime_version=runtime_version,
                outbox_id=None,
            ),
            results=items,
        )

    def stage_batches(
        self,
        run_id: str,
        job_id: str,
        summary: PredictionBatchSummary,
        dataset_id: str,
        dataset_version: str,
        pipeline_contract_version: str,
        source_lineage: Any,
        model_set_id: str,
        model_set_version: str,
        sensor_data_ref: Optional[dict[str, Any]] = None,
        base_dir: Optional[Path] = None,
    ) -> ArtifactReference:
        """Stage equipment prediction batches and write batch-manifest.json in run-dedicated directory."""
        import hashlib
        import json
        from pathlib import Path
        from systems.generator.generator_config import PATHS
        from systems.generator.app.runtime_pipeline.pipeline_exception import (
            PipelineModelSetSnapshotMismatchError,
        )
        from systems.generator.app.runtime_pipeline.pipeline_schema import (
            ArtifactReference,
            PredictionResultBatchPayload,
        )
        from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
            PredictionDeliveryService,
        )

        root = base_dir or PATHS.data_preprocessed
        staging_dir = root / "pipeline_datasets" / run_id / "batch_staging"
        staging_dir.mkdir(parents=True, exist_ok=True)

        batch_manifest_entries: dict[str, dict[str, Any]] = {}
        for asset_id, batch in summary.equipment_batches.items():
            for m_key, m_res in batch.model_results.items():
                if m_res.model_set_id and m_res.model_set_id != model_set_id:
                    raise PipelineModelSetSnapshotMismatchError(
                        f"Model result '{m_key}'의 model_set_id('{m_res.model_set_id}')가 Batch의 model_set_id('{model_set_id}')와 불일치합니다.",
                        retryable=False,
                    )
                if m_res.model_set_version and m_res.model_set_version != model_set_version:
                    raise PipelineModelSetSnapshotMismatchError(
                        f"Model result '{m_key}'의 model_set_version('{m_res.model_set_version}')가 Batch의 model_set_version('{model_set_version}')와 불일치합니다.",
                        retryable=False,
                    )

            temp_payload = self.build_payload(
                run_id=run_id,
                job_id=job_id,
                asset_id=asset_id,
                batch=batch,
                source_lineage=source_lineage,
                runtime_version="generator-runtime-prediction-v1",
            )
            event_id, payload_sha256 = PredictionDeliveryService.compute_canonical_payload_sha256(temp_payload)
            temp_payload.producer.outbox_id = event_id

            asset_file = staging_dir / f"{asset_id}.json"
            content_bytes = temp_payload.model_dump_json(indent=2).encode("utf-8")
            with open(asset_file, "wb") as f:
                f.write(content_bytes)

            batch_manifest_entries[asset_id] = {
                "path": f"{asset_id}.json",
                "sha256": payload_sha256,
                "event_id": event_id,
            }

        manifest_data = {
            "run_id": run_id,
            "job_id": job_id,
            "contract_version": pipeline_contract_version,
            "source_checksum": source_lineage.source_checksum if hasattr(source_lineage, "source_checksum") else "",
            "batches": batch_manifest_entries,
        }
        manifest_bytes = json.dumps(manifest_data, indent=2, sort_keys=True).encode("utf-8")
        manifest_file = staging_dir / "batch-manifest.json"
        with open(manifest_file, "wb") as f:
            f.write(manifest_bytes)

        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        rel_uri = f"data_preprocessed/pipeline_datasets/{run_id}/batch_staging/batch-manifest.json"
        return ArtifactReference(
            uri=rel_uri,
            sha256=manifest_sha256,
            role="batch_manifest",
            size_bytes=len(manifest_bytes),
        )

    def load_staged_batches(
        self,
        manifest_ref: ArtifactReference,
        base_dir: Optional[Path] = None,
    ) -> dict[str, Any]:
        """Load and verify staged equipment prediction result batches from batch-manifest.json."""
        import hashlib
        import json
        from pathlib import Path
        from systems.generator.generator_config import PATHS, PROJECT_ROOT
        from systems.generator.app.runtime_pipeline.pipeline_exception import (
            PipelineCheckpointChecksumMismatchError,
            PipelineCheckpointOutputMissingError,
        )
        from systems.generator.app.runtime_pipeline.pipeline_schema import (
            PredictionResultBatchPayload,
        )
        from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
            PredictionDeliveryService,
        )

        uri_str = manifest_ref.uri.replace("\\", "/")
        rel_path = uri_str[len("data_preprocessed/"):] if uri_str.startswith("data_preprocessed/") else uri_str
        if rel_path.startswith("data/preprocessed/"):
            rel_path = rel_path[len("data/preprocessed/"):]

        candidates = [
            Path(manifest_ref.uri),
            (base_dir or PATHS.data_preprocessed) / rel_path,
            (base_dir or PATHS.data_preprocessed).parent / uri_str,
            PROJECT_ROOT / uri_str,
        ]
        manifest_path = None
        for cand in candidates:
            if cand.is_file():
                manifest_path = cand
                break

        if not manifest_path:
            raise PipelineCheckpointOutputMissingError(
                f"Staged batch manifest file not found at '{manifest_ref.uri}'",
                details=[{"uri": manifest_ref.uri}],
            )

        with open(manifest_path, "rb") as f:
            m_bytes = f.read()
        if hashlib.sha256(m_bytes).hexdigest() != manifest_ref.sha256:
            raise PipelineCheckpointChecksumMismatchError(
                f"Batch manifest checksum mismatch for '{manifest_ref.uri}'",
                details=[{"uri": manifest_ref.uri}],
            )

        manifest_data = json.loads(m_bytes.decode("utf-8"))
        batches_dir = manifest_path.parent
        staged_payloads: dict[str, PredictionResultBatchPayload] = {}

        for asset_id, entry in manifest_data.get("batches", {}).items():
            asset_file = batches_dir / entry["path"]
            if not asset_file.is_file():
                raise PipelineCheckpointOutputMissingError(
                    f"Staged batch file missing for equipment '{asset_id}' at '{asset_file}'",
                    details=[{"asset_id": asset_id, "path": str(asset_file)}],
                )
            with open(asset_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            payload = PredictionResultBatchPayload.model_validate(data)
            event_id, payload_sha256 = PredictionDeliveryService.compute_canonical_payload_sha256(payload)
            if payload_sha256 != entry["sha256"]:
                raise PipelineCheckpointChecksumMismatchError(
                    f"Staged batch payload checksum mismatch for asset '{asset_id}'",
                    details=[{"asset_id": asset_id, "expected": entry["sha256"], "actual": payload_sha256}],
                )
            staged_payloads[asset_id] = payload

        return staged_payloads


ModelResultCollector = PredictionBatchService

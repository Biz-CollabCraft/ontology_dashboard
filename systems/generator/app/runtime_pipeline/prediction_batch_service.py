"""Service for organizing multi-model prediction results per equipment into batches with observation alignment verification."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from datetime import datetime, timezone
import hashlib

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    ModelSetContractInvalidError,
    PipelinePredictionObservationAlignmentNotImplementedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    InternalModelPredictionResult,
    ModelPredictionResult,
    PredictionResultBatchPayload,
    PredictionResultItem,
    PredictionResultLineage,
    PredictionResultProducer,
    PredictionResultSourceRef,
    compute_prediction_result_item_sha256,
)

logger = logging.getLogger(__name__)


def to_external_result_item(
    internal: InternalModelPredictionResult,
    *,
    source_kind: str = "live_sensor",
    source_ref: Optional[PredictionResultSourceRef] = None,
    lineage: Optional[PredictionResultLineage] = None,
) -> PredictionResultItem:
    """Convert an InternalModelPredictionResult into an official external PredictionResultItem."""
    # 1. Strict observed_at validation (fail-closed, no fallback to datetime.now())
    if not internal.observed_at:
        raise ModelSetContractInvalidError(
            f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' is missing required observed_at.",
            details=[{"asset_id": internal.asset_id, "model_id": internal.model_id}],
            retryable=False,
        )

    if isinstance(internal.observed_at, datetime):
        obs_dt = internal.observed_at
        if obs_dt.tzinfo is None:
            obs_dt = obs_dt.replace(tzinfo=timezone.utc)
    else:
        s = str(internal.observed_at).strip()
        if not s:
            raise ModelSetContractInvalidError(
                f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' has blank observed_at.",
                details=[{"asset_id": internal.asset_id, "model_id": internal.model_id}],
                retryable=False,
            )
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            obs_dt = datetime.fromisoformat(s)
            if obs_dt.tzinfo is None:
                obs_dt = obs_dt.replace(tzinfo=timezone.utc)
        except Exception as exc:
            raise ModelSetContractInvalidError(
                f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' has invalid observed_at ISO timestamp format '{internal.observed_at}': {exc}",
                details=[{"asset_id": internal.asset_id, "model_id": internal.model_id, "observed_at": str(internal.observed_at)}],
                retryable=False,
            ) from exc

    # 2. Strict source_ref validation (fail-closed, no fallback to dummy uri or zero checksum)
    if source_ref is None:
        raise ModelSetContractInvalidError(
            f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' is missing required source_ref.",
            details=[{"asset_id": internal.asset_id, "model_id": internal.model_id}],
            retryable=False,
        )

    if not source_ref.uri or not str(source_ref.uri).strip():
        raise ModelSetContractInvalidError(
            f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' has empty source_ref.uri.",
            details=[{"asset_id": internal.asset_id, "model_id": internal.model_id}],
            retryable=False,
        )

    clean_sha256 = (source_ref.sha256 or "").strip().lower()
    if not clean_sha256 or len(clean_sha256) != 64 or clean_sha256 == "0" * 64 or any(c not in "0123456789abcdef" for c in clean_sha256):
        raise ModelSetContractInvalidError(
            f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' has invalid or zero source_ref.sha256 '{source_ref.sha256}'.",
            details=[{"asset_id": internal.asset_id, "model_id": internal.model_id, "sha256": str(source_ref.sha256)}],
            retryable=False,
        )

    if lineage is None:
        lineage = PredictionResultLineage()

    if internal.status == "succeeded":
        output_status = "predicted"
        score_val = internal.score
        failure_reason_val = None
    elif internal.status == "unknown":
        output_status = "history_insufficient"
        score_val = None
        failure_reason_val = internal.error_message or "History requirement insufficient"
    else:
        err_code = (internal.error_code or "").upper()
        if "ARTIFACT" in err_code:
            output_status = "failed_model_artifact"
        elif "FEATURE" in err_code:
            output_status = "failed_feature_execution"
        else:
            output_status = "failed_model_inference"
        score_val = None
        failure_reason_val = internal.error_message or "Model execution failed"

    item_key = f"{internal.asset_id}:{internal.model_id}:{obs_dt.isoformat()}"
    event_id = f"evt-{hashlib.sha256(item_key.encode('utf-8')).hexdigest()[:32]}"

    model_artifact_sha256 = (
        internal.manifest_checksum
        or (internal.artifact_ref.sha256 if internal.artifact_ref else None)
    )
    if not model_artifact_sha256 or model_artifact_sha256 == "0" * 64:
        if output_status == "predicted":
            raise ModelSetContractInvalidError(
                f"Prediction result for asset '{internal.asset_id}', model '{internal.model_id}' has invalid or missing model_artifact_sha256.",
                details=[{"asset_id": internal.asset_id, "model_id": internal.model_id}],
                retryable=False,
            )
        else:
            model_artifact_sha256 = "0" * 64

    item_dict = {
        "event_id": event_id,
        "asset_id": internal.asset_id,
        "observed_at": obs_dt,
        "source_kind": source_kind,
        "source_ref": source_ref.model_dump(mode="json"),
        "output_status": output_status,
        "score": score_val,
        "model_id": internal.model_id,
        "model_version": internal.model_version,
        "model_artifact_sha256": model_artifact_sha256,
        "feature_schema_version": internal.feature_schema_version or "v1.0.0",
        "history_requirement_version": internal.history_requirement_version or "v1.0.0",
        "feature_schema_sha256": None,
        "history_requirement_sha256": None,
        "lineage": lineage.model_dump(mode="json"),
        "failure_reason": failure_reason_val,
    }

    item_payload_sha256 = compute_prediction_result_item_sha256(item_dict)

    return PredictionResultItem(
        event_id=event_id,
        asset_id=internal.asset_id,
        observed_at=obs_dt,
        source_kind=source_kind,
        source_ref=source_ref,
        payload_sha256=item_payload_sha256,
        output_status=output_status,
        score=score_val,
        model_id=internal.model_id,
        model_version=internal.model_version,
        model_artifact_sha256=model_artifact_sha256,
        feature_schema_version=internal.feature_schema_version or "v1.0.0",
        history_requirement_version=internal.history_requirement_version or "v1.0.0",
        feature_schema_sha256=None,
        history_requirement_sha256=None,
        lineage=lineage,
        failure_reason=failure_reason_val,
    )


def validate_external_results_array(items: list[PredictionResultItem]) -> None:
    """Validate external results array against composite key duplication, event_id duplication, and non-empty rules."""
    if not items:
        raise ModelSetContractInvalidError(
            "Prediction Result Batch의 results 배열이 비어 있습니다.",
            retryable=False,
        )

    seen_composite_keys: set[tuple[str, str, str]] = set()
    seen_event_ids: set[str] = set()

    for item in items:
        if item.event_id in seen_event_ids:
            raise ModelSetContractInvalidError(
                f"Prediction Result Batch 안에서 중복된 event_id '{item.event_id}'가 감지되었습니다.",
                details=[{"event_id": item.event_id}],
                retryable=False,
            )
        seen_event_ids.add(item.event_id)

        obs_str = item.observed_at.isoformat() if isinstance(item.observed_at, datetime) else str(item.observed_at)
        composite_key = (item.asset_id, item.model_id, obs_str)
        if composite_key in seen_composite_keys:
            raise ModelSetContractInvalidError(
                f"Prediction Result Batch 안에서 중복된 복합키 (asset_id='{item.asset_id}', model_id='{item.model_id}', observed_at='{obs_str}')가 감지되었습니다.",
                details=[{"asset_id": item.asset_id, "model_id": item.model_id, "observed_at": obs_str}],
                retryable=False,
            )
        seen_composite_keys.add(composite_key)


@dataclass
class EquipmentModelBatch:
    """Collected model execution results for a single equipment formatted for delivery."""
    asset_id: str
    status: Literal["succeeded", "partially_succeeded", "failed", "unknown"]
    observed_at: str
    succeeded_models: list[str]
    failed_models: list[str]
    model_results: dict[str, ModelPredictionResult]
    internal_results: list[InternalModelPredictionResult] = field(default_factory=list)


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
                internal_results=asset_results,
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

            # Convert internal results to external PredictionResultItem list
            items: list[PredictionResultItem] = []
            s_uri = source_lineage.source_uri if hasattr(source_lineage, "source_uri") and source_lineage.source_uri else "data/incoming/protocol.jsonl"
            s_checksum = source_lineage.source_checksum if hasattr(source_lineage, "source_checksum") and source_lineage.source_checksum else "0" * 64
            src_ref = PredictionResultSourceRef(uri=s_uri, sha256=s_checksum)
            lineage_obj = PredictionResultLineage()

            if batch.internal_results:
                for internal_r in batch.internal_results:
                    items.append(to_external_result_item(internal_r, source_kind="live_sensor", source_ref=src_ref, lineage=lineage_obj))
            else:
                for m_id, m_res in batch.model_results.items():
                    internal_r = InternalModelPredictionResult(
                        asset_id=asset_id,
                        model_id=m_id,
                        model_version=m_res.model_version,
                        status=m_res.status,
                        observed_at=m_res.observed_at,
                        score_type=m_res.score_type,
                        score_source=m_res.score_source,
                        score=m_res.score,
                        artifact_ref=m_res.artifact_ref,
                        feature_ref=m_res.feature_ref,
                        manifest_checksum=m_res.manifest_checksum,
                        feature_schema_version=m_res.feature_schema_version,
                        label_schema_version=m_res.label_schema_version,
                        history_requirement_version=m_res.history_requirement_version,
                        model_set_id=m_res.model_set_id or model_set_id,
                        model_set_version=m_res.model_set_version or model_set_version,
                        error_code=m_res.error_code,
                        error_message=m_res.error_message,
                    )
                    items.append(to_external_result_item(internal_r, source_kind="live_sensor", source_ref=src_ref, lineage=lineage_obj))

            validate_external_results_array(items)

            now_dt = datetime.now(timezone.utc)
            batch_key = f"{run_id}:{asset_id}:{now_dt.isoformat()}"
            batch_id = f"batch-{hashlib.sha256(batch_key.encode('utf-8')).hexdigest()[:24]}"

            producer = PredictionResultProducer(
                system="systems.generator",
                runtime_version="1.0.0",
                outbox_id=None,
            )

            external_payload = PredictionResultBatchPayload(
                contract_version="prediction-result-batch-v1",
                batch_id=batch_id,
                producer=producer,
                emitted_at=now_dt,
                results=items,
            )

            event_id, payload_sha256 = PredictionDeliveryService.compute_canonical_payload_sha256(external_payload)

            asset_file = staging_dir / f"{asset_id}.json"
            content_bytes = external_payload.model_dump_json(indent=2).encode("utf-8")
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
            validate_external_results_array(payload.results)
            event_id, payload_sha256 = PredictionDeliveryService.compute_canonical_payload_sha256(payload)
            if payload_sha256 != entry["sha256"]:
                raise PipelineCheckpointChecksumMismatchError(
                    f"Staged batch payload checksum mismatch for asset '{asset_id}'",
                    details=[{"asset_id": asset_id, "expected": entry["sha256"], "actual": payload_sha256}],
                )
            staged_payloads[asset_id] = payload

        return staged_payloads


ModelResultCollector = PredictionBatchService

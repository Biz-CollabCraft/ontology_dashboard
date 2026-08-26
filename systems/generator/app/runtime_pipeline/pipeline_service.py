"""Pipeline orchestration service executing Preprocessing, Runtime Feature, Prediction, Batch Building, and Delivery."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from systems.generator.generator_config import (
    PROJECT_ROOT,
    PATHS,
    validate_pipeline_source_uri,
)
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_repository import (
    compute_source_schema_fingerprint,
)
from systems.generator.app.preprocessing.preprocessing_service import PreprocessingService
from systems.generator.app.runtime_pipeline.prediction_batch_service import (
    PredictionBatchService,
    PredictionBatchSummary,
)
from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
    PredictionDeliveryService,
)
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineAssetIdColumnMissingError,
    PipelineAssetIdMissingError,
    PipelineAssetIdValueMissingError,
    PipelineCheckpointChecksumMismatchError,
    PipelineCheckpointIncompatibleError,
    PipelineCheckpointInvalidError,
    PipelineCheckpointOutputMissingError,
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineIntermediateCleanupFailedError,
    PipelineMappingNotImplementedError,
    PipelineModelPredictionFailedError,
    PipelineNoActiveModelError,
    PipelinePredictionObservationAlignmentNotImplementedError,
    PipelinePreprocessingFailedError,
    PipelineResumeFailedError,
    PipelineResumeNotAllowedError,
    PipelineRuntimeFeatureFailedError,
    PipelineSourceChecksumChangedError,
    PipelineSourceFileNotStableError,
    PipelineTimestampInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_repository import (
    PipelineRepository,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    InternalModelPredictionResult,
    PipelineCheckpoint,
    PipelineQueueItem,
    PipelineRunState,
    PredictionDeliveryEventState,
    PredictionResultBatchPayload,
    SourceLineage,
    compute_source_identity,
    now_utc_iso,
)
from systems.generator.app.runtime_pipeline.pipeline_state import (
    PipelineStateManager,
)
from systems.generator.app.runtime_pipeline.prediction_service import (
    LoadedModelArtifact,
    PredictionService,
    REGISTERED_BASE_MODELS,
)
from systems.generator.app.runtime_pipeline.runtime_feature_service import (
    RuntimeFeatureBundle,
    RuntimeFeatureService,
)

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates individual pipeline run execution across 5 independent stages with checkpoint resumption."""

    def __init__(
        self,
        repository: Optional[PipelineRepository] = None,
        preprocessing_service: Optional[PreprocessingService] = None,
        runtime_feature_service: Optional[RuntimeFeatureService] = None,
        prediction_service: Optional[PredictionService] = None,
        prediction_batch_service: Optional[PredictionBatchService] = None,
        prediction_delivery_service: Optional[PredictionDeliveryService] = None,
    ) -> None:
        self.repository = repository or PipelineRepository()
        self.preprocessing_service = preprocessing_service or PreprocessingService()
        self.runtime_feature_service = runtime_feature_service or RuntimeFeatureService()
        self.prediction_service = prediction_service or PredictionService()
        self.prediction_batch_service = prediction_batch_service or PredictionBatchService()
        self.prediction_delivery_service = prediction_delivery_service or PredictionDeliveryService()

    def get_logical_source_uri(self, source_path: Path) -> str:
        """Convert filesystem path to logical relative URI without exposing local drives or absolute paths."""
        try:
            p = source_path.resolve()
            for root in (PROJECT_ROOT, PATHS.data_incoming, PATHS.data_preprocessed):
                try:
                    rel = p.relative_to(root.resolve())
                    return str(rel).replace("\\", "/")
                except ValueError:
                    pass
        except Exception:
            pass
        return f"data/incoming/{source_path.name}"

    def _load_source_df(self, source_path: Path) -> pd.DataFrame:
        """Parse source observation protocol file (.jsonl or .csv)."""
        if not source_path.exists() or not source_path.is_file():
            raise PipelineInputNotFoundError(
                f"입력 소스 파일을 찾을 수 없습니다: {source_path}",
                details=[{"source_path": str(source_path)}],
                retryable=False,
            )

        if source_path.suffix.lower() == ".jsonl":
            records = []
            with open(source_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        records.append(json.loads(stripped))
            if not records:
                raise PipelineInputNotFoundError(
                    f"입력 jsonl 파일이 비어 있습니다: {source_path}",
                    retryable=False,
                )
            return pd.DataFrame(records)
        elif source_path.suffix.lower() == ".csv":
            df = pd.read_csv(source_path)
            if df.empty:
                raise PipelineInputNotFoundError(
                    f"입력 csv 파일이 비어 있습니다: {source_path}",
                    retryable=False,
                )
            return df
        else:
            raise PipelineInputNotFoundError(
                f"지원하지 않는 입력 파일 형식입니다: {source_path.suffix}",
                retryable=False,
            )

    def _publish_preprocessed_dataset(
        self,
        run_id: str,
        preprocessed_df: pd.DataFrame,
    ) -> ArtifactReference:
        """Atomically persist preprocessed dataset to disk and return validated ArtifactReference."""
        datasets_dir = PATHS.data_preprocessed / "pipeline_datasets" / run_id
        datasets_dir.mkdir(parents=True, exist_ok=True)
        dest_csv = datasets_dir / "observations.csv"
        temp_csv = datasets_dir / f".tmp_{uuid.uuid4().hex}_observations.csv"

        try:
            preprocessed_df.to_csv(temp_csv, index=False, encoding="utf-8")
            temp_csv.replace(dest_csv)
        except Exception as exc:
            if temp_csv.exists():
                try:
                    temp_csv.unlink()
                except Exception:
                    pass
            raise PipelinePreprocessingFailedError(
                f"전처리 데이터셋 파일 저장 실패: {exc}",
                retryable=False,
            ) from exc

        sha256 = compute_file_sha256(dest_csv)
        size_bytes = dest_csv.stat().st_size
        return ArtifactReference(
            uri=str(dest_csv).replace("\\", "/"),
            sha256=sha256,
            role="preprocessed_dataset",
            size_bytes=size_bytes,
        )

    def _validate_checkpoint_output_ref(self, ref: ArtifactReference) -> bool:
        """Verify on-disk existence and SHA-256 integrity for a stage output reference."""
        p = Path(ref.uri)
        if not p.is_file():
            if not p.is_absolute():
                candidates = [
                    (self.repository.base_dir / p).resolve(),
                    (PROJECT_ROOT / p).resolve(),
                ]
                try:
                    candidates.append((PATHS.models_store.parent / p).resolve())
                except Exception:
                    pass
                try:
                    candidates.append((PATHS.models_store / p).resolve())
                except Exception:
                    pass
                try:
                    candidates.append((PATHS.data_preprocessed.parent / p).resolve())
                except Exception:
                    pass
                try:
                    candidates.append((PATHS.data_preprocessed / p).resolve())
                except Exception:
                    pass
                try:
                    candidates.append((self.preprocessing_service.repository.base_dir / p).resolve())
                except Exception:
                    pass

                found = False
                for c in candidates:
                    if c.is_file():
                        p = c
                        found = True
                        break
                if not found:
                    return False
            else:
                return False
        try:
            actual_sha = compute_file_sha256(p)
            return actual_sha == ref.sha256
        except Exception:
            return False

    def execute_queue_item(self, item: PipelineQueueItem) -> PipelineRunState:
        """Execute complete 5-stage pipeline lifecycle for a claimed queue item with checkpoint resumption."""
        # 1. Path, File Existence and Stability Validation
        source_path = validate_pipeline_source_uri(item.source_uri)
        if not source_path.exists() or not source_path.is_file():
            raise PipelineInputNotFoundError(
                f"입력 소스 파일을 찾을 수 없습니다: {source_path}",
                details=[{"source_path": str(source_path)}],
                retryable=False,
            )

        actual_size = source_path.stat().st_size
        if item.size_bytes is not None and actual_size != item.size_bytes:
            raise PipelineSourceFileNotStableError(
                f"소스 파일 크기가 변경되었습니다 (작성 중 또는 불안정 상태): 등록 시={item.size_bytes}B, 현재={actual_size}B",
                details=[{"registered_size": item.size_bytes, "current_size": actual_size}],
                retryable=True,
            )

        actual_sha = compute_file_sha256(source_path)
        if actual_sha != item.source_checksum:
            raise PipelineSourceChecksumChangedError(
                f"소스 파일 체크섬이 변경되었습니다: 등록 시={item.source_checksum}, 현재={actual_sha}",
                details=[{"expected": item.source_checksum, "actual": actual_sha}],
                retryable=True,
            )

        contract_ver = item.pipeline_contract_version or "generator-prediction-result-v1"
        source_identity = item.source_identity or compute_source_identity(
            actual_sha, item.dataset_id, item.dataset_version, contract_ver
        )
        logical_source_uri = self.get_logical_source_uri(source_path)

        # 2. Resumption Planning: Search for existing resumable run
        resumable_run = self.repository.find_resumable_run(source_identity)
        resumed_stage: Optional[str] = None
        checkpoint_to_resume: Optional[PipelineCheckpoint] = None

        if resumable_run:
            chk = self.repository.get_checkpoint(resumable_run.run_id) or resumable_run.checkpoint
            if chk:
                if chk.source_checksum != actual_sha:
                    logger.warning(
                        f"[PipelineService] Source checksum changed for run '{resumable_run.run_id}'. "
                        "Marking existing checkpoint as invalidated and starting fresh run."
                    )
                    chk.status = "invalidated"
                    self.repository.save_checkpoint(chk)
                    resumable_run.status = "failed"
                    resumable_run.checkpoint_status = "invalidated"
                    self.repository.save_run_state(resumable_run)
                elif chk.status == "resumable":
                    checkpoint_to_resume = chk

        if checkpoint_to_resume and resumable_run:
            run_id = resumable_run.run_id
            manager = PipelineStateManager(resumable_run)
            manager.state.job_id = item.job_id

            # Determine furthest valid checkpoint
            last_stg = checkpoint_to_resume.last_completed_stage

            # Check Checkpoint 1 (Preprocessing) validity
            prep_outputs = checkpoint_to_resume.stage_outputs.get("preprocessing", [])
            prep_valid = bool(prep_outputs) and all(self._validate_checkpoint_output_ref(r) for r in prep_outputs)

            # Check Checkpoint 2 (Runtime Feature) validity
            feat_outputs = checkpoint_to_resume.stage_outputs.get("runtime_feature", [])
            feat_valid = prep_valid and bool(feat_outputs) and all(self._validate_checkpoint_output_ref(r) for r in feat_outputs)

            # Check Checkpoint 3 (Prediction) validity
            pred_valid = feat_valid and bool(resumable_run.prediction_results) and last_stg in ("runtime_prediction", "batch_building", "prediction_delivery")

            if pred_valid and last_stg in ("batch_building", "prediction_delivery"):
                resumed_stage = "prediction_delivery"
            elif pred_valid:
                resumed_stage = "batch_building"
            elif feat_valid:
                resumed_stage = "runtime_prediction"
            elif prep_valid:
                resumed_stage = "runtime_feature"
            else:
                resumed_stage = "preprocessing"

            manager.mark_resumed(from_stage=resumed_stage)
        else:
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            source_ref = ArtifactReference(
                uri=logical_source_uri,
                sha256=item.source_checksum,
                role="source_observation_protocol",
                size_bytes=actual_size,
            )
            manager = PipelineStateManager.create(
                run_id=run_id,
                job_id=item.job_id,
                source_ref=source_ref,
            )
            manager.start_run()

            # Checkpoint 0: Source Validated
            manager.record_checkpoint(
                stage_name="source_validated",
                next_stage="preprocessing",
                source_identity=source_identity,
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                pipeline_contract_version=contract_ver,
                status="resumable",
            )
            if manager.state.checkpoint:
                self.repository.save_checkpoint(manager.state.checkpoint)
            self.repository.save_run_state(manager.state)

        # -------------------------------------------------------------
        # Stage 1: Preprocessing (Plan building + Dataset publishing)
        # -------------------------------------------------------------
        dataset_ref: Optional[ArtifactReference] = None
        plan_ref: Optional[ArtifactReference] = None
        plan: dict[str, Any] = {}

        if resumed_stage in ("runtime_feature", "runtime_prediction", "batch_building", "prediction_delivery") and checkpoint_to_resume:
            prep_outputs = checkpoint_to_resume.stage_outputs.get("preprocessing", [])
            for r in prep_outputs:
                if r.role == "preprocessed_dataset":
                    dataset_ref = r
                elif r.role == "preprocessing_plan":
                    plan_ref = r
            logger.info(f"[PipelineService] Resuming: Stage 1 Preprocessing skipped for run '{run_id}'")
            if plan_ref:
                try:
                    plan = self.preprocessing_service.repository.get_plan(item.dataset_id, item.dataset_version) or {}
                except Exception:
                    plan = {}
        else:
            manager.start_stage("preprocessing", input_refs=[manager.state.source_ref])
            try:
                raw_df = self._load_source_df(source_path)

                # Strict validation of ID and timestamp
                id_cols = [c for c in ("asset_id", "Product ID", "UDI", "equipment_id", "machine_id") if c in raw_df.columns]
                if not id_cols:
                    raise PipelineMappingNotImplementedError(
                        "입력 데이터에 확정된 설비 식별자 컬럼이 없어 LLM 기반 자동 매핑이 필요합니다. 현재 단계에서는 지원되지 않습니다.",
                        details=[{
                            "enhancement_issue": 117,
                            "required_capability": "llm_mapping_generation",
                            "source_schema_fingerprint": compute_source_schema_fingerprint(raw_df),
                        }],
                        retryable=False,
                    )

                target_id = id_cols[0]
                raw_id_series = raw_df[target_id]
                invalid_id_mask = (
                    raw_id_series.isna()
                    | raw_id_series.astype(str).str.strip().str.lower().isin(["", "null", "none", "nan"])
                )
                if invalid_id_mask.any():
                    invalid_indices = [int(i) for i in raw_df.index[invalid_id_mask]]
                    raise PipelineAssetIdValueMissingError(
                        f"설비 식별자 컬럼 '{target_id}'에 누락/무효 값(None, 빈문자열, null, none)이 {len(invalid_indices)}건 존재합니다.",
                        details=[{
                            "id_column": target_id,
                            "invalid_row_count": len(invalid_indices),
                            "sample_row_indexes": invalid_indices[:10],
                        }],
                        retryable=False,
                    )

                time_cols = [c for c in ("timestamp", "observed_at", "time", "date", "datetime") if c in raw_df.columns]
                if time_cols:
                    target_time = time_cols[0]
                    raw_ts = raw_df[target_time]
                    if raw_ts.isna().any() or raw_ts.astype(str).str.strip().isin(["", "null", "none", "nan"]).any():
                        raise PipelineTimestampInvalidError(
                            f"타임스탬프 컬럼 '{target_time}'에 결측치 또는 유효하지 않은 값이 포함되어 있습니다.",
                            details=[{"time_column": target_time}],
                            retryable=False,
                        )
                    try:
                        converted_ts = pd.to_datetime(raw_ts, utc=True)
                        if converted_ts.isna().any():
                            raise ValueError("NaT detected")
                    except Exception as exc:
                        raise PipelineTimestampInvalidError(
                            f"타임스탬프 컬럼 '{target_time}' 파싱 실패: {exc}",
                            details=[{"time_column": target_time, "error": str(exc)}],
                            retryable=False,
                        ) from exc

                    # Check for duplicate [asset_id, timestamp] rows
                    raw_df_chk = raw_df.copy()
                    raw_df_chk[target_time] = converted_ts
                    dups = raw_df_chk.duplicated(subset=[target_id, target_time], keep=False)
                    if dups.any():
                        dup_sample = raw_df_chk[dups].iloc[0]
                        sample_asset = str(dup_sample[target_id])
                        sample_ts = str(dup_sample[target_time])
                        raise PipelineTimestampInvalidError(
                            f"동일 설비 '{sample_asset}' 및 시각 '{sample_ts}'에 대한 중복 관측 행이 {dups.sum()}건 존재합니다. 계약상 중복 병합 정책이 정의되지 않아 처리를 중단합니다.",
                            details=[{"asset_id": sample_asset, "timestamp": sample_ts, "duplicate_count": int(dups.sum())}],
                            retryable=False,
                        )

                schema_fp = compute_source_schema_fingerprint(raw_df)

                # Build and validate preprocessing plan
                plan = self.preprocessing_service.planner.build_plan(str(source_path))
                self.preprocessing_service.validate_plan(raw_df, plan)

                # Publish plan to repository
                try:
                    logical_src_uri = self.preprocessing_service.repository.get_logical_uri(source_path)
                except Exception:
                    logical_src_uri = f"data/incoming/{source_path.name}"

                plan_data_to_publish = dict(plan)
                plan_data_to_publish.update({
                    "source_dataset_uri": logical_src_uri,
                    "source_dataset_sha256": item.source_checksum,
                    "source_schema_fingerprint": schema_fp,
                    "source_dataset_size_bytes": source_path.stat().st_size if source_path.exists() else None,
                })
                published_plan = self.preprocessing_service.repository.publish_plan(
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    plan_data=plan_data_to_publish,
                )

                plan_ref = ArtifactReference(
                    uri=published_plan.preprocessing_plan_uri,
                    sha256=published_plan.sha256,
                    role="preprocessing_plan",
                    size_bytes=None,
                )

                # Execute actual preprocessing
                preprocessed_df = self.preprocessing_service.preprocess_with_plan(str(source_path), plan)

                # Atomically publish preprocessed dataset to disk
                dataset_ref = self._publish_preprocessed_dataset(run_id, preprocessed_df)

                manager.register_intermediate_outputs([dataset_ref])
                manager.succeed_stage("preprocessing", output_refs=[plan_ref, dataset_ref])

                # Checkpoint 1: Preprocessing Completed
                manager.record_checkpoint(
                    stage_name="preprocessing",
                    next_stage="runtime_feature",
                    stage_outputs=[plan_ref, dataset_ref],
                    source_identity=source_identity,
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    pipeline_contract_version=contract_ver,
                    status="resumable",
                )
                if manager.state.checkpoint:
                    self.repository.save_checkpoint(manager.state.checkpoint)
                self.repository.save_run_state(manager.state)
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_PREPROCESSING_FAILED")
                retryable = getattr(exc, "retryable", False)
                manager.fail_stage("preprocessing", err_code, str(exc), retryable=retryable)
                manager.finish_run("failed")
                self.repository.save_run_state(manager.state)
                raise

        # -------------------------------------------------------------
        # Stage 2: Runtime Feature (Per-Equipment Isolation & float64 npy)
        # -------------------------------------------------------------
        assert dataset_ref is not None, "dataset_ref must be available"
        model_artifacts: dict[str, LoadedModelArtifact] = {}
        model_feature_refs: dict[str, ArtifactReference] = {}
        model_feature_bundles: dict[str, RuntimeFeatureBundle] = {}
        model_feature_errors: dict[str, Any] = {}
        last_feat_error: Optional[Exception] = None

        if resumed_stage in ("runtime_prediction", "batch_building", "prediction_delivery") and checkpoint_to_resume:
            prep_file_path = Path(dataset_ref.uri)
            if not prep_file_path.is_file():
                prep_file_path = (self.repository.base_dir / dataset_ref.uri).resolve()
            preprocessed_input_df = pd.read_csv(prep_file_path)
            id_col = plan.get("id_column") or "asset_id"
            if id_col not in preprocessed_input_df.columns:
                candidates = [c for c in ("asset_id", "Product ID", "UDI", "equipment_id", "machine_id") if c in preprocessed_input_df.columns]
                id_col = candidates[0] if candidates else "asset_id"

            cached_feat_refs = {}
            for r in checkpoint_to_resume.stage_outputs.get("runtime_feature", []):
                fname = Path(r.uri).name
                mid = fname.split("_")[0] if "_" in fname else ""
                if mid:
                    cached_feat_refs[mid] = r

            for base_model in REGISTERED_BASE_MODELS:
                model_id = self.prediction_service.resolve_model_id(base_model)
                try:
                    artifact = self.prediction_service.load_active_artifact(base_model)
                    model_artifacts[base_model] = artifact

                    cached_ref = cached_feat_refs.get(model_id)
                    if cached_ref and self._validate_checkpoint_output_ref(cached_ref):
                        bundle = self.runtime_feature_service.load_bundle_from_artifact(
                            artifact_ref=cached_ref,
                            preprocessed_df=preprocessed_input_df,
                            feature_schema_dict=artifact.feature_schema,
                            id_column=id_col,
                            time_column=plan.get("time_column"),
                            dataset_id=item.dataset_id,
                            dataset_version=item.dataset_version,
                        )
                        model_feature_refs[base_model] = cached_ref
                        model_feature_bundles[base_model] = bundle
                        logger.info(f"[PipelineService] Reused verified feature for '{model_id}' from checkpoint")
                    else:
                        bundle, feat_ref = self.runtime_feature_service.extract_and_publish(
                            preprocessed_df=preprocessed_input_df,
                            feature_schema_dict=artifact.feature_schema,
                            history_requirement_dict=artifact.history_requirement,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            id_column=id_col,
                            time_column=plan.get("time_column"),
                            dataset_id=item.dataset_id,
                            dataset_version=item.dataset_version,
                            run_id=run_id,
                        )
                        model_feature_refs[base_model] = feat_ref
                        model_feature_bundles[base_model] = bundle
                        logger.info(f"[PipelineService] Re-extracted feature for damaged/missing model '{model_id}'")
                except Exception as exc:
                    last_feat_error = exc
                    model_feature_errors[base_model] = exc
                    logger.warning(f"[PipelineService] Feature loading/extraction failed for '{model_id}': {exc}")
        else:
            manager.start_stage("runtime_feature", input_refs=[dataset_ref, plan_ref] if plan_ref else [dataset_ref])
            try:
                prep_file_path = Path(dataset_ref.uri)
                if not prep_file_path.is_file():
                    prep_file_path = (self.repository.base_dir / dataset_ref.uri).resolve()
                preprocessed_input_df = pd.read_csv(prep_file_path)

                id_col = plan.get("id_column") or "asset_id"
                if id_col not in preprocessed_input_df.columns:
                    candidates = [c for c in ("asset_id", "Product ID", "UDI", "equipment_id", "machine_id") if c in preprocessed_input_df.columns]
                    if candidates:
                        id_col = candidates[0]
                    else:
                        raise PipelineAssetIdColumnMissingError(
                            "전처리 데이터셋에 설비 식별자(asset_id) 컬럼이 누락되었습니다.",
                            retryable=False,
                        )

                actual_asset_ids = sorted(preprocessed_input_df[id_col].dropna().astype(str).unique().tolist())
                if not actual_asset_ids:
                    raise PipelineAssetIdValueMissingError(
                        "전처리 데이터셋에서 유효한 설비 식별자 목록을 추출할 수 없습니다.",
                        retryable=False,
                    )

                cached_feat_refs = {}
                if checkpoint_to_resume:
                    for r in checkpoint_to_resume.stage_outputs.get("runtime_feature", []):
                        fname = Path(r.uri).name
                        mid = fname.split("_")[0] if "_" in fname else ""
                        if mid:
                            cached_feat_refs[mid] = r

                for base_model in REGISTERED_BASE_MODELS:
                    model_id = self.prediction_service.resolve_model_id(base_model)
                    try:
                        artifact = self.prediction_service.load_active_artifact(base_model)
                        model_artifacts[base_model] = artifact

                        cached_ref = cached_feat_refs.get(model_id)
                        if cached_ref and self._validate_checkpoint_output_ref(cached_ref):
                            bundle = self.runtime_feature_service.load_bundle_from_artifact(
                                artifact_ref=cached_ref,
                                preprocessed_df=preprocessed_input_df,
                                feature_schema_dict=artifact.feature_schema,
                                id_column=id_col,
                                time_column=plan.get("time_column"),
                                dataset_id=item.dataset_id,
                                dataset_version=item.dataset_version,
                            )
                            model_feature_refs[base_model] = cached_ref
                            model_feature_bundles[base_model] = bundle
                            logger.info(f"[PipelineService] Reused verified feature for '{model_id}' from checkpoint")
                        else:
                            bundle, feat_ref = self.runtime_feature_service.extract_and_publish(
                                preprocessed_df=preprocessed_input_df,
                                feature_schema_dict=artifact.feature_schema,
                                history_requirement_dict=artifact.history_requirement,
                                model_id=model_id,
                                model_version=artifact.model_version,
                                id_column=id_col,
                                time_column=plan.get("time_column"),
                                dataset_id=item.dataset_id,
                                dataset_version=item.dataset_version,
                                run_id=run_id,
                            )
                            model_feature_refs[base_model] = feat_ref
                            model_feature_bundles[base_model] = bundle
                    except Exception as exc:
                        last_feat_error = exc
                        model_feature_errors[base_model] = exc
                        logger.warning(f"[PipelineService] Feature extraction failed for '{model_id}': {exc}")

                if not model_artifacts:
                    raise PipelineNoActiveModelError(
                        "활성화된 머신러닝 모델 아티팩트가 0개입니다.",
                        retryable=False,
                    )

                if not model_feature_refs:
                    if last_feat_error is not None:
                        raise last_feat_error
                    raise PipelineRuntimeFeatureFailedError(
                        "모든 모델에 대해 Runtime Feature 생성이 실패했습니다.",
                        retryable=False,
                    )

                manager.register_intermediate_outputs(list(model_feature_refs.values()))
                manager.succeed_stage("runtime_feature", output_refs=list(model_feature_refs.values()))

                # Model Snapshot
                model_snapshot = {
                    bm: {
                        "model_id": self.prediction_service.resolve_model_id(bm),
                        "model_version": art.model_version,
                    }
                    for bm, art in model_artifacts.items()
                }

                # Checkpoint 2: Runtime Feature Completed
                manager.record_checkpoint(
                    stage_name="runtime_feature",
                    next_stage="runtime_prediction",
                    stage_outputs=list(model_feature_refs.values()),
                    model_snapshot=model_snapshot,
                    source_identity=source_identity,
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    pipeline_contract_version=contract_ver,
                    status="resumable",
                )
                if manager.state.checkpoint:
                    self.repository.save_checkpoint(manager.state.checkpoint)
                self.repository.save_run_state(manager.state)
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_RUNTIME_FEATURE_FAILED")
                retryable = getattr(exc, "retryable", False)
                manager.fail_stage("runtime_feature", err_code, str(exc), retryable=retryable)
                manager.finish_run("failed")
                self.repository.save_run_state(manager.state)
                raise

        # -------------------------------------------------------------
        # Stage 3: Prediction (Score Calculation across Models per Equipment)
        # -------------------------------------------------------------
        model_results: list[InternalModelPredictionResult] = []

        if resumed_stage in ("batch_building", "prediction_delivery") and resumable_run and resumable_run.prediction_results:
            model_results = list(resumable_run.prediction_results)
            logger.info(f"[PipelineService] Resuming: Stage 3 Runtime Prediction skipped for run '{run_id}'")
        else:
            manager.start_stage("prediction", input_refs=list(model_feature_refs.values()))
            try:
                model_results = self.prediction_service.predict_for_models(
                    base_models=REGISTERED_BASE_MODELS,
                    model_feature_refs=model_feature_refs,
                    model_feature_bundles=model_feature_bundles,
                    model_feature_errors=model_feature_errors,
                )

                succeeded_count = sum(1 for r in model_results if r.status == "succeeded")
                if succeeded_count == 0:
                    raise PipelineModelPredictionFailedError(
                        "모든 모델의 예측 계산이 실패하여 전달 가능한 결과가 없습니다.",
                        details=[{"total_results": len(model_results)}],
                        retryable=False,
                    )

                pred_output_refs = [
                    r.artifact_ref for r in model_results if r.artifact_ref is not None
                ]
                manager.succeed_stage("prediction", output_refs=pred_output_refs)

                # Checkpoint 3: Runtime Prediction Completed
                manager.record_checkpoint(
                    stage_name="runtime_prediction",
                    next_stage="batch_building",
                    stage_outputs=pred_output_refs,
                    source_identity=source_identity,
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    pipeline_contract_version=contract_ver,
                    status="resumable",
                )
                if manager.state.checkpoint:
                    self.repository.save_checkpoint(manager.state.checkpoint)
                self.repository.save_run_state(manager.state)
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_MODEL_PREDICTION_FAILED")
                retryable = getattr(exc, "retryable", False)
                manager.fail_stage("prediction", err_code, str(exc), retryable=retryable)
                manager.finish_run("failed")
                self.repository.save_run_state(manager.state)
                raise

        # -------------------------------------------------------------
        # Stage 4: Batch Building (Collect Model Results per Equipment)
        # -------------------------------------------------------------
        manager.start_stage("batch_building")
        try:
            batch_summary: PredictionBatchSummary = self.prediction_batch_service.collect(model_results)
            manager.record_predictions(model_results)
            manager.succeed_stage("batch_building", output_refs=[])

            # Checkpoint 4: Batch Built
            manager.record_checkpoint(
                stage_name="batch_building",
                next_stage="prediction_delivery",
                source_identity=source_identity,
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                pipeline_contract_version=contract_ver,
                status="resumable",
            )
            if manager.state.checkpoint:
                self.repository.save_checkpoint(manager.state.checkpoint)
            self.repository.save_run_state(manager.state)
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_BATCH_BUILDING_FAILED")
            retryable = getattr(exc, "retryable", False)
            manager.fail_stage("batch_building", err_code, str(exc), retryable=retryable)
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise

        # -------------------------------------------------------------
        # Stage 5: Prediction Delivery (Outbox Persistence for ALL equipments)
        # -------------------------------------------------------------
        if batch_summary.equipment_batches:
            manager.start_stage("prediction_delivery")
            manager.record_prediction_delivery("pending")

            # Post-run verification: ensure source file was not modified during pipeline execution
            post_sha = compute_file_sha256(source_path)
            post_size = source_path.stat().st_size
            if post_sha != item.source_checksum or (item.size_bytes is not None and post_size != item.size_bytes):
                raise PipelineSourceChecksumChangedError(
                    f"파이프라인 실행 도중 소스 파일이 변경되었습니다: 시작={item.source_checksum}, 완료={post_sha}",
                    details=[{"expected": item.source_checksum, "actual": post_sha, "start_size": item.size_bytes, "finish_size": post_size}],
                    retryable=True,
                )

            event_ids: list[str] = []
            events_state: list[PredictionDeliveryEventState] = []

            for asset_id, eq_batch in batch_summary.equipment_batches.items():
                event_id = f"evt-{uuid.uuid4().hex[:16]}"
                event_ids.append(event_id)
                events_state.append(
                    PredictionDeliveryEventState(
                        event_id=event_id,
                        asset_id=asset_id,
                        status="pending",
                        attempt=0,
                        max_attempts=5,
                        next_retry_at=None,
                        last_error_code=None,
                        last_error_message=None,
                        updated_at=now_utc_iso(),
                    )
                )

                batch_observed_at = eq_batch.observed_at
                if not batch_observed_at:
                    raise PipelinePredictionObservationAlignmentNotImplementedError(
                        f"설비 '{asset_id}'의 결과 배치를 위한 관측 시각(observed_at)이 누락되었습니다.",
                        details=[{"asset_id": asset_id}],
                        retryable=False,
                    )

                batch_payload = PredictionResultBatchPayload(
                    event_id=event_id,
                    run_id=run_id,
                    job_id=item.job_id,
                    asset_id=asset_id,
                    observed_at=batch_observed_at,
                    generated_at=now_utc_iso(),
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    model_results=eq_batch.model_results,
                    source_lineage=SourceLineage(
                        source_uri=logical_source_uri,
                        source_checksum=item.source_checksum,
                        pipeline_contract_version=contract_ver,
                    ),
                    sensor_data_ref={"uri": logical_source_uri, "sha256": item.source_checksum},
                )

                # Atomically persist to Outbox directory for background worker delivery
                self.prediction_delivery_service.create_outbox_record(batch_payload)
                self.repository.save_event(batch_payload)

            manager.state.prediction_event_ids = event_ids
            manager.state.prediction_events = events_state
            manager.succeed_stage("prediction_delivery", output_refs=[])

            # Checkpoint 5: Final Published Completed
            manager.record_checkpoint(
                stage_name="prediction_delivery",
                next_stage="completed",
                source_identity=source_identity,
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                pipeline_contract_version=contract_ver,
                status="completed",
            )
            if manager.state.checkpoint:
                self.repository.save_checkpoint(manager.state.checkpoint)
        else:
            manager.record_prediction_delivery("not_required")
            manager.state.prediction_events = []

        # -------------------------------------------------------------
        # Intermediate Outputs Cleanup (Run-Dedicated Files Only)
        # -------------------------------------------------------------
        manager.mark_cleanup_pending()
        self.repository.save_run_state(manager.state)

        cleanup_success, deleted_paths, cleanup_error = self.repository.cleanup_run_intermediate_outputs(
            run_id=run_id,
            intermediate_refs=manager.state.intermediate_outputs,
        )

        if cleanup_success:
            manager.mark_cleaned()
            final_run_status = batch_summary.overall_status
        else:
            manager.mark_cleanup_failed(
                error_code="PIPELINE_INTERMEDIATE_CLEANUP_FAILED",
                error_message=cleanup_error or "Intermediate cleanup failed",
            )
            final_run_status = "succeeded_with_cleanup_warning" if batch_summary.overall_status == "succeeded" else batch_summary.overall_status

        # -------------------------------------------------------------
        # Finish Run and Persist
        # -------------------------------------------------------------
        manager.finish_run(final_run_status)
        self.repository.save_run_state(manager.state)

        return manager.state

"""Pipeline orchestration service executing Preprocessing, Runtime Feature, Prediction, Aggregation, and Notification."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from systems.generator.generator_config import PATHS, validate_pipeline_source_uri
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_repository import (
    compute_source_schema_fingerprint,
)
from systems.generator.app.preprocessing.preprocessing_service import PreprocessingService
from systems.generator.app.runtime_pipeline.aggregation_service import (
    AggregationService,
    AggregationVerdict,
)
from systems.generator.app.runtime_pipeline.notification_service import (
    NotificationService,
)
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineNoActiveModelError,
    PipelinePreprocessingFailedError,
    PipelineRuntimeFeatureFailedError,
)
from systems.generator.app.runtime_pipeline.pipeline_repository import (
    PipelineRepository,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    AnomalySignalPayload,
    ArtifactReference,
    ModelPredictionResult,
    PipelineQueueItem,
    PipelineRunState,
    SourceLineage,
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
    RuntimeFeatureService,
)

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates individual pipeline run execution across 5 independent stages."""

    def __init__(
        self,
        repository: Optional[PipelineRepository] = None,
        preprocessing_service: Optional[PreprocessingService] = None,
        runtime_feature_service: Optional[RuntimeFeatureService] = None,
        prediction_service: Optional[PredictionService] = None,
        aggregation_service: Optional[AggregationService] = None,
        notification_service: Optional[NotificationService] = None,
    ) -> None:
        self.repository = repository or PipelineRepository()
        self.preprocessing_service = preprocessing_service or PreprocessingService()
        self.runtime_feature_service = runtime_feature_service or RuntimeFeatureService()
        self.prediction_service = prediction_service or PredictionService()
        self.aggregation_service = aggregation_service or AggregationService()
        self.notification_service = notification_service or NotificationService()

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

    def execute_queue_item(self, item: PipelineQueueItem) -> PipelineRunState:
        """Execute complete 5-stage pipeline lifecycle for a claimed queue item."""
        # 1. Path and Checksum Validation against allowed roots
        source_path = validate_pipeline_source_uri(item.source_uri)

        actual_sha = compute_file_sha256(source_path)
        if actual_sha != item.source_checksum:
            raise PipelineInputChecksumMismatchError(
                f"소스 파일 체크섬 불일치: 기대={item.source_checksum}, 실제={actual_sha}",
                details=[{"expected": item.source_checksum, "actual": actual_sha}],
                retryable=False,
            )

        source_ref = ArtifactReference(
            uri=item.source_uri,
            sha256=item.source_checksum,
            role="source_observation_file",
            size_bytes=source_path.stat().st_size,
        )

        run_id = f"run-{uuid.uuid4().hex[:12]}"
        manager = PipelineStateManager.create(
            run_id=run_id,
            job_id=item.job_id,
            source_ref=source_ref,
        )
        manager.start_run()

        raw_df = self._load_source_df(source_path)

        # -------------------------------------------------------------
        # Stage 1: Preprocessing (Build Plan & Execute & Publish Dataset)
        # -------------------------------------------------------------
        manager.start_stage("preprocessing", input_refs=[source_ref])
        try:
            plan = self.preprocessing_service.planner.build_plan(str(source_path))
            self.preprocessing_service.validate_plan(raw_df, plan)

            clean_source_uri = item.source_uri
            if Path(clean_source_uri).is_absolute() or ".." in Path(clean_source_uri).parts:
                clean_source_uri = f"data/incoming/{source_path.name}"

            plan["dataset_id"] = item.dataset_id
            plan["dataset_version"] = item.dataset_version
            plan["source_dataset_uri"] = clean_source_uri
            plan["source_dataset_sha256"] = item.source_checksum
            plan["source_schema_fingerprint"] = compute_source_schema_fingerprint(raw_df)
            plan["source_dataset_size_bytes"] = source_path.stat().st_size

            published_plan = self.preprocessing_service.repository.publish_plan(
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                plan_data=plan,
            )

            plan_ref = ArtifactReference(
                uri=published_plan.preprocessing_plan_uri,
                sha256=published_plan.sha256,
                role="preprocessing_plan",
            )

            # Actual execution of plan on raw dataset
            preprocessed_df = self.preprocessing_service.preprocess_with_plan(str(source_path), plan)

            # Atomically publish preprocessed dataset file
            dataset_ref = self._publish_preprocessed_dataset(run_id, preprocessed_df)

            manager.succeed_stage("preprocessing", output_refs=[plan_ref, dataset_ref])
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_PREPROCESSING_FAILED")
            retryable = getattr(exc, "retryable", False)
            manager.fail_stage("preprocessing", err_code, str(exc), retryable=retryable)
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise

        # -------------------------------------------------------------
        # Stage 2: Runtime Feature (Per-Model Extraction & Asset Isolation)
        # -------------------------------------------------------------
        manager.start_stage("runtime_feature", input_refs=[dataset_ref, plan_ref])
        model_artifacts: dict[str, LoadedModelArtifact] = {}
        model_feature_refs: dict[str, ArtifactReference] = {}
        last_feat_error: Optional[Exception] = None

        try:
            # Load preprocessed dataframe from published dataset
            prep_file_path = Path(dataset_ref.uri)
            preprocessed_input_df = pd.read_csv(prep_file_path)

            for base_model in REGISTERED_BASE_MODELS:
                model_id = self.prediction_service.resolve_model_id(base_model)
                try:
                    artifact = self.prediction_service.load_active_artifact(base_model)
                    model_artifacts[base_model] = artifact

                    # Extract feature matrix with strict equipment isolation
                    bundle, feat_ref = self.runtime_feature_service.extract_and_publish(
                        preprocessed_df=preprocessed_input_df,
                        feature_schema_dict=artifact.feature_schema,
                        history_requirement_dict=artifact.history_requirement,
                        id_column=plan.get("id_column"),
                        time_column=plan.get("time_column"),
                        dataset_id=item.dataset_id,
                        dataset_version=item.dataset_version,
                    )
                    model_feature_refs[base_model] = feat_ref
                except Exception as exc:
                    last_feat_error = exc
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

            manager.succeed_stage("runtime_feature", output_refs=list(model_feature_refs.values()))
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_RUNTIME_FEATURE_FAILED")
            retryable = getattr(exc, "retryable", False)
            manager.fail_stage("runtime_feature", err_code, str(exc), retryable=retryable)
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise

        # -------------------------------------------------------------
        # Stage 3: Prediction (Inference from Feature Refs Only)
        # -------------------------------------------------------------
        manager.start_stage("prediction", input_refs=list(model_feature_refs.values()))
        try:
            model_results: list[ModelPredictionResult] = (
                self.prediction_service.execute_predictions_from_feature_refs(
                    model_artifacts=model_artifacts,
                    model_feature_refs=model_feature_refs,
                )
            )
            pred_output_refs = [
                r.artifact_ref for r in model_results if r.artifact_ref is not None
            ]
            manager.succeed_stage("prediction", output_refs=pred_output_refs)
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_MODEL_PREDICTION_FAILED")
            retryable = getattr(exc, "retryable", False)
            manager.fail_stage("prediction", err_code, str(exc), retryable=retryable)
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise

        # -------------------------------------------------------------
        # Stage 4: Aggregation
        # -------------------------------------------------------------
        manager.start_stage("aggregation")
        verdict: AggregationVerdict = self.aggregation_service.aggregate(model_results)
        manager.record_predictions(model_results, verdict.anomaly_detected)
        manager.succeed_stage("aggregation", output_refs=[])

        # -------------------------------------------------------------
        # Stage 5: Notification (if anomaly detected, with Outbox pattern)
        # -------------------------------------------------------------
        if verdict.anomaly_detected is True:
            manager.start_stage("notification")
            manager.record_notification("pending")
            event_id = f"evt-{uuid.uuid4().hex[:16]}"

            # Determine representative asset ID
            asset_id = None
            if "asset_id" in preprocessed_input_df.columns:
                asset_id = str(preprocessed_input_df["asset_id"].iloc[-1])
            elif "Product ID" in preprocessed_input_df.columns:
                asset_id = str(preprocessed_input_df["Product ID"].iloc[-1])

            first_feat_ref = next((r.feature_ref.model_dump() for r in model_results if r.feature_ref), None)

            signal_payload = AnomalySignalPayload(
                event_id=event_id,
                run_id=run_id,
                job_id=item.job_id,
                asset_id=asset_id,
                detected_at=now_utc_iso(),
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
                anomaly_detected=True,
                anomaly_models=verdict.anomaly_models,
                model_results=model_results,
                source_lineage=SourceLineage(
                    source_uri=item.source_uri,
                    source_checksum=item.source_checksum,
                ),
                sensor_data_ref={"uri": item.source_uri, "sha256": item.source_checksum},
                feature_ref=first_feat_ref,
            )

            try:
                self.notification_service.send_notification(signal_payload)
                manager.record_notification("sent")
                manager.succeed_stage("notification", output_refs=[])
                self.repository.save_event(signal_payload)
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_NOTIFICATION_FAILED")
                retryable = getattr(exc, "retryable", True)
                logger.warning(f"[PipelineService] Notification dispatch failed: {exc}")
                manager.record_notification("failed")
                manager.fail_stage("notification", err_code, str(exc), retryable=retryable)
                manager.finish_run(verdict.overall_status)
                self.repository.save_run_state(manager.state)
                # Re-raise so worker can schedule notification retry
                raise
        else:
            manager.record_notification("not_required")

        # -------------------------------------------------------------
        # Finish Run and Persist
        # -------------------------------------------------------------
        manager.finish_run(verdict.overall_status)
        self.repository.save_run_state(manager.state)

        return manager.state

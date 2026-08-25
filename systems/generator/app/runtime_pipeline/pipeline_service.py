"""Pipeline orchestration service executing Preprocessing, Feature, Prediction and Notification."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_planner import PreprocessingPlanner
from systems.generator.app.preprocessing.preprocessing_repository import (
    PreprocessingRepository,
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
    PipelinePreprocessingFailedError,
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
    PredictionService,
)

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates individual pipeline run execution without in-memory state leakage."""

    def __init__(
        self,
        repository: Optional[PipelineRepository] = None,
        preprocessing_service: Optional[PreprocessingService] = None,
        prediction_service: Optional[PredictionService] = None,
        aggregation_service: Optional[AggregationService] = None,
        notification_service: Optional[NotificationService] = None,
    ) -> None:
        self.repository = repository or PipelineRepository()
        self.preprocessing_service = preprocessing_service or PreprocessingService()
        self.prediction_service = prediction_service or PredictionService()
        self.aggregation_service = aggregation_service or AggregationService()
        self.notification_service = notification_service or NotificationService()


    def _load_source_df(self, source_path: Path) -> pd.DataFrame:
        """Parse source observation protocol file (.jsonl or .csv)."""
        if not source_path.exists() or not source_path.is_file():
            raise PipelineInputNotFoundError(
                f"입력 소스 파일을 찾을 수 없습니다: {source_path}",
                details=[{"source_path": str(source_path)}],
            )

        if source_path.suffix.lower() == ".jsonl":
            records = []
            with open(source_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        records.append(json.loads(stripped))
            if not records:
                raise PipelineInputNotFoundError(f"입력 jsonl 파일이 비어 있습니다: {source_path}")
            return pd.DataFrame(records)
        elif source_path.suffix.lower() == ".csv":
            df = pd.read_csv(source_path)
            if df.empty:
                raise PipelineInputNotFoundError(f"입력 csv 파일이 비어 있습니다: {source_path}")
            return df
        else:
            raise PipelineInputNotFoundError(f"지원하지 않는 입력 파일 형식입니다: {source_path.suffix}")

    def execute_queue_item(self, item: PipelineQueueItem) -> PipelineRunState:
        """Execute complete pipeline lifecycle for a claimed queue item."""
        source_path = Path(item.source_uri)
        if not source_path.is_absolute():
            source_path = (Path.cwd() / source_path).resolve()

        if not source_path.is_file():
            raise PipelineInputNotFoundError(
                f"소스 파일이 존재하지 않습니다: {source_path}",
                details=[{"source_uri": item.source_uri}],
            )

        actual_sha = compute_file_sha256(source_path)
        if actual_sha != item.source_checksum:
            raise PipelineInputChecksumMismatchError(
                f"소스 파일 체크섬 불일치: 기대={item.source_checksum}, 실제={actual_sha}",
                details=[{"expected": item.source_checksum, "actual": actual_sha}],
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
        # Stage 1: Preprocessing
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
            manager.succeed_stage("preprocessing", output_refs=[plan_ref])
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_PREPROCESSING_FAILED")
            manager.fail_stage("preprocessing", err_code, str(exc))
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise PipelinePreprocessingFailedError(f"Preprocessing 단계 실패: {exc}") from exc


        # -------------------------------------------------------------
        # Stage 2: Prediction (includes Runtime Feature generation)
        # -------------------------------------------------------------
        manager.start_stage("prediction", input_refs=[source_ref, plan_ref])
        try:
            model_results = self.prediction_service.execute_predictions(
                preprocessed_df=raw_df,
                dataset_id=item.dataset_id,
                dataset_version=item.dataset_version,
            )
            pred_output_refs = [
                r.artifact_ref for r in model_results if r.artifact_ref is not None
            ]
            manager.succeed_stage("prediction", output_refs=pred_output_refs)
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_MODEL_PREDICTION_FAILED")
            manager.fail_stage("prediction", err_code, str(exc))
            manager.finish_run("failed")
            self.repository.save_run_state(manager.state)
            raise

        # -------------------------------------------------------------
        # Stage 3: Aggregation
        # -------------------------------------------------------------
        manager.start_stage("aggregation")
        verdict: AggregationVerdict = self.aggregation_service.aggregate(model_results)
        manager.record_predictions(model_results, verdict.anomaly_detected)
        manager.succeed_stage("aggregation", output_refs=[])

        # -------------------------------------------------------------
        # Stage 4: Notification (if anomaly detected)
        # -------------------------------------------------------------
        if verdict.anomaly_detected is True:
            manager.start_stage("notification")
            manager.record_notification("pending")
            event_id = f"evt-{uuid.uuid4().hex[:16]}"

            # Determine representative asset ID and feature ref
            asset_id = None
            if "asset_id" in raw_df.columns:
                asset_id = str(raw_df["asset_id"].iloc[-1])
            elif "Product ID" in raw_df.columns:
                asset_id = str(raw_df["Product ID"].iloc[-1])

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
                logger.warning(f"[PipelineService] Notification dispatch failed: {exc}")
                manager.record_notification("failed")
                manager.fail_stage("notification", err_code, str(exc), retryable=True)
                # Prediction results remain preserved!
        else:
            manager.record_notification("not_required")

        # -------------------------------------------------------------
        # Finish Run and Persist
        # -------------------------------------------------------------
        manager.finish_run(verdict.overall_status)
        self.repository.save_run_state(manager.state)
        return manager.state

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
    PipelineAssetIdMissingError,
    PipelineInputChecksumMismatchError,
    PipelineInputNotFoundError,
    PipelineMappingNotImplementedError,
    PipelineNoActiveModelError,
    PipelinePreprocessingFailedError,
    PipelineRuntimeFeatureFailedError,
    PipelineTimestampInvalidError,
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
    RuntimeFeatureBundle,
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

        # 2. Initialize State Manager
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        source_ref = ArtifactReference(
            uri=item.source_uri,
            sha256=item.source_checksum,
            role="source_observation_protocol",
            size_bytes=source_path.stat().st_size if source_path.exists() else None,
        )
        manager = PipelineStateManager.create(
            run_id=run_id,
            job_id=item.job_id,
            source_ref=source_ref,
        )
        manager.start_run()

        # -------------------------------------------------------------
        # Stage 1: Preprocessing (Plan building + Dataset publishing)
        # -------------------------------------------------------------
        manager.start_stage("preprocessing", input_refs=[source_ref])
        try:
            raw_df = self._load_source_df(source_path)

            # 1. Early strict validation of ID and timestamp
            id_cols = [c for c in ("asset_id", "Product ID", "UDI", "equipment_id") if c in raw_df.columns]
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
                raise PipelineAssetIdMissingError(
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

            manager.succeed_stage("preprocessing", output_refs=[plan_ref, dataset_ref])
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
        manager.start_stage("runtime_feature", input_refs=[dataset_ref, plan_ref])
        model_artifacts: dict[str, LoadedModelArtifact] = {}
        model_feature_refs: dict[str, ArtifactReference] = {}
        model_feature_bundles: dict[str, RuntimeFeatureBundle] = {}
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
                    model_feature_bundles[base_model] = bundle
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
        # Stage 3: Prediction (Inference from Feature Refs per Equipment)
        # -------------------------------------------------------------
        manager.start_stage("prediction", input_refs=list(model_feature_refs.values()))
        try:
            model_results: list[ModelPredictionResult] = (
                self.prediction_service.execute_predictions_from_feature_refs(
                    model_artifacts=model_artifacts,
                    model_feature_refs=model_feature_refs,
                    model_feature_bundles=model_feature_bundles,
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
        # Stage 4: Aggregation (Per-Equipment Aggregation)
        # -------------------------------------------------------------
        manager.start_stage("aggregation")
        verdict: AggregationVerdict = self.aggregation_service.aggregate(model_results)
        manager.record_predictions(model_results, verdict.anomaly_detected)
        manager.succeed_stage("aggregation", output_refs=[])

        # -------------------------------------------------------------
        # Stage 5: Notification (Outbox Persistence per Anomalous Equipment)
        # -------------------------------------------------------------
        if verdict.anomalous_assets:
            manager.start_stage("notification")
            manager.record_notification("pending")
            event_ids: list[str] = []

            for asset_id in verdict.anomalous_assets:
                eq_verdict = verdict.equipment_verdicts[asset_id]
                event_id = f"evt-{uuid.uuid4().hex[:16]}"
                event_ids.append(event_id)

                first_feat_ref = next(
                    (r.feature_ref.model_dump() for r in eq_verdict.model_results if r.feature_ref),
                    None,
                )

                signal_payload = AnomalySignalPayload(
                    event_id=event_id,
                    run_id=run_id,
                    job_id=item.job_id,
                    asset_id=asset_id,
                    detected_at=now_utc_iso(),
                    dataset_id=item.dataset_id,
                    dataset_version=item.dataset_version,
                    anomaly_detected=True,
                    anomaly_models=eq_verdict.anomaly_models,
                    model_results=eq_verdict.model_results,
                    source_lineage=SourceLineage(
                        source_uri=item.source_uri,
                        source_checksum=item.source_checksum,
                    ),
                    sensor_data_ref={"uri": item.source_uri, "sha256": item.source_checksum},
                    feature_ref=first_feat_ref,
                )

                # Persist to Outbox directory atomically for dedicated NotificationWorker delivery
                self.notification_service.create_outbox_record(signal_payload)
                self.repository.save_event(signal_payload)

            manager.state.notification_event_ids = event_ids
            manager.succeed_stage("notification", output_refs=[])
        else:
            manager.record_notification("not_required")

        # -------------------------------------------------------------
        # Finish Run and Persist
        # -------------------------------------------------------------
        manager.finish_run(verdict.overall_status)
        self.repository.save_run_state(manager.state)

        return manager.state

"""Training orchestration service for canonical /train API."""

from __future__ import annotations

import logging
import math
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from systems.generator.generator_config import PATHS
from systems.generator.common.timestamp_canonicalizer import canonicalize_timestamp_series
from systems.generator.model.lightgbm import LightGBMModel
from systems.generator.model.random_forest import RandomForestModel
from systems.generator.model.xgboost import XGBoostModel
from systems.generator.model.model_training import (
    FRAMEWORK_BY_ALGORITHM,
    asset_time_split,
    infer_history_requirement,
)
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider
from systems.generator.app.feature.label_schema_provider import LabelSchemaProvider
from systems.generator.app.training.training_exception import (
    TrainingError,
    FeatureDatasetNotFoundError,
    ModelNotRegisteredError,
    TrainingAlreadyRunningError,
    ModelArtifactConflictError,
    FeatureDatasetIntegrityError,
    FeatureSchemaMismatchError,
    LabelSchemaMismatchError,
    TrainingSplitMetadataMissingError,
    InsufficientTrainingDataError,
    ModelTrainingFailedError,
    ModelArtifactPublishFailedError,
)
from systems.generator.app.training.training_repository import TrainingRepository
from systems.generator.app.training.training_schema import (
    TrainingRequest,
    TrainingResponse,
    ModelResultItem,
    FailedModelItem,
)

logger = logging.getLogger(__name__)

# Registered base models
REGISTERED_MODELS: dict[str, type[Any]] = {
    "lightgbm": LightGBMModel,
    "xgboost": XGBoostModel,
    "random_forest": RandomForestModel,
}

# Process-wide training lock
_training_lock = threading.Lock()


def get_training_lock() -> threading.Lock:
    """Return process-wide training lock for synchronization."""
    return _training_lock


def _calculate_evaluation_metrics(
    y_true: np.ndarray, probabilities: np.ndarray, threshold: float = 0.5
) -> dict[str, Any]:
    """Calculate standard evaluation metrics."""
    y_arr = np.asarray(y_true).astype(int)
    prob_pos = probabilities[:, 1] if probabilities.ndim == 2 else probabilities
    preds = (prob_pos >= threshold).astype(int)

    matrix = confusion_matrix(y_arr, preds, labels=[0, 1]).astype(int).tolist()
    ap = float(average_precision_score(y_arr, prob_pos)) if len(np.unique(y_arr)) > 1 else 0.0
    auc = float(roc_auc_score(y_arr, prob_pos)) if len(np.unique(y_arr)) > 1 else 0.0

    return {
        "precision": float(precision_score(y_arr, preds, zero_division=0)),
        "recall": float(recall_score(y_arr, preds, zero_division=0)),
        "f1_score": float(f1_score(y_arr, preds, zero_division=0)),
        "average_precision": ap,
        "roc_auc": auc,
        "confusion_matrix": matrix,
        "samples_evaluated": int(len(y_arr)),
        "positive_rate": float(np.mean(y_arr)) if len(y_arr) > 0 else 0.0,
    }


class TrainingService:
    """Service orchestrating dataset validation, time splitting, training, and artifact publishing."""

    def __init__(
        self,
        repository: TrainingRepository | None = None,
        feature_schema_provider: FeatureSchemaProvider | None = None,
        label_schema_provider: LabelSchemaProvider | None = None,
    ) -> None:
        self.repository = repository or TrainingRepository()
        self.feature_schema_provider = feature_schema_provider or FeatureSchemaProvider()
        self.label_schema_provider = label_schema_provider or LabelSchemaProvider()

    def run_training(
        self,
        request: TrainingRequest,
        base_model: str | None = None,
        request_id: str | None = None,
    ) -> TrainingResponse:
        """Execute canonical training pipeline under process-wide lock."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        run_id = f"train-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        logger.info(
            f"[TrainingService] Starting training run={run_id}, req={req_id}, "
            f"feature_dataset_version={request.feature_dataset_version}, base_model={base_model or 'all'}"
        )

        # 1. Acquire process-wide lock
        acquired = _training_lock.acquire(blocking=False)
        if not acquired:
            logger.warning(f"[TrainingService] Training lock conflict for run={run_id}")
            raise TrainingAlreadyRunningError("모델 학습이 이미 진행 중입니다.")

        try:
            return self._execute_training_internal(
                request=request,
                base_model=base_model,
                request_id=req_id,
                run_id=run_id,
            )
        finally:
            _training_lock.release()

    def _execute_training_internal(
        self,
        request: TrainingRequest,
        base_model: str | None,
        request_id: str,
        run_id: str,
    ) -> TrainingResponse:
        # Step 0: Validate target models
        if base_model is not None:
            if base_model not in REGISTERED_MODELS:
                raise ModelNotRegisteredError(
                    f"지원하지 않는 모델 알고리즘입니다: '{base_model}'. "
                    f"사용 가능한 모델: {list(REGISTERED_MODELS.keys())}"
                )
            target_models = [base_model]
        else:
            target_models = list(REGISTERED_MODELS.keys())

        # Step 1: Bundle validation & loading
        logger.info(f"[TrainingService] Step 1: bundle_validation for {request.feature_dataset_version}")
        X, y, feature_columns, metadata, row_metadata = self.repository.load_feature_bundle(
            request.feature_dataset_version
        )

        # Validate Schema versions
        feature_schema_ver = metadata.get("feature_schema_version", "pdm-feature-v1")
        label_schema_ver = metadata.get("label_schema_version", "pdm-label-v1")
        horizon_hours = metadata.get("prediction_horizon_hours", 24)

        try:
            feat_schema = self.feature_schema_provider.get_schema(feature_schema_ver)
            if set(feat_schema.feature_names) != set(feature_columns):
                raise FeatureSchemaMismatchError(
                    f"Feature columns do not match schema declaration: declared={feat_schema.feature_names}, got={feature_columns}"
                )
        except FeatureSchemaMismatchError:
            raise
        except Exception as exc:
            raise FeatureSchemaMismatchError(f"Feature Schema 검증 실패: {exc}") from exc

        try:
            self.label_schema_provider.validate_label_schema(
                schema_version=label_schema_ver,
                requested_horizon_hours=horizon_hours,
            )
        except LabelSchemaMismatchError:
            raise
        except Exception as exc:
            raise LabelSchemaMismatchError(f"Label Schema 검증 실패: {exc}") from exc

        # Step 2: Data split (asset_time_split)
        logger.info(f"[TrainingService] Step 2: data_split")
        train_idx, val_idx, test_idx = self._resolve_split_indices(
            metadata=metadata,
            row_metadata=row_metadata,
            total_rows=len(y),
        )

        # Build DataFrames with feature names for sklearn/lgb/xgb
        full_df = pd.DataFrame(X, columns=feature_columns)
        full_df["label"] = y

        train_df = full_df.iloc[train_idx].reset_index(drop=True)
        val_df = full_df.iloc[val_idx].reset_index(drop=True) if len(val_idx) > 0 else full_df.iloc[0:0]
        test_df = full_df.iloc[test_idx].reset_index(drop=True) if len(test_idx) > 0 else full_df.iloc[0:0]

        logger.info(
            f"[TrainingService] Split sizes: train={len(train_df)}, val={len(val_df)}, test={len(test_df)}"
        )

        results: list[ModelResultItem] = []
        failed_models: list[FailedModelItem] = []

        # Step 3: Execute model training per model with failure isolation
        for name in target_models:
            model_cls = REGISTERED_MODELS[name]
            try:
                result_item = self._train_single_algorithm(
                    name=name,
                    model_cls=model_cls,
                    train_df=train_df,
                    val_df=val_df,
                    test_df=test_df,
                    feature_names=feature_columns,
                    metadata=metadata,
                    request=request,
                    run_id=run_id,
                )
                results.append(result_item)
            except Exception as exc:
                err_id = f"err-{uuid.uuid4().hex[:8]}"
                logger.exception(
                    f"[TrainingService] Model training failed for base_model={name}, error_id={err_id}: {exc}"
                )
                failed_models.append(
                    FailedModelItem(
                        base_model=name,
                        code="MODEL_TRAINING_FAILED",
                        error_id=err_id,
                    )
                )
                if base_model is not None:
                    # Single model request fails with 500
                    raise ModelTrainingFailedError(
                        f"모델 '{name}' 학습 실행에 실패했습니다: {exc}",
                        details=[{"error_id": err_id, "base_model": name}],
                    ) from exc

        # Step 5: Determine overall status
        if not results:
            # All models failed in multi-model run
            raise ModelTrainingFailedError(
                "모든 모델 학습에 실패했습니다.",
                details=[f.model_dump() for f in failed_models],
            )

        status_str = "succeeded" if not failed_models else "partially_succeeded"
        return TrainingResponse(
            request_id=request_id,
            run_id=run_id,
            status=status_str,
            feature_dataset_version=request.feature_dataset_version,
            results=results,
            failed_models=failed_models,
        )

    def _resolve_split_indices(
        self,
        metadata: dict[str, Any],
        row_metadata: dict[str, Any] | None,
        total_rows: int,
    ) -> tuple[list[int], list[int], list[int]]:
        """Resolve chronological asset-time split indices."""
        # 1. Check if metadata has split_indices
        if "split_indices" in metadata and isinstance(metadata["split_indices"], dict):
            sp = metadata["split_indices"]
            if "train" in sp and "val" in sp and "test" in sp:
                return sp["train"], sp["val"], sp["test"]

        # 2. Check if row_metadata has asset_ids and timestamps
        if row_metadata and "asset_ids" in row_metadata and "timestamps" in row_metadata:
            asset_ids = row_metadata["asset_ids"]
            timestamps = row_metadata["timestamps"]
            if len(asset_ids) == total_rows and len(timestamps) == total_rows:
                df_meta = pd.DataFrame({"asset_id": asset_ids, "timestamp": timestamps})
                train_sub, val_sub, test_sub = asset_time_split(
                    df_meta, id_col="asset_id", time_col="timestamp"
                )
                return (
                    train_sub.index.tolist(),
                    val_sub.index.tolist(),
                    test_sub.index.tolist(),
                )

        # 3. Fallback: If no split metadata or row metadata exists, fail fast
        raise TrainingSplitMetadataMissingError(
            "시간순 데이터 분할(asset_time_split)을 위한 메타데이터(asset_id, timestamp 등)가 누락되었습니다."
        )

    def _train_single_algorithm(
        self,
        name: str,
        model_cls: type[Any],
        train_df: pd.DataFrame,
        val_df: pd.DataFrame,
        test_df: pd.DataFrame,
        feature_names: list[str],
        metadata: dict[str, Any],
        request: TrainingRequest,
        run_id: str,
    ) -> ModelResultItem:
        logger.info(f"[TrainingService] Training algorithm: {name}")
        model = model_cls()
        model.train(
            train_df,
            feature_names=feature_names,
            target_col="label",
        )

        # Evaluation
        val_probs = model.predict_proba(val_df) if not val_df.empty else np.zeros((0, 2))
        val_metrics = (
            _calculate_evaluation_metrics(val_df["label"].values, val_probs)
            if not val_df.empty
            else {}
        )

        test_probs = model.predict_proba(test_df) if not test_df.empty else np.zeros((0, 2))
        test_metrics = (
            _calculate_evaluation_metrics(test_df["label"].values, test_probs)
            if not test_df.empty
            else {}
        )

        # Serialization to temp file
        temp_dir = Path(tempfile.mkdtemp(prefix="training_joblib_"))
        try:
            model_joblib_path = temp_dir / "model.joblib"
            model.save(str(model_joblib_path))

            # Determine identifiers
            model_id = name
            model_version = self.repository.get_next_model_version(model_id)
            dataset_version = metadata.get("dataset_version", "v1.0")
            feature_schema_ver = metadata.get("feature_schema_version", "pdm-feature-v1")
            label_schema_ver = metadata.get("label_schema_version", "pdm-label-v1")
            horizon_hours = metadata.get("prediction_horizon_hours", 24)
            framework = FRAMEWORK_BY_ALGORITHM.get(name, getattr(model, "framework", name))

            # History requirement
            history_requirement = {
                "history_requirement_version": "pdm-history-v1",
                "expected_sampling_interval_seconds": 3600,
                "minimum_history_rows": 10,
                "maximum_lookback_hours": horizon_hours,
                "history_sufficiency_policy": "decision-required",
                "missing_history_policy": "fail",
                "current_observation_included_in_window": True,
            }

            label_schema_payload = {
                "label_schema_version": label_schema_ver,
                "target": "label",
                "prediction_task": "binary_failure_within_horizon",
                "prediction_horizon_hours": horizon_hours,
            }

            prediction_contract = {
                "prediction_task": "binary_failure_within_horizon",
                "prediction_horizon_hours": horizon_hours,
                "probability_output": "positive_class_probability",
                "positive_class": 1,
            }

            model_runtime = {
                "format": "joblib",
                "framework": framework,
                "framework_api": "sklearn",
                "entry_role": "model",
                "output_type": "positive_class_probability",
            }

            training_config = {
                "algorithm": name,
                "framework": framework,
                "target_name": "label",
                "feature_count": len(feature_names),
                "split_strategy": "asset_time_split",
                "random_seed": 42,
            }

            metrics_payload = {
                "metrics_schema_version": "pdm-metrics-v1",
                "validation_metrics": val_metrics,
                "test_metrics": test_metrics,
                "train_positive_rate": float(train_df["label"].mean()) if not train_df.empty else 0.0,
            }

            provenance_payload = {
                "training": {
                    "run_id": run_id,
                    "publisher": "systems/generator",
                    "feature_dataset_version": request.feature_dataset_version,
                    "dataset_id": metadata.get("dataset_id"),
                    "dataset_version": dataset_version,
                    "failure_dataset_id": metadata.get("failure_dataset_id"),
                    "failure_dataset_version": metadata.get("failure_dataset_version"),
                }
            }

            compatibility_payload = {
                "runtime": "ontology_dashboard.systems.backend.diagnosis",
                "feature_executor_version": "pdm-feature-executor-v1",
                "prediction_task": "binary_failure_within_horizon",
                "python": ">=3.11",
            }

            # Publish Model Artifact atomically
            artifact_path = self.repository.publish_model_artifact(
                model_id=model_id,
                model_version=model_version,
                dataset_version=dataset_version,
                feature_schema_version=feature_schema_ver,
                model_file=model_joblib_path,
                feature_schema={
                    "schema_version": feature_schema_ver,
                    "features": feature_names,
                    "target": "label",
                    "prediction_task": "binary_failure_within_horizon",
                    "feature_executor_version": "pdm-feature-executor-v1",
                    "partition_by": metadata.get("id_column", "asset_id"),
                    "order_by": metadata.get("time_column", "timestamp"),
                },
                training_config=training_config,
                metrics=metrics_payload,
                label_schema=label_schema_payload,
                history_requirement=history_requirement,
                prediction_contract=prediction_contract,
                model_runtime=model_runtime,
                provenance=provenance_payload,
                compatibility=compatibility_payload,
            )

            # Return logical relative artifact URI
            try:
                rel_uri = artifact_path.relative_to(PATHS.models_store.parent).as_posix()
            except ValueError:
                rel_uri = str(artifact_path)

            return ModelResultItem(
                base_model=name,
                status="succeeded",
                model_id=model_id,
                model_version=model_version,
                artifact_uri=rel_uri,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

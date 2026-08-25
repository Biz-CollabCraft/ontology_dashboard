"""Service for executing multi-model predictions against active Model Artifacts across equipment."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.model.publisher import ModelArtifactPublisher
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineModelArtifactInvalidError,
    PipelineModelPredictionFailedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    ModelPredictionResult,
    now_utc_iso,
)
from systems.generator.app.runtime_pipeline.runtime_feature_service import RuntimeFeatureBundle

logger = logging.getLogger(__name__)

REGISTERED_BASE_MODELS = ["lightgbm", "xgboost", "random_forest"]


@dataclass
class LoadedModelArtifact:
    model_id: str
    model_version: str
    model: Any
    manifest: dict[str, Any]
    feature_schema: dict[str, Any]
    label_schema: dict[str, Any]
    history_requirement: dict[str, Any]
    metrics: dict[str, Any]
    artifact_dir: Path
    artifact_ref: ArtifactReference


class PredictionService:
    """Loads active Model Artifacts and executes inference from published Runtime Feature references per equipment."""

    def __init__(
        self,
        models_store_dir: Optional[Path] = None,
        publisher: Optional[ModelArtifactPublisher] = None,
    ) -> None:
        if models_store_dir is None:
            self.models_store = PATHS.models_store
            self.artifacts_dir = self.models_store / "artifacts"
        else:
            base_p = Path(models_store_dir)
            if base_p.name == "artifacts":
                self.artifacts_dir = base_p
                self.models_store = base_p.parent
            else:
                self.models_store = base_p
                self.artifacts_dir = base_p / "artifacts"

        self.publisher = publisher or ModelArtifactPublisher(self.artifacts_dir)

    def resolve_model_id(self, base_or_id: str) -> str:
        clean = base_or_id.strip()
        if clean.startswith("pdm-"):
            return clean
        return f"pdm-{clean}"

    def load_active_artifact(self, base_or_id: str) -> LoadedModelArtifact:
        """Resolve latest.json, strictly verify all 6 files and checksums, and load model."""
        model_id = self.resolve_model_id(base_or_id)
        latest_file = self.artifacts_dir / model_id / "latest.json"

        if not latest_file.exists():
            raise PipelineModelArtifactInvalidError(
                f"모델 '{model_id}'의 latest.json 포인터가 존재하지 않습니다.",
                details=[{"model_id": model_id, "pointer_path": str(latest_file)}],
                retryable=False,
            )

        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                pointer_data = json.load(f)
        except Exception as exc:
            raise PipelineModelArtifactInvalidError(
                f"모델 '{model_id}'의 latest.json 파싱 실패: {exc}",
                details=[{"model_id": model_id, "error": str(exc)}],
                retryable=False,
            ) from exc

        model_version = pointer_data.get("model_version") or pointer_data.get("active_version")
        if not model_version:
            raise PipelineModelArtifactInvalidError(
                f"latest.json에 유효한 model_version이 없습니다 ({model_id}).",
                retryable=False,
            )

        target_artifact_dir = self.artifacts_dir / model_id / model_version
        if not target_artifact_dir.is_dir():
            raise PipelineModelArtifactInvalidError(
                f"latest.json이 가리키는 아티팩트 디렉터리가 존재하지 않습니다: {target_artifact_dir}",
                retryable=False,
            )

        manifest_file = target_artifact_dir / "manifest.json"
        if not manifest_file.exists():
            raise PipelineModelArtifactInvalidError(
                f"manifest.json이 누락되었습니다: {manifest_file}",
                retryable=False,
            )

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.publisher.validate_manifest(manifest_data, target_artifact_dir)
        except Exception as exc:
            raise PipelineModelArtifactInvalidError(
                f"아티팩트 manifest 검증 실패 ({model_id}/{model_version}): {exc}",
                details=[{"model_id": model_id, "model_version": model_version, "error": str(exc)}],
                retryable=False,
            ) from exc

        # Load payload files
        model_path = target_artifact_dir / "model.joblib"
        feat_schema_path = target_artifact_dir / "feature_schema.json"
        lbl_schema_path = target_artifact_dir / "label_schema.json"
        hist_req_path = target_artifact_dir / "history_requirement.json"
        metrics_path = target_artifact_dir / "metrics.json"

        try:
            model_obj = joblib.load(model_path)
            feat_schema = json.loads(feat_schema_path.read_text(encoding="utf-8"))
            lbl_schema = json.loads(lbl_schema_path.read_text(encoding="utf-8"))
            hist_req = json.loads(hist_req_path.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise PipelineModelArtifactInvalidError(
                f"아티팩트 페이로드 파일 로드 실패 ({model_id}/{model_version}): {exc}",
                retryable=False,
            ) from exc

        manifest_sha = compute_file_sha256(manifest_file)
        artifact_ref = ArtifactReference(
            uri=str(target_artifact_dir).replace("\\", "/"),
            sha256=manifest_sha,
            role="model_artifact",
            size_bytes=None,
        )

        return LoadedModelArtifact(
            model_id=model_id,
            model_version=model_version,
            model=model_obj,
            manifest=manifest_data,
            feature_schema=feat_schema,
            label_schema=lbl_schema,
            history_requirement=hist_req,
            metrics=metrics,
            artifact_dir=target_artifact_dir,
            artifact_ref=artifact_ref,
        )

    def execute_predictions_from_feature_refs(
        self,
        *,
        model_artifacts: dict[str, LoadedModelArtifact],
        model_feature_refs: dict[str, ArtifactReference],
        model_feature_bundles: Optional[dict[str, RuntimeFeatureBundle]] = None,
        asset_ids: Optional[list[str]] = None,
        model_feature_errors: Optional[dict[str, Any]] = None,
    ) -> list[ModelPredictionResult]:
        """Run pure model inference for each equipment over all active models consuming published features."""
        results: list[ModelPredictionResult] = []
        now = now_utc_iso()

        # Resolve all known equipment IDs
        known_assets: list[str] = list(asset_ids or [])
        if not known_assets and model_feature_bundles:
            for b in model_feature_bundles.values():
                if b and b.row_metadata:
                    for rm in b.row_metadata:
                        if rm.asset_id not in known_assets:
                            known_assets.append(rm.asset_id)
        if not known_assets:
            known_assets = ["default_asset"]

        for base_model, artifact in model_artifacts.items():
            model_id = artifact.model_id
            feature_ref = model_feature_refs.get(base_model) or model_feature_refs.get(model_id)
            bundle = (model_feature_bundles or {}).get(base_model)

            if feature_ref is None:
                err_info = (model_feature_errors or {}).get(base_model)
                err_code = getattr(err_info, "code", "PIPELINE_RUNTIME_FEATURE_FAILED") if err_info else "PIPELINE_RUNTIME_FEATURE_FAILED"
                err_msg = str(err_info) if err_info else f"모델 '{model_id}'에 해당하는 Runtime Feature가 생성되지 않았습니다."
                for target_asset in known_assets:
                    results.append(
                        ModelPredictionResult(
                            asset_id=target_asset,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            status="failed",
                            prediction="failed",
                            probability=None,
                            threshold=0.5,
                            is_anomaly=None,
                            predicted_at=now,
                            artifact_ref=artifact.artifact_ref,
                            feature_ref=None,
                            error_code=err_code,
                            error_message=err_msg,
                        )
                    )
                continue

            # Load feature matrix from published npy file
            try:
                feat_path = Path(feature_ref.uri)
                if not feat_path.exists():
                    raise FileNotFoundError(f"Runtime feature file not found: {feat_path}")
                features_matrix = np.load(feat_path, allow_pickle=False)
                if features_matrix.size == 0:
                    raise ValueError("Feature matrix is empty")
            except Exception as exc:
                logger.warning(f"[PredictionService] Failed to load feature npy for '{model_id}': {exc}")
                for target_asset in known_assets:
                    results.append(
                        ModelPredictionResult(
                            asset_id=target_asset,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            status="failed",
                            prediction="failed",
                            probability=None,
                            threshold=0.5,
                            is_anomaly=None,
                            predicted_at=now,
                            artifact_ref=artifact.artifact_ref,
                            feature_ref=feature_ref,
                            error_code="PIPELINE_RUNTIME_FEATURE_FAILED",
                            error_message=f"Runtime feature npy 로드 실패: {exc}",
                        )
                    )
                continue

            # Map row metadata to equipments
            # Determine latest row index per equipment
            asset_latest_row: dict[str, int] = {}
            if bundle and bundle.row_metadata:
                for row_meta in bundle.row_metadata:
                    asset_latest_row[row_meta.asset_id] = row_meta.row_index
            else:
                asset_latest_row["default_asset"] = len(features_matrix) - 1

            # Iterate over each equipment
            for asset_id, latest_idx in asset_latest_row.items():

                # Check history sufficiency for this asset
                history_status = (bundle.asset_history_status or {}).get(asset_id) if bundle else None
                if history_status and not history_status.get("ready", True):
                    actual_count = history_status.get("count", 0)
                    min_req = history_status.get("minimum_history_rows", 1)
                    results.append(
                        ModelPredictionResult(
                            asset_id=asset_id,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            status="unknown",
                            prediction="unknown",
                            probability=None,
                            threshold=0.5,
                            is_anomaly=None,
                            predicted_at=now,
                            artifact_ref=artifact.artifact_ref,
                            feature_ref=feature_ref,
                            error_code="PIPELINE_HISTORY_INSUFFICIENT",
                            error_message=f"설비 '{asset_id}'의 관측 이력 부족 (요구치={min_req}, 실제={actual_count})",
                        )
                    )
                    continue

                # Extract latest feature vector for this equipment
                target_features = features_matrix[latest_idx : latest_idx + 1]

                # Perform inference
                try:
                    model_obj = artifact.model
                    if hasattr(model_obj, "predict_proba"):
                        probs = model_obj.predict_proba(target_features)
                        if probs.ndim == 2 and probs.shape[1] >= 2:
                            prob_val = float(probs[0, 1])
                        else:
                            prob_val = float(probs[0, 0])
                    elif hasattr(model_obj, "decision_function"):
                        df_val = float(model_obj.decision_function(target_features)[0])
                        prob_val = float(1.0 / (1.0 + np.exp(-df_val)))
                    elif hasattr(model_obj, "predict"):
                        preds = model_obj.predict(target_features)
                        prob_val = float(preds[0])
                    else:
                        raise PipelineModelPredictionFailedError(f"Model object has no predict method: {type(model_obj)}")

                    threshold = 0.5
                    is_anomaly = prob_val >= threshold
                    pred_label = "anomaly" if is_anomaly else "normal"

                    results.append(
                        ModelPredictionResult(
                            asset_id=asset_id,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            status="succeeded",
                            prediction=pred_label,
                            probability=prob_val,
                            threshold=threshold,
                            is_anomaly=is_anomaly,
                            predicted_at=now,
                            artifact_ref=artifact.artifact_ref,
                            feature_ref=feature_ref,
                            error_code=None,
                            error_message=None,
                        )
                    )
                    logger.info(
                        f"[PredictionService] Equipment '{asset_id}', Model '{model_id}' ({artifact.model_version}): "
                        f"prediction={pred_label}, prob={prob_val:.4f}"
                    )
                except Exception as exc:
                    err_code = getattr(exc, "code", "PIPELINE_MODEL_PREDICTION_FAILED")
                    logger.warning(f"[PredictionService] Model '{model_id}' prediction execution failed for asset '{asset_id}': {exc}")
                    results.append(
                        ModelPredictionResult(
                            asset_id=asset_id,
                            model_id=model_id,
                            model_version=artifact.model_version,
                            status="failed",
                            prediction="failed",
                            probability=None,
                            threshold=0.5,
                            is_anomaly=None,
                            predicted_at=now,
                            artifact_ref=artifact.artifact_ref,
                            feature_ref=feature_ref,
                            error_code=err_code,
                            error_message=str(exc),
                        )
                    )

        return results

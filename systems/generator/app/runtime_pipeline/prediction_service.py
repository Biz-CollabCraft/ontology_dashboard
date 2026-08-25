"""Service for executing multi-model predictions against active Model Artifacts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.model.publisher import ModelArtifactPublisher
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineModelArtifactInvalidError,
    PipelineNoActiveModelError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    ModelPredictionResult,
    now_utc_iso,
)
from systems.generator.app.runtime_pipeline.runtime_feature_service import (
    RuntimeFeatureBundle,
    RuntimeFeatureService,
)

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
    """Loads active Model Artifacts, extracts runtime features per model, and executes inference."""

    def __init__(
        self,
        models_store_dir: Optional[Path] = None,
        publisher: Optional[ModelArtifactPublisher] = None,
        feature_service: Optional[RuntimeFeatureService] = None,
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
        self.feature_service = feature_service or RuntimeFeatureService()

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
            )

        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                pointer_data = json.load(f)
        except Exception as exc:
            raise PipelineModelArtifactInvalidError(
                f"모델 '{model_id}'의 latest.json 파싱 실패: {exc}",
                details=[{"model_id": model_id, "error": str(exc)}],
            ) from exc

        model_version = pointer_data.get("model_version") or pointer_data.get("active_version")
        if not model_version:
            raise PipelineModelArtifactInvalidError(
                f"latest.json에 유효한 model_version이 없습니다 ({model_id})."
            )

        target_artifact_dir = self.artifacts_dir / model_id / model_version
        if not target_artifact_dir.is_dir():
            raise PipelineModelArtifactInvalidError(
                f"latest.json이 가리키는 아티팩트 디렉터리가 존재하지 않습니다: {target_artifact_dir}"
            )

        manifest_file = target_artifact_dir / "manifest.json"
        if not manifest_file.exists():
            raise PipelineModelArtifactInvalidError(f"manifest.json이 누락되었습니다: {manifest_file}")

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            self.publisher.validate_manifest(manifest_data, target_artifact_dir)
        except Exception as exc:
            raise PipelineModelArtifactInvalidError(
                f"아티팩트 manifest 검증 실패 ({model_id}/{model_version}): {exc}",
                details=[{"model_id": model_id, "model_version": model_version, "error": str(exc)}],
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
                f"아티팩트 페이로드 파일 로드 실패 ({model_id}/{model_version}): {exc}"
            ) from exc

        manifest_sha = compute_file_sha256(manifest_file)
        artifact_ref = ArtifactReference(
            uri=str(target_artifact_dir).replace("\\", "/"),
            sha256=manifest_sha,
            role="model_artifact",
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

    def execute_predictions(
        self,
        *,
        preprocessed_df: pd.DataFrame,
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
        target_models: Optional[list[str]] = None,
    ) -> list[ModelPredictionResult]:
        """Execute inference for all registered models with failure isolation."""
        models_to_run = target_models or REGISTERED_BASE_MODELS
        results: list[ModelPredictionResult] = []

        for base_model in models_to_run:
            model_id = self.resolve_model_id(base_model)
            now = now_utc_iso()

            # 1. Load active artifact
            try:
                artifact = self.load_active_artifact(base_model)
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_MODEL_ARTIFACT_INVALID")
                logger.warning(f"[PredictionService] Model '{model_id}' failed artifact load: {exc}")
                results.append(
                    ModelPredictionResult(
                        model_id=model_id,
                        model_version="unknown",
                        status="failed",
                        prediction="failed",
                        probability=None,
                        threshold=0.5,
                        is_anomaly=None,
                        predicted_at=now,
                        artifact_ref=None,
                        feature_ref=None,
                        error_code=err_code,
                        error_message=str(exc),
                    )
                )
                continue

            # 2. Extract runtime features matching this model's schema
            try:
                bundle, feat_ref = self.feature_service.extract_and_publish(
                    preprocessed_df=preprocessed_df,
                    feature_schema_dict=artifact.feature_schema,
                    history_requirement_dict=artifact.history_requirement,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                )
            except Exception as exc:
                err_code = getattr(exc, "code", "PIPELINE_RUNTIME_FEATURE_FAILED")
                logger.warning(f"[PredictionService] Model '{model_id}' failed feature extraction: {exc}")
                results.append(
                    ModelPredictionResult(
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
                        error_message=str(exc),
                    )
                )
                continue

            # 3. Model Inference
            try:
                X = bundle.features
                if hasattr(artifact.model, "predict_proba"):
                    probs = artifact.model.predict_proba(X)
                    if probs.ndim == 2 and probs.shape[1] >= 2:
                        prob = float(probs[-1, 1])
                    else:
                        prob = float(probs[-1])
                elif hasattr(artifact.model, "predict"):
                    preds = artifact.model.predict(X)
                    prob = float(preds[-1])
                else:
                    raise TypeError(f"Loaded model '{model_id}' has no predict or predict_proba method")

                threshold = 0.5
                is_anomaly = bool(prob >= threshold)
                pred_label = "anomaly" if is_anomaly else "normal"

                results.append(
                    ModelPredictionResult(
                        model_id=model_id,
                        model_version=artifact.model_version,
                        status="succeeded",
                        prediction=pred_label,
                        probability=round(prob, 4),
                        threshold=threshold,
                        is_anomaly=is_anomaly,
                        predicted_at=now,
                        artifact_ref=artifact.artifact_ref,
                        feature_ref=feat_ref,
                        error_code=None,
                        error_message=None,
                    )
                )
            except Exception as exc:
                logger.exception(f"[PredictionService] Model '{model_id}' inference failed: {exc}")
                results.append(
                    ModelPredictionResult(
                        model_id=model_id,
                        model_version=artifact.model_version,
                        status="failed",
                        prediction="failed",
                        probability=None,
                        threshold=0.5,
                        is_anomaly=None,
                        predicted_at=now,
                        artifact_ref=artifact.artifact_ref,
                        feature_ref=feat_ref,
                        error_code="PIPELINE_MODEL_PREDICTION_FAILED",
                        error_message=str(exc),
                    )
                )

        # Check if all models failed
        succeeded = [r for r in results if r.status == "succeeded"]
        if not succeeded:
            raise PipelineNoActiveModelError(
                "모든 활성 머신러닝 모델의 추론이 실패하였거나 로드할 수 없습니다.",
                details=[r.model_dump() for r in results],
            )

        return results

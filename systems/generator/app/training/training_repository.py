"""Repository for loading Feature Bundles and publishing Model Artifacts."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from systems.generator.generator_config import PATHS
from systems.generator.model.model_registry import (
    publish_model_artifact,
    validate_manifest,
    validate_model_artifact_directory,
)
from systems.generator.app.feature.feature_service import compute_feature_dataset_version
from systems.generator.app.training.training_exception import (
    FeatureDatasetNotFoundError,
    FeatureDatasetIntegrityError,
    InsufficientTrainingDataError,
    ModelArtifactConflictError,
    ModelArtifactPublishFailedError,
)

logger = logging.getLogger(__name__)


class TrainingRepository:
    """Repository handling feature bundle consumption and immutable model artifact publication."""

    def __init__(
        self,
        features_base_dir: Path | None = None,
        artifact_uri: str | Path | None = None,
    ) -> None:
        self._features_base_dir = features_base_dir
        self._artifact_uri = artifact_uri

    @property
    def features_base_dir(self) -> Path:
        if self._features_base_dir is not None:
            return self._features_base_dir.resolve()
        return (PATHS.models_store / "cache" / "features").resolve()

    @property
    def artifact_uri(self) -> str:
        if self._artifact_uri is not None:
            return str(self._artifact_uri)
        return os.environ.get("MODEL_ARTIFACT_URI") or str(PATHS.models_store / "artifacts")

    def find_feature_bundle_dir(self, feature_dataset_version: str) -> Path:
        """Locate feature bundle directory by version."""
        search_roots = [self.features_base_dir, (PATHS.data_preprocessed / "features").resolve()]
        for base in search_roots:
            if base.exists():
                candidates = [p for p in base.glob(f"**/*{feature_dataset_version}*") if p.is_dir()]
                if candidates:
                    return candidates[0].resolve()

        raise FeatureDatasetNotFoundError(
            f"Feature Dataset '{feature_dataset_version}'을 찾을 수 없습니다."
        )

    def load_feature_bundle(
        self, feature_dataset_version: str
    ) -> tuple[np.ndarray, np.ndarray, list[str], dict[str, Any], dict[str, Any] | None]:
        """Load and strictly validate all components of a Feature Bundle.

        Returns:
            (features_array, labels_array, feature_columns, metadata, row_metadata)
        """
        bundle_dir = self.find_feature_bundle_dir(feature_dataset_version)

        features_path = bundle_dir / "features.npy"
        labels_path = bundle_dir / "labels.npy"
        cols_path = bundle_dir / "feature_columns.json"
        meta_path = bundle_dir / "feature_metadata.json"
        row_meta_path = bundle_dir / "row_metadata.json"

        # 1. Check all 4 mandatory files exist
        for req_path in (features_path, labels_path, cols_path, meta_path):
            if not req_path.is_file():
                raise FeatureDatasetIntegrityError(
                    f"Feature Bundle 필수 파일이 누락되었습니다: {req_path.name}"
                )

        # 2. Parse JSON metadata
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"feature_metadata.json 파싱 실패: {exc}") from exc

        try:
            with open(cols_path, "r", encoding="utf-8") as f:
                feature_columns = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"feature_columns.json 파싱 실패: {exc}") from exc

        # 3. Load NPY arrays
        try:
            X = np.load(features_path, allow_pickle=False)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"features.npy 로드 실패: {exc}") from exc

        try:
            y = np.load(labels_path, allow_pickle=False)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"labels.npy 로드 실패: {exc}") from exc

        # 4. Strict dimensional and structural checks
        if X.ndim != 2:
            raise FeatureDatasetIntegrityError(f"features.npy는 2차원이어야 합니다 (현재: {X.ndim}D)")
        if y.ndim != 1:
            raise FeatureDatasetIntegrityError(f"labels.npy는 1차원이어야 합니다 (현재: {y.ndim}D)")
        if X.shape[0] != y.shape[0]:
            raise FeatureDatasetIntegrityError(
                f"Feature 행 수({X.shape[0]})와 Label 행 수({y.shape[0]})가 일치하지 않습니다."
            )
        if X.shape[1] != len(feature_columns):
            raise FeatureDatasetIntegrityError(
                f"Feature 열 수({X.shape[1]})와 feature_columns 수({len(feature_columns)})가 일치하지 않습니다."
            )

        # 5. Type and Value range checks
        if not np.issubdtype(X.dtype, np.floating):
            raise FeatureDatasetIntegrityError(f"features.npy dtype은 floating이어야 합니다 (현재: {X.dtype})")
        if not np.issubdtype(y.dtype, np.integer):
            raise FeatureDatasetIntegrityError(f"labels.npy dtype은 integer이어야 합니다 (현재: {y.dtype})")
        if not np.isfinite(X).all():
            raise FeatureDatasetIntegrityError("features.npy에 NaN 또는 무한대(Inf) 값이 포함되어 있습니다.")
        if not np.isfinite(y).all():
            raise FeatureDatasetIntegrityError("labels.npy에 NaN 또는 무한대(Inf) 값이 포함되어 있습니다.")

        unique_labels = set(np.unique(y))
        if not unique_labels.issubset({0, 1}):
            raise FeatureDatasetIntegrityError(f"labels.npy에 {0, 1} 이외의 라벨 값이 포함되어 있습니다: {unique_labels}")

        if len(unique_labels) < 2:
            raise InsufficientTrainingDataError(
                f"학습을 위해 Positive 및 Negative 표본이 모두 필요합니다 (현재 라벨 종류: {unique_labels})"
            )

        # 6. Metadata fingerprint validation
        expected_contract = metadata.get("contract")
        if not expected_contract or not isinstance(expected_contract, dict):
            raise FeatureDatasetIntegrityError("feature_metadata.json에 'contract' 항목이 누락되었습니다.")

        recalculated_version = compute_feature_dataset_version(**expected_contract)
        if recalculated_version != feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"Feature Dataset 지문 불일치: 요청={feature_dataset_version}, 계산={recalculated_version}"
            )

        # 7. Optional row metadata
        row_metadata = None
        if row_meta_path.is_file():
            try:
                with open(row_meta_path, "r", encoding="utf-8") as f:
                    row_metadata = json.load(f)
            except Exception:
                row_metadata = None

        return X, y, feature_columns, metadata, row_metadata

    def get_next_model_version(self, model_id: str) -> str:
        """Compute next immutable model version string for model_id."""
        local_root = self._resolve_local_artifact_root()
        model_dir = local_root / model_id
        if not model_dir.exists():
            return "v1"

        highest_v = 0
        for entry in model_dir.iterdir():
            if entry.is_dir() and entry.name.startswith("v"):
                try:
                    num = int(entry.name[1:])
                    highest_v = max(highest_v, num)
                except ValueError:
                    pass
        return f"v{highest_v + 1}"

    def publish_model_artifact(
        self,
        *,
        model_id: str,
        model_version: str,
        dataset_version: str,
        feature_schema_version: str,
        model_file: Path,
        feature_schema: dict[str, Any],
        training_config: dict[str, Any],
        metrics: dict[str, Any],
        provenance: dict[str, Any],
        compatibility: dict[str, Any],
        label_schema: dict[str, Any] | None = None,
        history_requirement: dict[str, Any] | None = None,
        prediction_contract: dict[str, Any] | None = None,
        model_runtime: dict[str, Any] | None = None,
        extra_files: dict[str, Path] | None = None,
    ) -> Path:
        """Atomically publish immutable Model Artifact package and validate it immediately."""
        local_root = self._resolve_local_artifact_root()
        target_dir = local_root / model_id / model_version
        if target_dir.exists():
            raise ModelArtifactConflictError(
                f"Model Artifact 버전이 이미 존재합니다: {model_id}/{model_version}"
            )

        try:
            artifact_path = publish_model_artifact(
                artifact_uri=self.artifact_uri,
                model_id=model_id,
                model_version=model_version,
                dataset_version=dataset_version,
                feature_schema_version=feature_schema_version,
                model_file=model_file,
                feature_schema=feature_schema,
                training_config=training_config,
                metrics=metrics,
                provenance=provenance,
                compatibility=compatibility,
                label_schema=label_schema,
                history_requirement=history_requirement,
                prediction_contract=prediction_contract,
                model_runtime=model_runtime,
                extra_files={k: str(v) for k, v in (extra_files or {}).items()},
            )
            # Validate output package
            validate_model_artifact_directory(artifact_path)
            return artifact_path
        except FileExistsError as exc:
            raise ModelArtifactConflictError(str(exc)) from exc
        except Exception as exc:
            logger.exception(f"[TrainingRepository] Failed to publish Model Artifact: {exc}")
            raise ModelArtifactPublishFailedError(f"Model Artifact 발행 실패: {exc}") from exc

    def _resolve_local_artifact_root(self) -> Path:
        text = str(self.artifact_uri)
        if text.startswith("file://"):
            return Path(text[7:]).expanduser().resolve()
        if "://" in text:
            raise ValueError("Local filesystem URI only supported.")
        return Path(text).expanduser().resolve()

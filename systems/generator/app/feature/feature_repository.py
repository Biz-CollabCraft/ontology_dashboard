"""Repository for versioned Feature, Label, and NPY storage with atomic publishing."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional
import numpy as np

from systems.generator.generator_config import PATHS
from systems.generator.app.feature.feature_exception import (
    NpyValidationError,
    NpyPublishError,
)

logger = logging.getLogger(__name__)


class FeatureRepository:
    """Manages versioned storage and atomic publishing for Feature, Label, and NPY artifacts."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._custom_base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base_dir is not None:
            return self._custom_base_dir
        return PATHS.models_store / "cache" / "features"

    def _feature_dirname(self, dataset_id: str, dataset_version: str, feature_dataset_version: str) -> str:
        safe_id = dataset_id.replace("/", "_").replace("\\", "_")
        safe_ver = dataset_version.replace("/", "_").replace("\\", "_")
        safe_fver = feature_dataset_version.replace("/", "_").replace("\\", "_")
        return f"{safe_id}-{safe_ver}-{safe_fver}"

    def get_feature_dir(self, dataset_id: str, dataset_version: str, feature_dataset_version: str) -> Path:
        return self.base_dir / self._feature_dirname(dataset_id, dataset_version, feature_dataset_version)

    def find_feature_outputs(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
    ) -> Optional[dict[str, Any]]:
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)
        meta_path = target_dir / "feature_metadata.json"
        if target_dir.exists() and meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning(f"[FeatureRepository] Failed to read metadata at {meta_path}: {exc}")
        return None

    def publish_feature_bundle(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        metadata: dict[str, Any],
        overwrite: bool = False,
    ) -> dict[str, str]:
        """Atomically stage, validate, and publish NPY arrays and metadata."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)

        if target_dir.exists() and not overwrite:
            logger.info(f"[FeatureRepository] Target feature directory {target_dir} exists, reusing without overwrite.")
            return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)

        # 1. Validation before staging
        if X.ndim != 2:
            raise NpyValidationError(f"X matrix must be 2-dimensional, got shape {X.shape}")
        if y.ndim != 1:
            raise NpyValidationError(f"y label array must be 1-dimensional, got shape {y.shape}")
        if X.shape[0] != y.shape[0]:
            raise NpyValidationError(f"X row count ({X.shape[0]}) does not match y count ({y.shape[0]})")
        if X.shape[1] != len(feature_names):
            raise NpyValidationError(f"X column count ({X.shape[1]}) does not match feature_names count ({len(feature_names)})")
        if not np.isfinite(X).all():
            raise NpyValidationError("X matrix contains NaN or Infinite values")
        if X.shape[0] == 0:
            raise NpyValidationError("Cannot publish empty feature dataset (row_count=0)")

        # 2. Stage in temp directory
        temp_dir = self.base_dir / f".tmp_{uuid.uuid4().hex}_{self._feature_dirname(dataset_id, dataset_version, feature_dataset_version)}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            np.save(temp_dir / "features.npy", X.astype(np.float64), allow_pickle=False)
            np.save(temp_dir / "labels.npy", y.astype(np.int64), allow_pickle=False)

            with open(temp_dir / "feature_columns.json", "w", encoding="utf-8") as f:
                json.dump(feature_names, f, ensure_ascii=False, indent=2)

            with open(temp_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            # 3. Atomic replace/rename
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)

            temp_dir.replace(target_dir)
            logger.info(f"[FeatureRepository] Atomically published feature outputs to {target_dir}")
            return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)

        except Exception as exc:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            logger.exception(f"[FeatureRepository] Failed to publish feature bundle: {exc}")
            raise NpyPublishError(f"Feature NPY 산출물 저장에 실패했습니다: {exc}") from exc

    def _build_logical_uris(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
    ) -> dict[str, str]:
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)
        try:
            repo_root = PATHS.models_store.parent
            rel_dir = str(target_dir.relative_to(repo_root).as_posix())
        except Exception:
            rel_dir = f"models_store/cache/features/{self._feature_dirname(dataset_id, dataset_version, feature_dataset_version)}"

        return {
            "features_uri": f"{rel_dir}/features.npy",
            "labels_uri": f"{rel_dir}/labels.npy",
            "metadata_uri": f"{rel_dir}/feature_metadata.json",
        }

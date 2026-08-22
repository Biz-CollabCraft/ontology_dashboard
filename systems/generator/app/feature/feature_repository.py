"""Repository for immutable Feature Dataset Bundle storage and atomic publishing."""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as np

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.feature.feature_exception import (
    FeatureContractError,
    FeatureDatasetIntegrityError,
    FeaturePublishConflictError,
    FeaturePublishError,
)

logger = logging.getLogger(__name__)


class FeatureRepository:
    """Manages versioned immutable Feature Dataset Bundles (5 essential files) with atomic publishing."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or (PATHS.models_store / "cache" / "features")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _safe_segment(self, segment: str) -> str:
        return segment.replace("/", "_").replace("\\", "_").replace("..", "_").replace(":", "_")

    def get_feature_dir(self, dataset_id: str, dataset_version: str, feature_dataset_version: str) -> Path:
        return (
            self.base_dir
            / self._safe_segment(dataset_id)
            / self._safe_segment(dataset_version)
            / self._safe_segment(feature_dataset_version)
        )

    def validate_feature_bundle(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        expected_inputs: Optional[dict[str, Any]] = None,
        expected_horizon: Optional[int] = None,
    ) -> dict[str, Any]:
        """Validate integrity and immutability of an existing Feature Dataset Bundle."""
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)
        if not target_dir.exists() or not target_dir.is_dir():
            raise FeatureDatasetIntegrityError(
                f"Feature Dataset 디렉터리가 존재하지 않습니다: {target_dir}",
                code="FEATURE_DATASET_NOT_FOUND",
            )

        features_file = target_dir / "features.npy"
        labels_file = target_dir / "labels.npy"
        cols_file = target_dir / "feature_columns.json"
        row_meta_file = target_dir / "row_metadata.json"
        meta_file = target_dir / "feature_metadata.json"

        # 1. Check all 5 essential files exist
        missing_files = []
        for file_path in [features_file, labels_file, cols_file, row_meta_file, meta_file]:
            if not file_path.is_file():
                missing_files.append(file_path.name)
        if missing_files:
            raise FeatureDatasetIntegrityError(
                f"Feature Dataset Bundle 필수 파일이 누락되었습니다: {missing_files}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 2. Parse feature_metadata.json
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"feature_metadata.json 파일 파싱 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        # 3. Verify checksums of the 4 payload files
        artifact_files = metadata.get("artifact_files", [])
        checksum_map = {a.get("role"): a.get("sha256") for a in artifact_files if isinstance(a, dict)}

        for file_path, role in [
            (features_file, "features"),
            (labels_file, "labels"),
            (cols_file, "feature_columns"),
            (row_meta_file, "row_metadata"),
        ]:
            expected_sha = checksum_map.get(role)
            if not expected_sha:
                raise FeatureDatasetIntegrityError(
                    f"feature_metadata.json에 '{role}' 파일의 SHA-256 체크섬이 정의되지 않았습니다.",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )
            actual_sha = compute_file_sha256(file_path)
            if actual_sha != expected_sha:
                raise FeatureDatasetIntegrityError(
                    f"{role} 파일의 SHA-256 체크섬 불일치 (기록: {expected_sha}, 실제: {actual_sha})",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 4. Load and verify columns and row metadata
        try:
            with open(cols_file, "r", encoding="utf-8") as f:
                cols = json.load(f)
            with open(row_meta_file, "r", encoding="utf-8") as f:
                row_meta = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"JSON 파일 파싱 실패: {exc}") from exc

        if not isinstance(cols, list) or not isinstance(row_meta, list):
            raise FeatureDatasetIntegrityError("feature_columns.json 또는 row_metadata.json 형식이 잘못되었습니다.")

        # 5. Load and verify arrays
        try:
            X = np.load(features_file, allow_pickle=False)
            y = np.load(labels_file, allow_pickle=False)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"NPY 배열 로드 실패 (allow_pickle=False): {exc}") from exc

        if X.ndim != 2 or y.ndim != 1:
            raise FeatureDatasetIntegrityError(f"NPY 차원 불일치: X.shape={X.shape}, y.shape={y.shape}")
        if X.shape[0] != y.shape[0] or X.shape[0] != len(row_meta):
            raise FeatureDatasetIntegrityError(
                f"행 수 불일치: X={X.shape[0]}, y={y.shape[0]}, row_metadata={len(row_meta)}"
            )
        if X.shape[1] != len(cols):
            raise FeatureDatasetIntegrityError(
                f"열 수 불일치: X={X.shape[1]}, feature_columns={len(cols)}"
            )
        if not np.isfinite(X).all() or not np.isfinite(y).all():
            raise FeatureDatasetIntegrityError("NPY 배열에 NaN 또는 Inf가 포함되어 있습니다.")
        if not set(np.unique(y)).issubset({0, 1}):
            raise FeatureDatasetIntegrityError(f"labels.npy에 {{0, 1}} 이외의 값이 포함되어 있습니다: {np.unique(y)}")

        # 6. Verify inputs and contract if provided
        if expected_inputs is not None:
            actual_inputs = metadata.get("inputs", {})
            if actual_inputs != expected_inputs:
                raise FeaturePublishConflictError(
                    f"기존 Feature Dataset의 inputs({actual_inputs})가 현재 요청의 inputs({expected_inputs})와 일치하지 않습니다.",
                )

        if expected_horizon is not None:
            actual_horizon = metadata.get("prediction_contract", {}).get("prediction_horizon_hours")
            if actual_horizon != expected_horizon:
                raise FeaturePublishConflictError(
                    f"기존 Feature Dataset의 horizon({actual_horizon})이 요청 horizon({expected_horizon})과 일치하지 않습니다.",
                )

        if metadata.get("feature_dataset_version") != feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"feature_metadata.json의 버전('{metadata.get('feature_dataset_version')}')이 경로 버전('{feature_dataset_version}')과 일치하지 않습니다."
            )

        return metadata

    def find_feature_bundle(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        expected_inputs: Optional[dict[str, Any]] = None,
        expected_horizon: Optional[int] = None,
    ) -> Optional[dict[str, Any]]:
        """Find and return existing Feature Dataset metadata if valid. Raises FeatureDatasetIntegrityError if corrupted."""
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)
        if not target_dir.exists() or not target_dir.is_dir():
            return None
        return self.validate_feature_bundle(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            feature_dataset_version=feature_dataset_version,
            expected_inputs=expected_inputs,
            expected_horizon=expected_horizon,
        )

    def publish_feature_bundle(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: list[str],
        row_metadata: list[dict[str, Any]],
        inputs_metadata: dict[str, Any],
        prediction_contract: dict[str, Any],
        run_id: str,
        created_at: str,
    ) -> dict[str, str]:
        """Atomically stage, write, checksum, validate, and publish the 5 essential bundle files."""
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)

        # 1. In-memory validation
        if X.ndim != 2:
            raise FeatureContractError(f"Feature 행렬 X는 2차원이어야 합니다. (shape: {X.shape})")
        if y.ndim != 1:
            raise FeatureContractError(f"라벨 배열 y는 1차원이어야 합니다. (shape: {y.shape})")
        if X.shape[0] != y.shape[0]:
            raise FeatureContractError(f"X 행 수({X.shape[0]})와 y 행 수({y.shape[0]})가 일치하지 않습니다.")
        if X.shape[0] != len(row_metadata):
            raise FeatureContractError(f"X 행 수({X.shape[0]})와 row_metadata 행 수({len(row_metadata)})가 일치하지 않습니다.")
        if X.shape[1] != len(feature_names):
            raise FeatureContractError(f"X 컬럼 수({X.shape[1]})와 feature_names 수({len(feature_names)})가 일치하지 않습니다.")
        if X.shape[0] == 0:
            raise FeatureContractError("빈 Feature Dataset (row_count=0)은 발행할 수 없습니다.")
        if not np.isfinite(X).all():
            raise FeatureContractError("X 행렬에 NaN 또는 Inf 값이 포함되어 있습니다.")
        if not np.isfinite(y).all():
            raise FeatureContractError("y 라벨 배열에 NaN 또는 Inf 값이 포함되어 있습니다.")
        if not set(np.unique(y)).issubset({0, 1}):
            raise FeatureContractError(f"y 라벨 배열에 {{0, 1}} 이외의 값이 포함되어 있습니다: {np.unique(y)}")

        # 2. Immutable existence check: never blindly overwrite!
        if target_dir.exists():
            self.validate_feature_bundle(
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                feature_dataset_version=feature_dataset_version,
                expected_inputs=inputs_metadata,
                expected_horizon=prediction_contract.get("prediction_horizon_hours"),
            )
            logger.info(f"[FeatureRepository] Target feature directory {target_dir} exists and verified. Reusing.")
            return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)

        target_dir.parent.mkdir(parents=True, exist_ok=True)

        # 3. Stage in temp directory on same filesystem
        temp_dir = target_dir.parent / f".tmp_{uuid.uuid4().hex}_{self._safe_segment(feature_dataset_version)}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            features_file = temp_dir / "features.npy"
            labels_file = temp_dir / "labels.npy"
            cols_file = temp_dir / "feature_columns.json"
            row_meta_file = temp_dir / "row_metadata.json"
            meta_file = temp_dir / "feature_metadata.json"

            # 4. Write 4 payload files
            np.save(features_file, X.astype(np.float64), allow_pickle=False)
            np.save(labels_file, y.astype(np.int64), allow_pickle=False)

            with open(cols_file, "w", encoding="utf-8") as f:
                json.dump(feature_names, f, ensure_ascii=False, indent=2)

            with open(row_meta_file, "w", encoding="utf-8") as f:
                json.dump(row_metadata, f, ensure_ascii=False, indent=2)

            # 5. Compute SHA-256 of the 4 payload files
            features_sha = compute_file_sha256(features_file)
            labels_sha = compute_file_sha256(labels_file)
            cols_sha = compute_file_sha256(cols_file)
            row_meta_sha = compute_file_sha256(row_meta_file)

            positive_count = int(np.sum(y == 1))
            negative_count = int(np.sum(y == 0))

            # 6. Construct feature_metadata.json (strictly without self-referential checksum!)
            metadata = {
                "feature_dataset_version": feature_dataset_version,
                "created_at": created_at,
                "run_id": run_id,
                "inputs": inputs_metadata,
                "prediction_contract": prediction_contract,
                "shape": {
                    "row_count": int(X.shape[0]),
                    "feature_count": int(X.shape[1]),
                },
                "label_summary": {
                    "negative_count": negative_count,
                    "positive_count": positive_count,
                },
                "artifact_files": [
                    {
                        "role": "features",
                        "path": "features.npy",
                        "sha256": features_sha,
                    },
                    {
                        "role": "labels",
                        "path": "labels.npy",
                        "sha256": labels_sha,
                    },
                    {
                        "role": "feature_columns",
                        "path": "feature_columns.json",
                        "sha256": cols_sha,
                    },
                    {
                        "role": "row_metadata",
                        "path": "row_metadata.json",
                        "sha256": row_meta_sha,
                    },
                ],
            }

            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            # 7. Post-write validation of staged files
            X_read = np.load(features_file, allow_pickle=False)
            y_read = np.load(labels_file, allow_pickle=False)
            if X_read.shape != (X.shape[0], X.shape[1]):
                raise FeatureDatasetIntegrityError(f"Written X shape {X_read.shape} != original {X.shape}")
            if y_read.shape != (y.shape[0],):
                raise FeatureDatasetIntegrityError(f"Written y shape {y_read.shape} != original {y.shape}")

            # 8. Atomic publish with race-condition collision protection
            try:
                temp_dir.replace(target_dir)
                logger.info(f"[FeatureRepository] Atomically published Feature Dataset Bundle to {target_dir}")
                return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)
            except Exception as replace_exc:
                if target_dir.exists():
                    self.validate_feature_bundle(
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        feature_dataset_version=feature_dataset_version,
                        expected_inputs=inputs_metadata,
                        expected_horizon=prediction_contract.get("prediction_horizon_hours"),
                    )
                    logger.info(f"[FeatureRepository] Concurrent publish detected: validated and reused existing bundle at {target_dir}")
                    return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)
                raise replace_exc

        except Exception as exc:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, (FeatureContractError, FeatureDatasetIntegrityError, FeaturePublishConflictError)):
                raise
            logger.exception(f"[FeatureRepository] Failed to publish Feature Dataset Bundle: {exc}")
            raise FeaturePublishError(f"Feature Dataset Bundle 발행에 실패했습니다: {exc}") from exc

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
            rel_dir = (
                f"models_store/cache/features/{self._safe_segment(dataset_id)}/"
                f"{self._safe_segment(dataset_version)}/{self._safe_segment(feature_dataset_version)}"
            )

        return {
            "features_uri": f"{rel_dir}/features.npy",
            "labels_uri": f"{rel_dir}/labels.npy",
            "metadata_uri": f"{rel_dir}/feature_metadata.json",
        }

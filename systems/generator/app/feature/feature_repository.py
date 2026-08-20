"""Repository for immutable versioned Feature, Label, and NPY storage with containment safety."""

from __future__ import annotations

import hashlib
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
    FeatureConflictError,
    FeatureDatasetIntegrityError,
)

logger = logging.getLogger(__name__)


def compute_file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class FeatureRepository:
    """Manages immutable versioned storage and atomic publishing for Feature, Label, and NPY artifacts."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._custom_base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base_dir is not None:
            return self._custom_base_dir
        return PATHS.models_store / "cache" / "features"

    def _feature_dirname(self, dataset_id: str, dataset_version: str, feature_dataset_version: str) -> str:
        if ".." in dataset_id or "/" in dataset_id or "\\" in dataset_id:
            raise NpyValidationError(f"잘못된 dataset_id 식별자입니다: {dataset_id!r}", code="INVALID_ARTIFACT_PATH")
        if ".." in dataset_version or "/" in dataset_version or "\\" in dataset_version:
            raise NpyValidationError(f"잘못된 dataset_version 식별자입니다: {dataset_version!r}", code="INVALID_ARTIFACT_PATH")
        if ".." in feature_dataset_version or "/" in feature_dataset_version or "\\" in feature_dataset_version:
            raise NpyValidationError(f"잘못된 feature_dataset_version 식별자입니다: {feature_dataset_version!r}", code="INVALID_ARTIFACT_PATH")

        safe_id = dataset_id.replace("/", "_").replace("\\", "_")
        safe_ver = dataset_version.replace("/", "_").replace("\\", "_")
        safe_fver = feature_dataset_version.replace("/", "_").replace("\\", "_")
        return f"{safe_id}-{safe_ver}-{safe_fver}"

    def get_feature_dir(self, dataset_id: str, dataset_version: str, feature_dataset_version: str) -> Path:
        base = self.base_dir.resolve()
        dirname = self._feature_dirname(dataset_id, dataset_version, feature_dataset_version)
        target = (self.base_dir / dirname).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise NpyValidationError(
                f"Feature 저장 디렉터리가 루트 디렉터리를 벗어납니다: {target}",
                code="INVALID_ARTIFACT_PATH",
            ) from exc
        return target

    def validate_feature_bundle(
        self,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        expected_contract: dict[str, Any],
    ) -> dict[str, Any]:
        """Strictly validate the complete integrity of an existing feature bundle before reuse."""
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)
        if not target_dir.exists():
            raise FeatureDatasetIntegrityError(
                f"Feature Dataset 디렉터리가 존재하지 않습니다: {target_dir}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        features_path = target_dir / "features.npy"
        labels_path = target_dir / "labels.npy"
        cols_path = target_dir / "feature_columns.json"
        meta_path = target_dir / "feature_metadata.json"

        # 1. Check all 4 required files exist
        for required_path in (features_path, labels_path, cols_path, meta_path):
            if not required_path.is_file():
                raise FeatureDatasetIntegrityError(
                    f"Feature Bundle 필수 파일이 누락되었습니다: {required_path.name}",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 2. Check metadata parseable
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"feature_metadata.json 파싱 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        # 2.1 Check mandatory metadata fields
        mandatory_fields = [
            "feature_dataset_version",
            "dataset_id",
            "dataset_version",
            "feature_schema_version",
            "label_schema_version",
            "prediction_horizon_hours",
            "contract",
            "checksum",
        ]
        for field_name in mandatory_fields:
            if field_name not in metadata:
                raise FeatureDatasetIntegrityError(
                    f"feature_metadata.json에 필수 필드가 누락되었습니다: '{field_name}'",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 2.2 SHA-256 Checksum validation
        checksum_info = metadata["checksum"]
        if not isinstance(checksum_info, dict) or checksum_info.get("algorithm") != "sha256":
            raise FeatureDatasetIntegrityError(
                "feature_metadata.json에 유효한 SHA-256 체크섬 정보가 누락되었습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        declared_files = checksum_info.get("files", {})
        if not declared_files or not isinstance(declared_files, dict):
            raise FeatureDatasetIntegrityError(
                "체크섬 파일 목록이 비어 있거나 올바른 형식이 아닙니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        for req_name in ("features.npy", "labels.npy", "feature_columns.json"):
            if req_name not in declared_files:
                raise FeatureDatasetIntegrityError(
                    f"필수 파일 '{req_name}'의 체크섬이 선언되지 않았습니다.",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )
        for fname, expected_hash in declared_files.items():
            fpath = target_dir / fname
            if not fpath.is_file():
                raise FeatureDatasetIntegrityError(
                    f"체크섬 검증 대상 파일 '{fname}'이 존재하지 않습니다.",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )
            actual_hash = compute_file_sha256(fpath)
            if actual_hash != expected_hash:
                raise FeatureDatasetIntegrityError(
                    f"파일 '{fname}'의 SHA-256 체크섬이 일치하지 않습니다 (선언={expected_hash}, 실제={actual_hash}).",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 3. Check columns parseable
        try:
            with open(cols_path, "r", encoding="utf-8") as f:
                feature_columns = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"feature_columns.json 파싱 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        if not isinstance(feature_columns, list) or not feature_columns:
            raise FeatureDatasetIntegrityError(
                "feature_columns.json이 비어 있거나 올바른 리스트 형식이 아닙니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 4. Check NPY files loadable
        try:
            X = np.load(features_path, allow_pickle=False)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"features.npy 로드 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        try:
            y = np.load(labels_path, allow_pickle=False)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"labels.npy 로드 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        # 5. Dimension and shape checks
        if X.ndim != 2:
            raise FeatureDatasetIntegrityError(
                f"features.npy는 2차원 행렬이어야 합니다 (현재: {X.ndim}D, shape={X.shape}).",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if y.ndim != 1:
            raise FeatureDatasetIntegrityError(
                f"labels.npy는 1차원 배열이어야 합니다 (현재: {y.ndim}D, shape={y.shape}).",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if X.shape[0] != y.shape[0]:
            raise FeatureDatasetIntegrityError(
                f"X 행 수({X.shape[0]})와 y 행 수({y.shape[0]})가 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if X.shape[1] != len(feature_columns):
            raise FeatureDatasetIntegrityError(
                f"X 열 수({X.shape[1]})와 feature_columns 수({len(feature_columns)})가 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 6. Feature names order and metadata match
        if metadata.get("feature_columns") != feature_columns:
            raise FeatureDatasetIntegrityError(
                "feature_columns.json과 feature_metadata.json의 feature_columns 목록/순서가 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if metadata.get("row_count") != X.shape[0]:
            raise FeatureDatasetIntegrityError(
                f"metadata row_count({metadata.get('row_count')})가 실제 X 행 수({X.shape[0]})와 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if metadata.get("feature_count") != X.shape[1]:
            raise FeatureDatasetIntegrityError(
                f"metadata feature_count({metadata.get('feature_count')})가 실제 X 열 수({X.shape[1]})와 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 7. Dtype checks
        if not np.issubdtype(X.dtype, np.floating):
            raise FeatureDatasetIntegrityError(
                f"features.npy의 dtype({X.dtype})이 부동소수점 형식이 아닙니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if not np.issubdtype(y.dtype, np.integer):
            raise FeatureDatasetIntegrityError(
                f"labels.npy의 dtype({y.dtype})이 정수 형식이 아닙니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 8. NaN / Inf / value checks
        if not np.isfinite(X).all():
            raise FeatureDatasetIntegrityError(
                "features.npy에 NaN 또는 무한대(Inf) 값이 포함되어 있습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if not np.isfinite(y).all():
            raise FeatureDatasetIntegrityError(
                "labels.npy에 NaN 또는 무한대(Inf) 값이 포함되어 있습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if not set(np.unique(y)).issubset({0, 1}):
            raise FeatureDatasetIntegrityError(
                f"labels.npy에 {{0, 1}} 이외의 라벨 값이 포함되어 있습니다: {np.unique(y)}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 9. Contract and version matches
        if metadata.get("contract") != expected_contract:
            raise FeatureDatasetIntegrityError(
                "feature_metadata.json의 계약이 요청 계약과 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if metadata.get("feature_dataset_version") != feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"feature_metadata.json의 버전('{metadata.get('feature_dataset_version')}')이 경로 버전('{feature_dataset_version}')과 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 10. Recalculate fingerprint from expected_contract
        canonical_json = json.dumps(expected_contract, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        expected_ver = f"feature-dataset-{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()[:16]}"
        if expected_ver != feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"요청 계약으로 재계산한 버전('{expected_ver}')이 feature_dataset_version('{feature_dataset_version}')과 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        return metadata

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
        row_metadata: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Atomically stage, validate, and publish NPY arrays and metadata into immutable directory."""
        target_dir = self.get_feature_dir(dataset_id, dataset_version, feature_dataset_version)

        # 1. Pre-staging in-memory validation
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
        if not np.isfinite(y).all():
            raise NpyValidationError("y label array contains NaN or Infinite values")
        if not set(np.unique(y)).issubset({0, 1}):
            raise NpyValidationError(f"y label array contains invalid values outside {{0, 1}}: {np.unique(y)}")
        if X.shape[0] == 0:
            raise NpyValidationError("Cannot publish empty feature dataset (row_count=0)")

        # 2. Immutable existence check with full validation before reuse: never overwrite!
        if target_dir.exists():
            self.validate_feature_bundle(
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                feature_dataset_version=feature_dataset_version,
                expected_contract=metadata.get("contract", {}),
            )
            logger.info(f"[FeatureRepository] Target feature directory {target_dir} verified and exists with exact contract match, returning existing bundle.")
            return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)

        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 3. Stage in temp directory
        temp_dir = self.base_dir / f".tmp_{uuid.uuid4().hex}_{self._feature_dirname(dataset_id, dataset_version, feature_dataset_version)}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            features_file = temp_dir / "features.npy"
            labels_file = temp_dir / "labels.npy"
            cols_file = temp_dir / "feature_columns.json"
            meta_file = temp_dir / "feature_metadata.json"

            np.save(features_file, X.astype(np.float64), allow_pickle=False)
            np.save(labels_file, y.astype(np.int64), allow_pickle=False)

            with open(cols_file, "w", encoding="utf-8") as f:
                json.dump(feature_names, f, ensure_ascii=False, indent=2)

            checksum_files = {
                "features.npy": compute_file_sha256(features_file),
                "labels.npy": compute_file_sha256(labels_file),
                "feature_columns.json": compute_file_sha256(cols_file),
            }

            if row_metadata is not None:
                row_meta_file = temp_dir / "row_metadata.json"
                with open(row_meta_file, "w", encoding="utf-8") as f:
                    json.dump(row_metadata, f, ensure_ascii=False, indent=2)
                checksum_files["row_metadata.json"] = compute_file_sha256(row_meta_file)

            metadata["checksum"] = {
                "algorithm": "sha256",
                "files": checksum_files,
            }

            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

            # 4. Post-write disk validation
            X_read = np.load(features_file, allow_pickle=False)
            y_read = np.load(labels_file, allow_pickle=False)

            if X_read.shape != (metadata["row_count"], metadata["feature_count"]):
                raise NpyValidationError(f"Saved features.npy shape {X_read.shape} does not match metadata {metadata['row_count']}x{metadata['feature_count']}")
            if y_read.shape != (metadata["row_count"],):
                raise NpyValidationError(f"Saved labels.npy shape {y_read.shape} does not match metadata row_count {metadata['row_count']}")
            if X_read.dtype != np.float64 or y_read.dtype != np.int64:
                raise NpyValidationError(f"Saved dtypes invalid (X: {X_read.dtype}, y: {y_read.dtype})")

            # 5. Atomic publish (atomic rename without prior rmtree)
            temp_dir.replace(target_dir)
            logger.info(f"[FeatureRepository] Atomically published immutable feature outputs to {target_dir}")
            return self._build_logical_uris(dataset_id, dataset_version, feature_dataset_version)

        except Exception as exc:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            if isinstance(exc, (NpyValidationError, FeatureConflictError, FeatureDatasetIntegrityError)):
                raise
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

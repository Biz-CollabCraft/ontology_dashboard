"""Repository for loading Feature Bundles and publishing Model Artifacts."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
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
    ModelArtifactNotFoundError,
    ModelArtifactIntegrityError,
    ActiveModelNotFoundError,
)

logger = logging.getLogger(__name__)


ALLOWED_FEATURE_BUNDLE_FILES = {
    "features.npy",
    "labels.npy",
    "feature_columns.json",
    "row_metadata.json",
}


def compute_file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    import hashlib
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


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
        """Locate feature bundle directory strictly matching feature_dataset_version within allowed roots."""
        if not feature_dataset_version or ".." in feature_dataset_version or "/" in feature_dataset_version or "\\" in feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"유효하지 않은 feature_dataset_version 식별자입니다: {feature_dataset_version!r}",
                code="INVALID_ARTIFACT_PATH",
            )

        search_roots = [self.features_base_dir, (PATHS.data_preprocessed / "features").resolve()]
        matching_dirs: list[Path] = []
        seen_dirs: set[Path] = set()

        for root in search_roots:
            if not root.exists():
                continue
            resolved_root = root.resolve()
            for candidate in resolved_root.iterdir():
                if not candidate.is_dir():
                    continue
                # Ensure path is strictly contained within root (no symlink escape)
                resolved_candidate = candidate.resolve()
                try:
                    resolved_candidate.relative_to(resolved_root)
                except ValueError:
                    continue

                meta_file = resolved_candidate / "feature_metadata.json"
                if not meta_file.is_file():
                    continue
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if meta.get("feature_dataset_version") == feature_dataset_version:
                        if resolved_candidate not in seen_dirs:
                            seen_dirs.add(resolved_candidate)
                            matching_dirs.append(resolved_candidate)
                except Exception:
                    continue

        if not matching_dirs:
            raise FeatureDatasetNotFoundError(
                f"Feature Dataset '{feature_dataset_version}'을 찾을 수 없습니다."
            )
        if len(matching_dirs) > 1:
            raise FeatureDatasetIntegrityError(
                f"동일한 Feature Dataset 버전({feature_dataset_version})을 가진 복수의 디렉터리가 발견되었습니다: {[str(p) for p in matching_dirs]}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        return matching_dirs[0]

    def load_feature_bundle(
        self, feature_dataset_version: str
    ) -> tuple[np.ndarray, np.ndarray, list[str], dict[str, Any], dict[str, Any] | None]:
        """Load and strictly validate all components and checksums of a Feature Bundle.

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
                    f"Feature Bundle 필수 파일이 누락되었습니다: {req_path.name}",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 2. Parse JSON metadata
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as exc:
            raise FeatureDatasetIntegrityError(
                f"feature_metadata.json 파싱 실패: {exc}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            ) from exc

        # 2.1 Check mandatory metadata fields without fallback
        mandatory_fields = [
            "feature_dataset_version",
            "dataset_id",
            "dataset_version",
            "feature_schema_version",
            "label_schema_version",
            "prediction_horizon_hours",
            "contract",
            "checksum",
            "split_indices",
        ]
        for field_name in mandatory_fields:
            if field_name not in metadata:
                raise FeatureDatasetIntegrityError(
                    f"feature_metadata.json에 필수 필드가 누락되었습니다: '{field_name}'",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        # 2.2 Validate split_indices completeness
        split_indices = metadata["split_indices"]
        if not isinstance(split_indices, dict) or not all(k in split_indices for k in ("train", "val", "test")):
            raise FeatureDatasetIntegrityError(
                "feature_metadata.json의 split_indices 구조가 유효하지 않습니다 (train/val/test 필수).",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 2.3 Check row_metadata.json existence and integrity
        if not row_meta_path.is_file():
            raise FeatureDatasetIntegrityError(
                "Feature Bundle 필수 파일인 row_metadata.json이 존재하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        try:
            with open(row_meta_path, "r", encoding="utf-8") as f:
                row_metadata = json.load(f)
            if not isinstance(row_metadata, dict) or "asset_ids" not in row_metadata or "timestamps" not in row_metadata:
                raise FeatureDatasetIntegrityError(
                    "row_metadata.json에 asset_ids 또는 timestamps가 누락되었습니다.",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )
        except FeatureDatasetIntegrityError:
            raise
        except Exception as exc:
            raise FeatureDatasetIntegrityError(f"row_metadata.json 파싱 실패: {exc}", code="FEATURE_DATASET_INTEGRITY_ERROR") from exc

        # 2.4 SHA-256 Checksum validation with path containment and allowlist
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

        for req_name in ("features.npy", "labels.npy", "feature_columns.json", "row_metadata.json"):
            if req_name not in declared_files:
                raise FeatureDatasetIntegrityError(
                    f"필수 파일 '{req_name}'의 체크섬이 선언되지 않았습니다.",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

        bundle_dir_resolved = bundle_dir.resolve()
        for fname, expected_hash in declared_files.items():
            if not isinstance(fname, str) or not fname:
                raise FeatureDatasetIntegrityError("체크섬 파일 이름이 올바르지 않습니다.", code="FEATURE_DATASET_INTEGRITY_ERROR")

            # Check rules: no absolute path, no .., no slashes, must be in allowlist
            if Path(fname).is_absolute() or ".." in fname or "/" in fname or "\\" in fname:
                raise FeatureDatasetIntegrityError(
                    f"체크섬 파일 경로에 유효하지 않은 문자나 상위/하위 경로가 포함되어 있습니다: {fname!r}",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )
            if fname not in ALLOWED_FEATURE_BUNDLE_FILES:
                raise FeatureDatasetIntegrityError(
                    f"허용되지 않은 체크섬 대상 파일명입니다: {fname!r}",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

            fpath = (bundle_dir / fname).resolve()
            try:
                fpath.relative_to(bundle_dir_resolved)
            except ValueError:
                raise FeatureDatasetIntegrityError(
                    f"체크섬 파일 경로가 번들 루트를 벗어납니다: {fname!r}",
                    code="FEATURE_DATASET_INTEGRITY_ERROR",
                )

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

        # 3. Load NPY arrays
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

        # 4. Strict dimensional and structural checks
        if X.ndim != 2:
            raise FeatureDatasetIntegrityError(
                f"features.npy는 2차원이어야 합니다 (현재: {X.ndim}D)",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if y.ndim != 1:
            raise FeatureDatasetIntegrityError(
                f"labels.npy는 1차원이어야 합니다 (현재: {y.ndim}D)",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if X.shape[0] != y.shape[0]:
            raise FeatureDatasetIntegrityError(
                f"Feature 행 수({X.shape[0]})와 Label 행 수({y.shape[0]})가 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if X.shape[1] != len(feature_columns):
            raise FeatureDatasetIntegrityError(
                f"Feature 열 수({X.shape[1]})와 feature_columns 수({len(feature_columns)})가 일치하지 않습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        # 5. Type and Value range checks
        if not np.issubdtype(X.dtype, np.floating):
            raise FeatureDatasetIntegrityError(
                f"features.npy dtype은 floating이어야 합니다 (현재: {X.dtype})",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
        if not np.issubdtype(y.dtype, np.integer):
            raise FeatureDatasetIntegrityError(
                f"labels.npy dtype은 integer이어야 합니다 (현재: {y.dtype})",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )
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

        unique_labels = set(np.unique(y))
        if not unique_labels.issubset({0, 1}):
            raise FeatureDatasetIntegrityError(
                f"labels.npy에 {{0, 1}} 이외의 라벨 값이 포함되어 있습니다: {unique_labels}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        if len(unique_labels) < 2:
            raise InsufficientTrainingDataError(
                f"학습을 위해 Positive 및 Negative 표본이 모두 필요합니다 (현재 라벨 종류: {unique_labels})",
                code="INSUFFICIENT_TRAINING_DATA",
            )

        # 6. Metadata fingerprint validation
        expected_contract = metadata["contract"]
        if not expected_contract or not isinstance(expected_contract, dict):
            raise FeatureDatasetIntegrityError(
                "feature_metadata.json에 'contract' 항목이 누락되었습니다.",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
            )

        recalculated_version = compute_feature_dataset_version(**expected_contract)
        if recalculated_version != feature_dataset_version:
            raise FeatureDatasetIntegrityError(
                f"Feature Dataset 지문 불일치: 요청={feature_dataset_version}, 계산={recalculated_version}",
                code="FEATURE_DATASET_INTEGRITY_ERROR",
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

    def update_latest_pointer(self, model_id: str, model_version: str, artifact_path: Path) -> Path:
        """Atomically update latest.json pointer for model_id."""
        local_root = self._resolve_local_artifact_root()
        model_dir = local_root / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        pointer_file = model_dir / "latest.json"

        tmp_file = model_dir / f".tmp_latest_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{os.getpid()}_{uuid.uuid4().hex[:6]}.json"
        try:
            data = {
                "model_id": model_id,
                "latest_version": model_version,
                "artifact_uri": str(artifact_path.as_posix()),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_file.replace(pointer_file)
            return pointer_file
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

    def get_active_model_pointer(self, model_id: str) -> dict[str, Any] | None:
        """Retrieve active model version info from latest.json if present."""
        local_root = self._resolve_local_artifact_root()
        pointer_file = local_root / model_id / "latest.json"
        if not pointer_file.is_file():
            return None
        try:
            with open(pointer_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "latest_version" in data:
                return data
            return None
        except Exception:
            return None

    def activate_model_version(self, base_model: str, model_version: str) -> dict[str, Any]:
        """Strictly validate and atomically activate a published model version pointer."""
        if not base_model or ".." in base_model or "/" in base_model or "\\" in base_model:
            raise ModelArtifactIntegrityError(f"유효하지 않은 base_model입니다: {base_model!r}")
        if not model_version or ".." in model_version or "/" in model_version or "\\" in model_version:
            raise ModelArtifactIntegrityError(f"유효하지 않은 model_version입니다: {model_version!r}")

        local_root = self._resolve_local_artifact_root()
        target_dir = local_root / base_model / model_version
        if not target_dir.is_dir():
            raise ModelArtifactNotFoundError(
                f"Model Artifact '{base_model}/{model_version}'을 찾을 수 없습니다."
            )

        # Validate full artifact package integrity
        try:
            validate_model_artifact_directory(target_dir)
        except Exception as exc:
            raise ModelArtifactIntegrityError(
                f"Model Artifact '{base_model}/{model_version}' 무결성 검증 실패: {exc}"
            ) from exc

        # Check manifest contents
        manifest_path = target_dir / "manifest.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if manifest.get("model_id") != base_model or manifest.get("model_version") != model_version:
                raise ModelArtifactIntegrityError(
                    f"manifest.json의 식별자({manifest.get('model_id')}/{manifest.get('model_version')})가 "
                    f"요청({base_model}/{model_version})과 일치하지 않습니다."
                )
        except ModelArtifactIntegrityError:
            raise
        except Exception as exc:
            raise ModelArtifactIntegrityError(f"manifest.json 파싱 실패: {exc}") from exc

        prev_pointer = self.get_active_model_pointer(base_model)
        prev_version = prev_pointer.get("latest_version") if prev_pointer else None

        # Atomically update pointer
        try:
            self.update_latest_pointer(base_model, model_version, target_dir)
        except Exception as exc:
            raise ModelArtifactPublishFailedError(f"latest.json 포인터 갱신 실패: {exc}") from exc

        return {
            "base_model": base_model,
            "previous_model_version": prev_version,
            "active_model_version": model_version,
            "status": "activated",
        }

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
        """Atomically publish immutable Model Artifact package and validate it."""
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

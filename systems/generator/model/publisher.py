"""Atomic Model Artifact publisher and manifest validator for Generator."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import jsonschema

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.training.training_exception import (
    ModelActivationCommitError,
    ModelActivationInProgressError,
    ModelActivationTargetInvalidError,
    ModelActivationTargetNotFoundError,
    ModelActivationVerifyError,
    ModelArtifactConflictError,
    ModelArtifactPublishError,
    ModelArtifactValidationError,
    TrainingContractError,
)

logger = logging.getLogger(__name__)

_artifact_lock = threading.Lock()

ARTIFACT_TYPE = "predictive_maintenance_model"
ARTIFACT_SCHEMA_VERSION = "model-artifact-v1.0"
REQUIRED_ARTIFACT_ROLES = ("model", "feature_schema", "label_schema", "history_requirement", "metrics")
OFFICIAL_SCHEMA_PATH = Path("contracts/schemas/model-artifact.schema.json")


@dataclass(frozen=True)
class ModelArtifactPublicationResult:
    """Explicit result of publishing an immutable Model Artifact and updating its latest pointer."""

    model_id: str
    model_version: str
    published: bool
    artifact_uri: str | None
    latest_updated: bool
    latest_error_code: str | None = None
    latest_error_message: str | None = None


class ModelActivationLock:
    """Non-blocking OS-level advisory file lock for model latest pointer updates."""

    def __init__(self, lock_file_path: Path, model_id: str, requested_version: str | None = None) -> None:
        self.lock_file_path = lock_file_path
        self.model_id = model_id
        self.requested_version = requested_version
        self._file_obj = None

    def __enter__(self) -> "ModelActivationLock":
        self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_obj = open(self.lock_file_path, "a+", encoding="utf-8")

        locked = False
        try:
            if sys.platform != "win32":
                import fcntl
                fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            else:
                import msvcrt
                self._file_obj.seek(0)
                msvcrt.locking(self._file_obj.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
        except (IOError, OSError):
            pass

        if not locked:
            if self._file_obj:
                try:
                    self._file_obj.close()
                except Exception:
                    pass
                self._file_obj = None
            raise ModelActivationInProgressError(
                "해당 모델의 최신 포인터 갱신 작업이 이미 진행 중입니다.",
                details=[{"model_id": self.model_id, "requested_version": self.requested_version}],
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._file_obj:
            try:
                if sys.platform != "win32":
                    import fcntl
                    fcntl.flock(self._file_obj.fileno(), fcntl.LOCK_UN)
                else:
                    import msvcrt
                    self._file_obj.seek(0)
                    msvcrt.locking(self._file_obj.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                self._file_obj.close()
            except Exception:
                pass
            self._file_obj = None


def build_history_requirement_from_feature_schema(feature_schema: dict[str, Any]) -> dict[str, Any]:
    """Deterministically derive history requirements from verified Feature Schema recipe."""
    feature_schema_ver = feature_schema.get("feature_schema_version") or feature_schema.get("schema_version", "unknown")
    features_list = feature_schema.get("features", [])

    raw_fields: list[str] = []
    max_lag = 0
    max_rolling = 0
    max_ewm = 0
    rolling_min_periods = 0

    for feat in features_list:
        if isinstance(feat, dict):
            src = feat.get("source_field")
            if src and isinstance(src, str) and src not in raw_fields:
                raw_fields.append(src)
            op = feat.get("operation", "raw")
            params = feat.get("parameters", {}) or {}
            if op in ("lag", "diff"):
                p = int(params.get("periods", 1))
                if p > max_lag:
                    max_lag = p
            elif "rolling" in op:
                w = int(params.get("window", 1))
                mp = int(params.get("min_periods", w))
                if w > max_rolling:
                    max_rolling = w
                if mp > rolling_min_periods:
                    rolling_min_periods = mp
            elif "ewm" in op:
                s = int(params.get("span", 1))
                if s > max_ewm:
                    max_ewm = s

    min_history = max(1, max_lag + 1 if max_lag > 0 else 1, max_rolling, max_ewm)

    return {
        "history_requirement_version": f"hist-req-{feature_schema_ver}",
        "feature_executor_version": "feature-engine-v1",
        "minimum_history_rows": min_history,
        "required_columns": raw_fields,
        "missing_history_policy": "zero_pad",
        "max_lag_periods": max_lag,
        "max_rolling_window": max_rolling,
        "rolling_min_periods": rolling_min_periods,
    }


class ModelArtifactPublisher:
    """Publishes immutable 6-file Model Artifact packages and manages active version pointers."""

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            models_store = getattr(PATHS, "models_store", Path("models_store"))
            self.base_dir = Path(models_store) / "artifacts"
        else:
            self.base_dir = Path(base_dir)
        self._schema_cache: dict[str, Any] | None = None

    def _get_official_schema(self) -> dict[str, Any]:
        """Load official Model Artifact JSON Schema."""
        if self._schema_cache is None:
            cand = OFFICIAL_SCHEMA_PATH
            if not cand.exists():
                cand = Path.cwd() / OFFICIAL_SCHEMA_PATH
            if not cand.exists():
                raise TrainingContractError(f"Model Artifact 스키마를 찾을 수 없습니다: {OFFICIAL_SCHEMA_PATH}")
            try:
                self._schema_cache = json.loads(cand.read_text(encoding="utf-8"))
            except Exception as exc:
                raise TrainingContractError(f"Model Artifact 스키마 파싱 실패: {exc}") from exc
        return self._schema_cache

    def get_artifact_dir(self, model_id: str, model_version: str) -> Path:
        clean_id = model_id.strip()
        clean_ver = model_version.strip()
        if ".." in clean_id or "/" in clean_id or "\\" in clean_id:
            raise TrainingContractError(f"model_id에 경로 탈출 문자가 포함되어 있습니다: {model_id}")
        if ".." in clean_ver or "/" in clean_ver or "\\" in clean_ver:
            raise TrainingContractError(f"model_version에 경로 탈출 문자가 포함되어 있습니다: {model_version}")
        return self.base_dir / clean_id / clean_ver

    def get_logical_uri(self, path: Path) -> str:
        try:
            rel = path.relative_to(Path.cwd())
            return str(rel).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def validate_manifest(self, manifest: dict[str, Any], artifact_dir: Path) -> None:
        """Strictly validate manifest structure, payload roles, relative paths, and checksums."""
        # 1. JSON Schema validation against official schema
        schema = self._get_official_schema()
        try:
            jsonschema.validate(instance=manifest, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ModelArtifactValidationError(f"Model Artifact Manifest 스키마 검증 실패: {exc.message}") from exc

        # 2. Check artifact_files array
        artifact_files = manifest.get("artifact_files", [])
        if not isinstance(artifact_files, list):
            raise ModelArtifactValidationError("artifact_files는 배열 구조여야 합니다.")

        seen_roles: set[str] = set()
        seen_paths: set[str] = set()
        for item in artifact_files:
            if not isinstance(item, dict):
                raise ModelArtifactValidationError("artifact_files 항목은 객체여야 합니다.")
            role = item.get("role")
            rel_path_str = item.get("path")
            expected_sha = item.get("sha256")
            if not role or not rel_path_str or not expected_sha:
                raise ModelArtifactValidationError(f"Role 항목에 필수 필드 누락: {item}")
            if role in seen_roles:
                raise ModelArtifactValidationError(f"Manifest artifact_files에 role 중복 발견: '{role}'")
            if rel_path_str in seen_paths:
                raise ModelArtifactValidationError(f"Manifest artifact_files에 path 중복 발견: '{rel_path_str}'")
            if ".." in rel_path_str or Path(rel_path_str).is_absolute():
                raise ModelArtifactValidationError(f"Role '{role}'의 path에 비정상 경로 감지: '{rel_path_str}'")

            target_file = artifact_dir / rel_path_str
            if not target_file.exists() or not target_file.is_file():
                raise ModelArtifactValidationError(f"Role '{role}'의 선언된 파일이 존재하지 않습니다: {target_file}")

            actual_sha = compute_file_sha256(target_file)
            if actual_sha != expected_sha:
                raise ModelArtifactValidationError(
                    f"Role '{role}' 파일 체크섬 불일치 ({rel_path_str}): 기대값={expected_sha}, 실제={actual_sha}"
                )
            seen_roles.add(role)
            seen_paths.add(rel_path_str)

        for role in REQUIRED_ARTIFACT_ROLES:
            if role not in seen_roles:
                raise ModelArtifactValidationError(f"Manifest artifact_files에 필수 role 누락: '{role}'")

    def publish_artifact(
        self,
        *,
        model_id: str,
        model_version: str,
        base_model: str,
        model_obj: Any,
        dataset_id: str,
        dataset_version: str,
        feature_dataset_version: str,
        feature_schema: dict[str, Any],
        label_schema: dict[str, Any],
        history_requirement: dict[str, Any],
        metrics: dict[str, Any],
        training_config: dict[str, Any],
        provenance: dict[str, Any],
        activation_policy: str | None = None,
    ) -> ModelArtifactPublicationResult:
        """Atomically stage, validate, and publish an immutable Model Artifact package, then update latest pointer."""
        with _artifact_lock:
            dest_dir = self.get_artifact_dir(model_id, model_version)
            model_root = dest_dir.parent
            model_root.mkdir(parents=True, exist_ok=True)

            feature_schema_ver = feature_schema.get("feature_schema_version") or feature_schema.get("schema_version", "unknown-feature-schema")
            label_schema_ver = label_schema.get("label_schema_version") or label_schema.get("schema_version", "unknown-label-schema")
            training_cfg_ver = training_config.get("training_config_version", "training-config-v1")

            # Check if artifact directory already exists
            if dest_dir.exists():
                manifest_file = dest_dir / "manifest.json"
                if not manifest_file.is_file():
                    raise ModelArtifactConflictError(
                        f"Model Artifact '{model_id}/{model_version}' 디렉터리가 불완전한 상태로 이미 존재합니다."
                    )
                try:
                    existing_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    self.validate_manifest(existing_manifest, dest_dir)
                except Exception as exc:
                    raise ModelArtifactConflictError(
                        f"Model Artifact '{model_id}/{model_version}'가 이미 존재하며 유효성 검증에 실패했습니다: {exc}"
                    ) from exc

                # Check input fingerprint match for idempotent pointer recovery
                em = existing_manifest
                em_cfg = em.get("training_config", {})
                em_prov = em.get("provenance", {})

                inputs_match = (
                    em.get("dataset_version") == dataset_version
                    and em.get("feature_schema_version") == feature_schema_ver
                    and em.get("label_schema_version") == label_schema_ver
                    and em_cfg.get("training_config_version") == training_cfg_ver
                    and em_cfg.get("training_config_sha256") == training_config.get("training_config_sha256")
                    and em_prov.get("feature_dataset_metadata_sha256") == provenance.get("feature_dataset_metadata_sha256")
                    and em_prov.get("prediction_horizon_hours") == provenance.get("prediction_horizon_hours")
                )

                if not inputs_match:
                    raise ModelArtifactConflictError(
                        f"Model Artifact '{model_id}/{model_version}'가 이미 다른 입력으로 존재합니다. "
                        "불변 아티팩트 정책에 따라 동일 버전 재발행 및 덮어쓰기는 금지됩니다."
                    )

                # Check if already pointing in latest.json
                final_pointer = model_root / "latest.json"
                already_latest = False
                if final_pointer.is_file():
                    try:
                        ptr_data = json.loads(final_pointer.read_text(encoding="utf-8"))
                        if ptr_data.get("model_version") == model_version or ptr_data.get("active_version") == model_version:
                            already_latest = True
                    except Exception:
                        pass

                if already_latest:
                    raise ModelArtifactConflictError(
                        f"Model Artifact '{model_id}/{model_version}'가 이미 정상 발행되어 최신 포인터로 활성화되어 있습니다. "
                        "불변 아티팩트 정책에 따라 동일 버전 재발행 및 덮어쓰기는 금지됩니다."
                    )

                # Inputs match and not yet in latest.json -> Retry pointer update!
                try:
                    self.update_active_pointer(model_id, model_version)
                    return ModelArtifactPublicationResult(
                        model_id=model_id,
                        model_version=model_version,
                        published=True,
                        artifact_uri=self.get_logical_uri(dest_dir),
                        latest_updated=True,
                    )
                except Exception as p_exc:
                    err_code = getattr(p_exc, "code", type(p_exc).__name__)
                    return ModelArtifactPublicationResult(
                        model_id=model_id,
                        model_version=model_version,
                        published=True,
                        artifact_uri=self.get_logical_uri(dest_dir),
                        latest_updated=False,
                        latest_error_code=err_code,
                        latest_error_message=str(p_exc),
                    )

            # Phase A: Staging and immutable Artifact publish
            staging_dir = model_root / f".tmp_{uuid.uuid4().hex}"
            staging_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 1. Write model.joblib
                model_file = staging_dir / "model.joblib"
                joblib.dump(model_obj, model_file, compress=3)

                # 2. Write feature_schema.json (full snapshot)
                feat_schema_file = staging_dir / "feature_schema.json"
                with open(feat_schema_file, "w", encoding="utf-8") as f:
                    json.dump(feature_schema, f, indent=2, ensure_ascii=False)

                # 3. Write label_schema.json (full snapshot)
                label_schema_file = staging_dir / "label_schema.json"
                with open(label_schema_file, "w", encoding="utf-8") as f:
                    json.dump(label_schema, f, indent=2, ensure_ascii=False)

                # 4. Write history_requirement.json
                hist_req_file = staging_dir / "history_requirement.json"
                with open(hist_req_file, "w", encoding="utf-8") as f:
                    json.dump(history_requirement, f, indent=2, ensure_ascii=False)

                # 5. Write metrics.json
                metrics_file = staging_dir / "metrics.json"
                with open(metrics_file, "w", encoding="utf-8") as f:
                    json.dump(metrics, f, indent=2, ensure_ascii=False)

                # 6. Calculate checksums for the 5 payload files
                checksum_dict = {
                    "model.joblib": compute_file_sha256(model_file),
                    "feature_schema.json": compute_file_sha256(feat_schema_file),
                    "label_schema.json": compute_file_sha256(label_schema_file),
                    "history_requirement.json": compute_file_sha256(hist_req_file),
                    "metrics.json": compute_file_sha256(metrics_file),
                }

                artifact_files_list = [
                    {
                        "role": "model",
                        "path": "model.joblib",
                        "sha256": checksum_dict["model.joblib"],
                    },
                    {
                        "role": "feature_schema",
                        "path": "feature_schema.json",
                        "sha256": checksum_dict["feature_schema.json"],
                    },
                    {
                        "role": "label_schema",
                        "path": "label_schema.json",
                        "sha256": checksum_dict["label_schema.json"],
                    },
                    {
                        "role": "history_requirement",
                        "path": "history_requirement.json",
                        "sha256": checksum_dict["history_requirement.json"],
                    },
                    {
                        "role": "metrics",
                        "path": "metrics.json",
                        "sha256": checksum_dict["metrics.json"],
                    },
                ]

                # 7. Construct and write manifest.json conforming to model-artifact.schema.json
                hist_req_ver = history_requirement.get("history_requirement_version", f"hist-req-{feature_schema_ver}")

                manifest = {
                    "artifact_type": ARTIFACT_TYPE,
                    "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                    "model_id": model_id,
                    "model_version": model_version,
                    "dataset_version": dataset_version,
                    "feature_schema_version": feature_schema_ver,
                    "label_schema_version": label_schema_ver,
                    "history_requirement_version": hist_req_ver,
                    "metrics_schema_version": "pdm-metrics-v1",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "training_config": training_config,
                    "metrics": metrics,
                    "checksum": {
                        "algorithm": "sha256",
                        "files": checksum_dict,
                    },
                    "provenance": provenance,
                    "compatibility": {"runtime": "app.diagnosis"},
                    "artifact_files": artifact_files_list,
                }

                manifest_file = staging_dir / "manifest.json"
                with open(manifest_file, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)

                # 8. Full validation of staging directory
                self.validate_manifest(manifest, staging_dir)

                # 9. Atomic rename / move staging -> dest_dir (Phase A completed!)
                staging_dir.rename(dest_dir)
                logger.info(f"[ModelArtifactPublisher] Published Model Artifact to {dest_dir}")

            except Exception as exc:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                if isinstance(exc, (ModelArtifactConflictError, ModelArtifactValidationError, TrainingContractError)):
                    raise
                logger.exception(f"[ModelArtifactPublisher] Failed to publish model artifact: {exc}")
                raise ModelArtifactPublishError(f"Model Artifact 원자적 발행 실패: {exc}") from exc

            # Phase B: Latest pointer update
            try:
                self.update_active_pointer(model_id, model_version)
                return ModelArtifactPublicationResult(
                    model_id=model_id,
                    model_version=model_version,
                    published=True,
                    artifact_uri=self.get_logical_uri(dest_dir),
                    latest_updated=True,
                )
            except Exception as p_exc:
                err_code = getattr(p_exc, "code", type(p_exc).__name__)
                logger.warning(
                    f"[ModelArtifactPublisher] Artifact published at {dest_dir} but latest pointer update failed: {p_exc}"
                )
                return ModelArtifactPublicationResult(
                    model_id=model_id,
                    model_version=model_version,
                    published=True,
                    artifact_uri=self.get_logical_uri(dest_dir),
                    latest_updated=False,
                    latest_error_code=err_code,
                    latest_error_message=str(p_exc),
                )

    def update_active_pointer(self, model_id: str, model_version: str) -> None:
        """Atomically update latest.json system-managed pointer for model_id with OS locking and validation."""
        model_root = self.base_dir / model_id
        model_root.mkdir(parents=True, exist_ok=True)
        lock_file = model_root / ".latest.lock"

        with ModelActivationLock(lock_file, model_id=model_id, requested_version=model_version):
            # 2. Check target artifact dir and manifest exist
            target_dir = self.get_artifact_dir(model_id, model_version)
            manifest_file = target_dir / "manifest.json"
            if not target_dir.is_dir() or not manifest_file.is_file():
                raise ModelActivationTargetNotFoundError(
                    f"최신 포인터 갱신 대상 모델 아티팩트가 존재하지 않습니다: {model_id}/{model_version}"
                )

            # 3. Checksum verification of target artifact files
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.validate_manifest(manifest_data, target_dir)
            except Exception as exc:
                if isinstance(exc, ModelArtifactValidationError):
                    raise ModelActivationTargetInvalidError(
                        f"최신 포인터 갱신 대상 모델 아티팩트 검증 실패: {exc.message}"
                    ) from exc
                raise ModelActivationTargetInvalidError(
                    f"최신 포인터 갱신 대상 모델 아티팩트 매니페스트 파싱 실패: {exc}"
                ) from exc

            # 4. Read existing latest.json for idempotency
            final_pointer = model_root / "latest.json"
            if final_pointer.is_file():
                try:
                    existing_pointer = json.loads(final_pointer.read_text(encoding="utf-8"))
                    if existing_pointer.get("model_version") == model_version or existing_pointer.get("active_version") == model_version:
                        logger.info(f"[ModelArtifactPublisher] latest.json is already pointing to {model_version} (idempotent success)")
                        return
                except Exception:
                    pass

            # 5-8. Atomic write to temp file, flush, fsync, os.replace
            tx_id = uuid.uuid4().hex
            temp_pointer = model_root / f".latest.{tx_id}.tmp"
            logical_uri = f"models_store/artifacts/{model_id}/{model_version}"
            now_iso = datetime.now(timezone.utc).isoformat()
            pointer_data = {
                "model_id": model_id,
                "model_version": model_version,
                "active_version": model_version,
                "artifact_uri": logical_uri,
                "updated_at": now_iso,
                "activated_at": now_iso,
                "manifest_path": f"{model_version}/manifest.json",
                "model_path": f"{model_version}/model.joblib",
            }

            try:
                with open(temp_pointer, "w", encoding="utf-8") as f:
                    json.dump(pointer_data, f, indent=2, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(temp_pointer, final_pointer)

                if sys.platform != "win32":
                    try:
                        dir_fd = os.open(str(model_root), os.O_RDONLY)
                        os.fsync(dir_fd)
                        os.close(dir_fd)
                    except Exception:
                        pass
            except Exception as exc:
                if temp_pointer.exists():
                    temp_pointer.unlink(missing_ok=True)
                raise ModelActivationCommitError(f"latest.json 원자적 교체 실패: {exc}") from exc

            # 9-10. Read-back verification
            try:
                readback_data = json.loads(final_pointer.read_text(encoding="utf-8"))
                rb_ver = readback_data.get("model_version") or readback_data.get("active_version")
                if rb_ver != model_version or readback_data.get("model_id") != model_id:
                    raise ModelActivationVerifyError(
                        f"latest.json read-back 불일치: 기대값={model_version}, 실제={rb_ver}"
                    )
            except Exception as exc:
                if isinstance(exc, ModelActivationVerifyError):
                    raise
                raise ModelActivationVerifyError(f"latest.json read-back 검증 실패: {exc}") from exc

            logger.info(f"[ModelArtifactPublisher] Updated latest pointer for {model_id} -> {model_version}")
    update_latest_pointer = update_active_pointer

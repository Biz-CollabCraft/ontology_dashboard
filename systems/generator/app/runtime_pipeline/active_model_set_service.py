"""Service for safely managing active-model-set.json pointer with atomic updates and lock protection."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from systems.generator.generator_config import PATHS, PROJECT_ROOT
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    ModelSetArtifactIntegrityError,
    ModelSetArtifactNotFoundError,
    ModelSetAtomicPublishFailedError,
    ModelSetContractInvalidError,
    ModelSetModelNotRegisteredError,
    ModelSetNotConfiguredError,
    ModelSetOptionalModelPolicyNotImplementedError,
    ModelSetUpdateConflictError,
    ModelSetUpdateLockedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ActiveModelConfig,
    ActiveModelSet,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class ActiveModelSetService:
    """Manages active-model-set.json pointer with file locking, validation, and atomic replace."""

    def __init__(
        self,
        models_store_dir: Optional[Path] = None,
        pointer_filename: str = "active-model-set.json",
    ) -> None:
        self.models_store = Path(models_store_dir) if models_store_dir else PATHS.models_store
        self.artifacts_dir = self.models_store / "artifacts"
        self.pointer_file = self.models_store / pointer_filename
        self.lock_file = self.models_store / f"{pointer_filename}.lock"

    def load_active_model_set(self) -> ActiveModelSet:
        """Load and validate active-model-set.json pointer. Raises ModelSetNotConfiguredError if missing."""
        if not self.pointer_file.exists():
            raise ModelSetNotConfiguredError(
                f"active-model-set.json 포인터 파일이 존재하지 않습니다: {self.pointer_file}",
                details=[{"path": str(self.pointer_file)}],
                retryable=False,
            )

        try:
            with open(self.pointer_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            model_set = ActiveModelSet.model_validate(data)
            if not model_set.models:
                raise ModelSetNotConfiguredError(
                    "active-model-set.json에 정의된 모델 목록이 비어 있습니다.",
                    details=[{"path": str(self.pointer_file)}],
                    retryable=False,
                )
            return model_set
        except Exception as exc:
            if isinstance(exc, ModelSetNotConfiguredError):
                raise
            raise ModelSetContractInvalidError(
                f"active-model-set.json 파싱 또는 계약 검증 실패: {exc}",
                details=[{"path": str(self.pointer_file), "error": str(exc)}],
                retryable=False,
            ) from exc

    def _resolve_model_id(self, base_or_id: str) -> str:
        clean = base_or_id.strip()
        if clean.startswith("pdm-"):
            return clean
        return f"pdm-{clean}"

    def update_active_model_set(
        self,
        new_set: ActiveModelSet,
        validate_artifacts: bool = True,
    ) -> ActiveModelSet:
        """Safely update active-model-set.json using file lock, artifact integrity check, and atomic replace."""
        self.models_store.mkdir(parents=True, exist_ok=True)

        # 1. Lock acquisition
        lock_fd = None
        try:
            lock_fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        except OSError as exc:
            raise ModelSetUpdateLockedError(
                f"active-model-set.json 잠금 획득 실패 (동시 갱신 경합): {exc}",
                details=[{"lock_path": str(self.lock_file)}],
                retryable=False,
            ) from exc

        try:
            # 2. Contract validation
            if not new_set.models:
                raise ModelSetContractInvalidError(
                    "active-model-set.json에 정의된 모델이 없습니다.",
                    retryable=False,
                )

            registered_allowlist = {"lightgbm", "xgboost", "random_forest", "pdm-lightgbm", "pdm-xgboost", "pdm-random_forest"}
            for base_or_id, config in new_set.models.items():
                if base_or_id not in registered_allowlist and self._resolve_model_id(base_or_id) not in registered_allowlist:
                    raise ModelSetModelNotRegisteredError(
                        f"Model Set에 등록되지 않은 모델이 포함되어 있습니다: {base_or_id}",
                        details=[{"model": base_or_id}],
                        retryable=False,
                    )

                if not config.required:
                    raise ModelSetOptionalModelPolicyNotImplementedError(
                        f"선택 모델(required=false) 정책은 현재 지원되지 않습니다: {base_or_id}",
                        details=[{"model": base_or_id, "config": config.model_dump()}],
                        retryable=False,
                    )

                if validate_artifacts:
                    model_id = self._resolve_model_id(base_or_id)
                    artifact_dir = self.artifacts_dir / model_id / config.model_version
                    if not artifact_dir.is_dir():
                        raise ModelSetArtifactNotFoundError(
                            f"Model Set에서 참조된 아티팩트 디렉터리가 존재하지 않습니다: {artifact_dir}",
                            details=[{"model_id": model_id, "version": config.model_version}],
                            retryable=False,
                        )

                    manifest_file = artifact_dir / "manifest.json"
                    if not manifest_file.exists():
                        raise ModelSetArtifactIntegrityError(
                            f"아티팩트 manifest.json이 누락되었습니다: {manifest_file}",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "manifest_missing"}],
                            retryable=False,
                        )

                    try:
                        with open(manifest_file, "r", encoding="utf-8") as mf:
                            manifest_data = json.load(mf)
                    except Exception as exc:
                        raise ModelSetArtifactIntegrityError(
                            f"manifest.json 파싱 실패: {exc}",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "manifest_json_parse_failed"}],
                            retryable=False,
                        ) from exc

                    # 1. Manifest required fields check
                    req_manifest_keys = ["model_id", "model_version", "artifact_files"]
                    for key in req_manifest_keys:
                        if key not in manifest_data or manifest_data[key] is None or manifest_data[key] == "":
                            raise ModelSetArtifactIntegrityError(
                                f"manifest.json에 필수 키 '{key}'가 누락되었습니다.",
                                details=[{"model_id": model_id, "version": config.model_version, "reason": f"manifest_field_missing:{key}"}],
                                retryable=False,
                            )

                    # 2. model_id & model_version match
                    if manifest_data.get("model_id") != model_id or manifest_data.get("model_version") != config.model_version:
                        raise ModelSetArtifactIntegrityError(
                            f"manifest.json의 model_id/model_version 불일치 ({manifest_data.get('model_id')}/{manifest_data.get('model_version')} vs {model_id}/{config.model_version})",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "model_id_version_mismatch"}],
                            retryable=False,
                        )

                    # 3. Schema version supported check
                    schema_ver = manifest_data.get("schema_version") or manifest_data.get("artifact_schema_version")
                    allowed_schema_versions = {"1.0", "1.0.0", "v1", "model-artifact-v1.0"}
                    if schema_ver and schema_ver not in allowed_schema_versions:
                        raise ModelSetArtifactIntegrityError(
                            f"지원되지 않는 Artifact Schema version 입니다: '{schema_ver}'",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "schema_version_unsupported"}],
                            retryable=False,
                        )

                    # 4. Check artifact_files roles and paths
                    artifact_files = manifest_data.get("artifact_files", [])
                    if not isinstance(artifact_files, list):
                        raise ModelSetArtifactIntegrityError(
                            "manifest.json의 artifact_files 필드가 배열 형태가 아닙니다.",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "artifact_files_not_list"}],
                            retryable=False,
                        )

                    declared_roles: list[str] = []
                    has_role_entries = False
                    for entry in artifact_files:
                        if isinstance(entry, dict) and "role" in entry:
                            has_role_entries = True
                            r_name = entry.get("role")
                            if r_name:
                                declared_roles.append(r_name)

                    if has_role_entries:
                        norm_roles = set()
                        for r in declared_roles:
                            norm_r = "model" if r == "model_artifact" else r
                            if norm_r in norm_roles:
                                raise ModelSetArtifactIntegrityError(
                                    f"manifest artifact_files에 중복된 role이 존재합니다: '{r}'",
                                    details=[{"model_id": model_id, "version": config.model_version, "reason": "role_duplicated"}],
                                    retryable=False,
                                )
                            norm_roles.add(norm_r)

                        required_roles = {"model", "feature_schema", "label_schema", "history_requirement", "metrics"}
                        missing_roles = required_roles - norm_roles
                        if missing_roles:
                            raise ModelSetArtifactIntegrityError(
                                f"manifest artifact_files에 필수 role이 누락되었습니다: {missing_roles}",
                                details=[{"model_id": model_id, "version": config.model_version, "reason": "required_role_missing"}],
                                retryable=False,
                            )

                    # 5. Check all declared artifact_files exist and match checksum
                    for file_entry in artifact_files:
                        fname = file_entry.get("path")
                        expected_sha = file_entry.get("sha256")
                        if fname:
                            target_f = artifact_dir / fname
                            if not target_f.is_file():
                                raise ModelSetArtifactIntegrityError(
                                    f"선언된 아티팩트 파일이 누락되었습니다: {target_f}",
                                    details=[{"model_id": model_id, "version": config.model_version, "reason": "declared_file_missing"}],
                                    retryable=False,
                                )
                            if expected_sha and compute_file_sha256(target_f) != expected_sha:
                                raise ModelSetArtifactIntegrityError(
                                    f"아티팩트 파일 체크섬 불일치: {target_f}",
                                    details=[{"model_id": model_id, "version": config.model_version, "reason": "checksum_mismatch"}],
                                    retryable=False,
                                )

                    # 6. Verify 4 JSON files exist & can be loaded via json.load
                    req_json_files = ["feature_schema.json", "label_schema.json", "history_requirement.json", "metrics.json"]
                    for jf in req_json_files:
                        jpath = artifact_dir / jf
                        if not jpath.is_file():
                            raise ModelSetArtifactIntegrityError(
                                f"필수 페이로드 파일 누락 ({jf}): {jpath}",
                                details=[{"model_id": model_id, "version": config.model_version, "reason": f"payload_file_missing:{jf}"}],
                                retryable=False,
                            )
                        try:
                            with open(jpath, "r", encoding="utf-8") as f:
                                json.load(f)
                        except Exception as exc:
                            raise ModelSetArtifactIntegrityError(
                                f"페이로드 JSON 파일 파싱 실패 ({jf}): {exc}",
                                details=[{"model_id": model_id, "version": config.model_version, "reason": f"json_load_failed:{jf}"}],
                                retryable=False,
                            ) from exc

                    # 7. Verify model.joblib exists & can be loaded via joblib.load
                    import joblib
                    model_joblib_path = artifact_dir / "model.joblib"
                    if not model_joblib_path.is_file():
                        raise ModelSetArtifactIntegrityError(
                            f"필수 모델 파일 model.joblib 누락: {model_joblib_path}",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "model_file_missing"}],
                            retryable=False,
                        )
                    try:
                        joblib.load(model_joblib_path)
                    except Exception as exc:
                        raise ModelSetArtifactIntegrityError(
                            f"모델 파일 joblib.load() 로드 실패: {exc}",
                            details=[{"model_id": model_id, "version": config.model_version, "reason": "joblib_load_failed"}],
                            retryable=False,
                        ) from exc

            # 3. Write temp file and atomic replace
            new_set.updated_at = now_utc_iso()
            content_bytes = json.dumps(new_set.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8")
            temp_file = self.models_store / f".tmp_{uuid.uuid4().hex}_active-model-set.json"

            try:
                with open(temp_file, "wb") as f:
                    f.write(content_bytes)
                    f.flush()
                    os.fsync(f.fileno())
                temp_file.replace(self.pointer_file)
            except Exception as io_exc:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except Exception:
                        pass
                raise ModelSetAtomicPublishFailedError(
                    f"active-model-set.json 원자적 포인터 교체 실패: {io_exc}",
                    retryable=False,
                ) from io_exc

            logger.info(
                f"[ActiveModelSetService] Successfully updated active-model-set.json to "
                f"set_id='{new_set.model_set_id}', set_ver='{new_set.model_set_version}' with {len(new_set.models)} model(s)"
            )
            return new_set

        finally:
            if lock_fd is not None:
                try:
                    os.close(lock_fd)
                except Exception:
                    pass
            if self.lock_file.exists():
                try:
                    self.lock_file.unlink()
                except Exception:
                    pass

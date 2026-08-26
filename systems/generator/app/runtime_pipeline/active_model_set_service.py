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
                            details=[{"model_id": model_id, "version": config.model_version}],
                            retryable=False,
                        )

                    try:
                        with open(manifest_file, "r", encoding="utf-8") as mf:
                            manifest_data = json.load(mf)

                        if manifest_data.get("model_id") != model_id or manifest_data.get("model_version") != config.model_version:
                            raise ModelSetArtifactIntegrityError(
                                f"manifest.json의 model_id/model_version 불일치 ({model_id}/{config.model_version})",
                                retryable=False,
                            )

                        for file_entry in manifest_data.get("artifact_files", []):
                            fname = file_entry.get("path")
                            expected_sha = file_entry.get("sha256")
                            if fname:
                                target_f = artifact_dir / fname
                                if not target_f.is_file():
                                    raise ModelSetArtifactIntegrityError(
                                        f"선언된 아티팩트 파일이 누락되었습니다: {target_f}",
                                        retryable=False,
                                    )
                                if expected_sha and compute_file_sha256(target_f) != expected_sha:
                                    raise ModelSetArtifactIntegrityError(
                                        f"아티팩트 파일 체크섬 불일치: {target_f}",
                                        retryable=False,
                                    )

                        req_files = ["model.joblib", "feature_schema.json", "label_schema.json", "history_requirement.json", "metrics.json"]
                        for rf in req_files:
                            if not (artifact_dir / rf).is_file():
                                raise ModelSetArtifactIntegrityError(
                                    f"필수 페이로드 파일 누락 ({rf}): {artifact_dir / rf}",
                                    retryable=False,
                                )

                    except Exception as m_exc:
                        if isinstance(m_exc, (ModelSetArtifactIntegrityError, ModelSetArtifactNotFoundError)):
                            raise
                        raise ModelSetArtifactIntegrityError(
                            f"아티팩트 무결성 검증 실패 ({model_id}/{config.model_version}): {m_exc}",
                            details=[{"error": str(m_exc)}],
                            retryable=False,
                        ) from m_exc

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

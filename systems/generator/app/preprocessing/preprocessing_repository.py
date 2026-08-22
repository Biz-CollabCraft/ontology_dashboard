"""Repository for versioned Preprocessing Plan and Mapping storage with atomic publishing."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.preprocessing.preprocessing_exception import (
    DatasetNotFoundError,
    DatasetContractError,
    PreprocessingPlanPublishError,
)

logger = logging.getLogger(__name__)


class PreprocessingRepository:
    """Manages versioned storage of Preprocessing Plans and mappings with atomic publishing."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = base_dir or (PATHS.models_store / "cache" / "preprocessing_plans")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _plan_filename(self, dataset_id: str, dataset_version: str) -> str:
        safe_id = dataset_id.replace("/", "_").replace("\\", "_").replace("..", "_").replace(":", "_")
        safe_ver = dataset_version.replace("/", "_").replace("\\", "_").replace("..", "_").replace(":", "_")
        return f"{safe_id}-{safe_ver}.json"

    def get_plan_path(self, dataset_id: str, dataset_version: str) -> Path:
        return self.base_dir / self._plan_filename(dataset_id, dataset_version)

    def get_logical_uri(self, dataset_id: str, dataset_version: str) -> str:
        plan_path = self.get_plan_path(dataset_id, dataset_version)
        try:
            repo_root = PATHS.models_store.parent
            return str(plan_path.relative_to(repo_root).as_posix())
        except Exception:
            return f"models_store/cache/preprocessing_plans/{self._plan_filename(dataset_id, dataset_version)}"

    def find_plan(self, dataset_id: str, dataset_version: str) -> Optional[dict[str, Any]]:
        path = self.get_plan_path(dataset_id, dataset_version)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"[PreprocessingRepository] Failed to read plan at {path}: {exc}")
            return None

    def load_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        preprocessing_plan_version: str,
    ) -> dict[str, Any]:
        """Load and strictly validate preprocessing plan by dataset_id, dataset_version, and plan_version."""
        path = self.get_plan_path(dataset_id, dataset_version)
        if not path.exists() or not path.is_file():
            alt_path = self.base_dir / f"{preprocessing_plan_version}.json"
            if alt_path.exists() and alt_path.is_file():
                path = alt_path
            else:
                raise DatasetNotFoundError(
                    f"Preprocessing Plan 파일을 찾을 수 없습니다: "
                    f"dataset='{dataset_id}:{dataset_version}', version='{preprocessing_plan_version}'"
                )

        try:
            with open(path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as exc:
            raise DatasetContractError(f"Preprocessing Plan JSON 파싱 실패 ({path.name}): {exc}") from exc

        if not isinstance(plan_data, dict):
            raise DatasetContractError(
                f"Preprocessing Plan 형식이 올바르지 않습니다 (dict 기대, {type(plan_data).__name__} 수신)"
            )

        # Validate internal fields if present
        plan_ds_id = plan_data.get("dataset_id")
        plan_ds_ver = plan_data.get("dataset_version")
        plan_ver = plan_data.get("preprocessing_plan_version")

        if plan_ds_id and plan_ds_id != dataset_id:
            raise DatasetContractError(
                f"Plan 내부 dataset_id ('{plan_ds_id}')가 요청된 dataset_id ('{dataset_id}')와 일치하지 않습니다."
            )
        if plan_ds_ver and plan_ds_ver != dataset_version:
            raise DatasetContractError(
                f"Plan 내부 dataset_version ('{plan_ds_ver}')가 요청된 dataset_version ('{dataset_version}')와 일치하지 않습니다."
            )
        if plan_ver and plan_ver != preprocessing_plan_version:
            raise DatasetContractError(
                f"Plan 내부 preprocessing_plan_version ('{plan_ver}')가 요청된 version ('{preprocessing_plan_version}')과 일치하지 않습니다."
            )

        # Required fields check
        if "structure_type" not in plan_data:
            raise DatasetContractError("Preprocessing Plan에 필수 필드 'structure_type'이 누락되었습니다.")
        if "selected_columns" not in plan_data and plan_data.get("structure_type") == "tabular_column_as_attribute":
            raise DatasetContractError("Preprocessing Plan에 필수 필드 'selected_columns'가 누락되었습니다.")

        return plan_data

    def publish_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        plan_data: dict[str, Any],
        overwrite: bool = False,
    ) -> str:
        """Atomically stage and publish a preprocessing plan JSON file."""
        target_path = self.get_plan_path(dataset_id, dataset_version)
        if target_path.exists() and not overwrite:
            logger.info(f"[PreprocessingRepository] Plan already exists at {target_path}, reusing without overwrite.")
            return self.get_logical_uri(dataset_id, dataset_version)

        # Ensure metadata keys are populated in plan_data
        data_to_write = dict(plan_data)
        if "dataset_id" not in data_to_write:
            data_to_write["dataset_id"] = dataset_id
        if "dataset_version" not in data_to_write:
            data_to_write["dataset_version"] = dataset_version
        if "preprocessing_plan_version" not in data_to_write:
            data_to_write["preprocessing_plan_version"] = f"preprocessing-plan-{dataset_id}-{dataset_version}"

        temp_path = self.base_dir / f".tmp_{uuid.uuid4().hex}_{self._plan_filename(dataset_id, dataset_version)}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data_to_write, f, ensure_ascii=False, indent=2)

            # Atomic rename / replace
            temp_path.replace(target_path)
            logger.info(f"[PreprocessingRepository] Atomically published plan to {target_path}")
            return self.get_logical_uri(dataset_id, dataset_version)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.exception(f"[PreprocessingRepository] Failed to publish plan: {exc}")
            raise PreprocessingPlanPublishError(f"전처리 계획 저장에 실패했습니다: {exc}") from exc

"""Repository for versioned Extraction Plan and Mapping storage with atomic publishing."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_exception import ExtractionPlanPublishError

logger = logging.getLogger(__name__)


class ExtractionRepository:
    """Manages versioned storage of Extraction Plans and mappings with atomic publishing."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._custom_base_dir = base_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base_dir is not None:
            return self._custom_base_dir
        return PATHS.models_store / "cache" / "extraction_plans"

    def _plan_filename(self, dataset_id: str, dataset_version: str) -> str:
        safe_id = dataset_id.replace("/", "_").replace("\\", "_")
        safe_ver = dataset_version.replace("/", "_").replace("\\", "_")
        return f"{safe_id}-{safe_ver}.json"

    def get_plan_path(self, dataset_id: str, dataset_version: str) -> Path:
        return self.base_dir / self._plan_filename(dataset_id, dataset_version)

    def get_logical_uri(self, dataset_id: str, dataset_version: str) -> str:
        plan_path = self.get_plan_path(dataset_id, dataset_version)
        try:
            repo_root = PATHS.models_store.parent
            return str(plan_path.relative_to(repo_root).as_posix())
        except Exception:
            return f"models_store/cache/extraction_plans/{self._plan_filename(dataset_id, dataset_version)}"

    def find_plan(self, dataset_id: str, dataset_version: str) -> Optional[dict[str, Any]]:
        path = self.get_plan_path(dataset_id, dataset_version)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"[ExtractionRepository] Failed to read plan at {path}: {exc}")
            return None

    def publish_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        plan_data: dict[str, Any],
        overwrite: bool = False,
    ) -> str:
        """Atomically stage and publish an extraction plan JSON file."""
        target_path = self.get_plan_path(dataset_id, dataset_version)
        if target_path.exists() and not overwrite:
            logger.info(f"[ExtractionRepository] Plan already exists at {target_path}, reusing without overwrite.")
            return self.get_logical_uri(dataset_id, dataset_version)

        self.base_dir.mkdir(parents=True, exist_ok=True)
        temp_path = self.base_dir / f".tmp_{uuid.uuid4().hex}_{self._plan_filename(dataset_id, dataset_version)}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(plan_data, f, ensure_ascii=False, indent=2)

            # Atomic rename / replace
            temp_path.replace(target_path)
            logger.info(f"[ExtractionRepository] Atomically published plan to {target_path}")
            return self.get_logical_uri(dataset_id, dataset_version)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.exception(f"[ExtractionRepository] Failed to publish plan: {exc}")
            raise ExtractionPlanPublishError(f"추출 계획 저장에 실패했습니다: {exc}") from exc

"""Repository for immutable versioned Preprocessing Plan storage and latest pointer management."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_exception import (
    DatasetNotFoundError,
    DatasetContractError,
    PreprocessingPlanPublishError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishedPreprocessingPlan:
    preprocessing_plan_id: str
    preprocessing_plan_version: str
    preprocessing_plan_uri: str
    sha256: str


def compute_preprocessing_plan_version(
    dataset_id: str,
    dataset_version: str,
    plan_data: dict[str, Any],
) -> str:
    """Compute deterministic 16-character SHA-256 version for preprocessing plan."""
    import hashlib
    canonical = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "structure_type": plan_data.get("structure_type"),
        "selected_columns": plan_data.get("selected_columns"),
        "id_column": plan_data.get("id_column"),
        "time_column": plan_data.get("time_column"),
        "attribute_column": plan_data.get("attribute_column"),
        "value_column": plan_data.get("value_column"),
        "duplicate_policy": plan_data.get("duplicate_policy"),
        "aggregation": plan_data.get("aggregation"),
    }
    canonical_json = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    h = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()[:16]
    return f"preprocessing-plan-{h}"


class PreprocessingRepository:
    """Manages immutable versioned storage of Preprocessing Plans and dataset latest pointers."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self.base_dir = (base_dir or (PATHS.models_store / "cache" / "preprocessing_plans")).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_path_segment(self, segment: str, name: str) -> str:
        s = str(segment).strip()
        if not s or ".." in s or "/" in s or "\\" in s:
            raise DatasetContractError(f"{name}에 유효하지 않은 경로 문자열(..) 또는 구분자가 포함되어 있습니다: '{segment}'")
        return s

    def get_dataset_plan_dir(self, dataset_id: str, dataset_version: str) -> Path:
        safe_id = self._sanitize_path_segment(dataset_id, "dataset_id")
        safe_ver = self._sanitize_path_segment(dataset_version, "dataset_version")
        target_dir = (self.base_dir / safe_id / safe_ver).resolve()
        if not target_dir.is_relative_to(self.base_dir):
            raise DatasetContractError(f"허용된 Preprocessing Plan 루트를 벗어난 경로입니다: {target_dir}")
        return target_dir

    def get_latest_pointer_path(self, dataset_id: str, dataset_version: str) -> Path:
        return self.get_dataset_plan_dir(dataset_id, dataset_version) / "latest.json"

    def get_logical_uri(self, target_path: Path) -> str:
        try:
            repo_root = PATHS.models_store.parent.resolve()
            return str(target_path.resolve().relative_to(repo_root).as_posix())
        except Exception:
            return str(target_path.as_posix())

    def find_latest_plan(self, dataset_id: str, dataset_version: str) -> Optional[dict[str, Any]]:
        """Find and validate latest published plan for a dataset/version, or return None."""
        pointer_path = self.get_latest_pointer_path(dataset_id, dataset_version)
        if not pointer_path.is_file():
            # Check legacy cache for logging
            legacy_file = self.base_dir / f"{dataset_id}-{dataset_version}.json"
            if legacy_file.is_file():
                logger.info(
                    f"[PreprocessingRepository] Legacy flat plan cache detected for {dataset_id}:{dataset_version} at {legacy_file.name}, "
                    f"not promoting to canonical."
                )
            return None

        try:
            with open(pointer_path, "r", encoding="utf-8") as f:
                pointer_data = json.load(f)
        except Exception as exc:
            raise DatasetContractError(f"latest.json 포인터 파일 파싱 실패 ({pointer_path.name}): {exc}") from exc

        if not isinstance(pointer_data, dict):
            raise DatasetContractError(f"latest.json 포인터 형식이 올바르지 않습니다 (dict 기대, {type(pointer_data).__name__} 수신)")

        # Validate pointer metadata
        ptr_ds_id = pointer_data.get("dataset_id")
        ptr_ds_ver = pointer_data.get("dataset_version")
        plan_id = pointer_data.get("preprocessing_plan_id")
        plan_ver = pointer_data.get("preprocessing_plan_version")
        rel_path = pointer_data.get("path")
        expected_sha = pointer_data.get("sha256")

        if ptr_ds_id != dataset_id or ptr_ds_ver != dataset_version:
            raise DatasetContractError(
                f"latest.json 내부 dataset 식별자('{ptr_ds_id}:{ptr_ds_ver}')가 요청('{dataset_id}:{dataset_version}')과 일치하지 않습니다."
            )

        if not plan_id or not rel_path or not expected_sha:
            raise DatasetContractError("latest.json 포인터 파일에 필수 필드(preprocessing_plan_id, path, sha256)가 누락되었습니다.")

        plan_dir = self.get_dataset_plan_dir(dataset_id, dataset_version)
        target_file = (plan_dir / rel_path).resolve()
        if not target_file.is_relative_to(plan_dir) or not target_file.is_file():
            raise DatasetContractError(f"latest.json이 가리키는 Plan 파일이 디렉터리에 존재하지 않습니다: {rel_path}")

        actual_sha = compute_file_sha256(target_file)
        if actual_sha != expected_sha:
            raise DatasetContractError(
                f"latest.json이 가리키는 Plan 파일의 SHA-256 체크섬 불일치 ({actual_sha} != {expected_sha})"
            )

        try:
            with open(target_file, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as exc:
            raise DatasetContractError(f"Plan JSON 파일 파싱 실패 ({target_file.name}): {exc}") from exc

        # Strict internal validation
        if plan_data.get("preprocessing_plan_id") != plan_id:
            raise DatasetContractError(
                f"Plan 파일 내부 plan_id ('{plan_data.get('preprocessing_plan_id')}')가 latest 포인터 ID ('{plan_id}')와 일치하지 않습니다."
            )
        if plan_data.get("dataset_id") != dataset_id or plan_data.get("dataset_version") != dataset_version:
            raise DatasetContractError(
                f"Plan 파일 내부 dataset 식별자가 요청('{dataset_id}:{dataset_version}')과 일치하지 않습니다."
            )

        computed_ver = compute_preprocessing_plan_version(dataset_id, dataset_version, plan_data)
        if plan_data.get("preprocessing_plan_version") != computed_ver or plan_ver != computed_ver:
            raise DatasetContractError(
                f"Plan 파일 내부 version ('{plan_data.get('preprocessing_plan_version')}')이 내용 기반 계산 버전 ('{computed_ver}')과 일치하지 않습니다."
            )

        return plan_data

    find_plan = find_latest_plan

    def load_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        preprocessing_plan_id: str,
    ) -> dict[str, Any]:
        """Load and strictly validate an immutable Preprocessing Plan by its unique plan ID."""
        safe_plan_id = self._sanitize_path_segment(preprocessing_plan_id, "preprocessing_plan_id")
        plan_dir = self.get_dataset_plan_dir(dataset_id, dataset_version)

        filename = safe_plan_id if safe_plan_id.endswith(".json") else f"{safe_plan_id}.json"
        target_path = (plan_dir / filename).resolve()

        if not target_path.is_relative_to(plan_dir) or not target_path.is_file():
            raise DatasetNotFoundError(
                f"Preprocessing Plan 파일을 찾을 수 없습니다: "
                f"dataset='{dataset_id}:{dataset_version}', plan_id='{preprocessing_plan_id}'"
            )

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except Exception as exc:
            raise DatasetContractError(f"Preprocessing Plan JSON 파싱 실패 ({target_path.name}): {exc}") from exc

        if not isinstance(plan_data, dict):
            raise DatasetContractError(f"Preprocessing Plan 형식이 올바르지 않습니다 (dict 기대, {type(plan_data).__name__} 수신)")

        # Validate mandatory identification and structural fields
        required_fields = [
            "preprocessing_plan_id",
            "preprocessing_plan_version",
            "dataset_id",
            "dataset_version",
            "structure_type",
        ]
        for rf in required_fields:
            if rf not in plan_data or not plan_data[rf]:
                raise DatasetContractError(f"Preprocessing Plan에 필수 필드 '{rf}'가 누락되었거나 비어 있습니다.")

        expected_plan_id = safe_plan_id[:-5] if safe_plan_id.endswith(".json") else safe_plan_id
        if plan_data.get("preprocessing_plan_id") != expected_plan_id:
            raise DatasetContractError(
                f"Plan 내부 preprocessing_plan_id ('{plan_data.get('preprocessing_plan_id')}')가 "
                f"요청된 ID ('{expected_plan_id}')와 일치하지 않습니다."
            )
        if plan_data.get("dataset_id") != dataset_id:
            raise DatasetContractError(
                f"Plan 내부 dataset_id ('{plan_data.get('dataset_id')}')가 요청된 dataset_id ('{dataset_id}')와 일치하지 않습니다."
            )
        if plan_data.get("dataset_version") != dataset_version:
            raise DatasetContractError(
                f"Plan 내부 dataset_version ('{plan_data.get('dataset_version')}')가 요청된 dataset_version ('{dataset_version}')와 일치하지 않습니다."
            )

        computed_ver = compute_preprocessing_plan_version(dataset_id, dataset_version, plan_data)
        if plan_data.get("preprocessing_plan_version") != computed_ver:
            raise DatasetContractError(
                f"Plan 내부 preprocessing_plan_version ('{plan_data.get('preprocessing_plan_version')}')가 "
                f"내용 기반 계산 버전 ('{computed_ver}')과 일치하지 않습니다."
            )

        st = plan_data.get("structure_type")
        if st == "tabular_column_as_attribute":
            if "selected_columns" not in plan_data or not isinstance(plan_data["selected_columns"], list) or not plan_data["selected_columns"]:
                raise DatasetContractError("Wide 구조 Preprocessing Plan에 'selected_columns' 목록이 누락되었거나 비어 있습니다.")
        elif st == "tabular_row_as_attribute":
            for role_col in ("id_column", "attribute_column", "value_column"):
                if role_col not in plan_data or not plan_data[role_col]:
                    raise DatasetContractError(f"Long 구조 Preprocessing Plan에 '{role_col}' 역할 컬럼이 누락되었습니다.")

        return plan_data

    def publish_plan(
        self,
        dataset_id: str,
        dataset_version: str,
        plan_data: dict[str, Any],
    ) -> PublishedPreprocessingPlan:
        """Publish an immutable Plan file, then atomically advance latest.json."""
        plan_dir = self.get_dataset_plan_dir(dataset_id, dataset_version)
        plan_dir.mkdir(parents=True, exist_ok=True)

        plan_id = f"pp-{uuid.uuid4()}"
        canonical_version = compute_preprocessing_plan_version(dataset_id, dataset_version, plan_data)

        full_plan_data = {
            "preprocessing_plan_id": plan_id,
            "preprocessing_plan_version": canonical_version,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "structure_type": plan_data.get("structure_type", "tabular_column_as_attribute"),
            "selected_columns": plan_data.get("selected_columns", []),
            "id_column": plan_data.get("id_column"),
            "time_column": plan_data.get("time_column"),
            "attribute_column": plan_data.get("attribute_column"),
            "value_column": plan_data.get("value_column"),
            "duplicate_policy": plan_data.get("duplicate_policy", "error"),
            "aggregation": plan_data.get("aggregation"),
        }

        target_plan_path = plan_dir / f"{plan_id}.json"
        if target_plan_path.exists():
            raise PreprocessingPlanPublishError(f"Plan 파일이 이미 존재합니다 (불변 파일 덮어쓰기 금지): {target_plan_path}")

        temp_plan_path = plan_dir / f".tmp_{uuid.uuid4().hex}_{plan_id}.json"
        temp_latest_path = plan_dir / f".tmp_{uuid.uuid4().hex}_latest.json"

        try:
            # 1. Write and validate immutable plan JSON
            with open(temp_plan_path, "w", encoding="utf-8") as f:
                json.dump(full_plan_data, f, ensure_ascii=False, indent=2)

            plan_sha256 = compute_file_sha256(temp_plan_path)

            # 2. Atomic rename plan file
            temp_plan_path.replace(target_plan_path)
            logger.info(f"[PreprocessingRepository] Atomically published immutable plan {plan_id} to {target_plan_path}")

            # 3. Write latest.json pointer
            latest_data = {
                "dataset_id": dataset_id,
                "dataset_version": dataset_version,
                "preprocessing_plan_id": plan_id,
                "preprocessing_plan_version": canonical_version,
                "path": f"{plan_id}.json",
                "sha256": plan_sha256,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            with open(temp_latest_path, "w", encoding="utf-8") as f:
                json.dump(latest_data, f, ensure_ascii=False, indent=2)

            # 4. Atomic replace latest.json
            latest_pointer_path = plan_dir / "latest.json"
            temp_latest_path.replace(latest_pointer_path)
            logger.info(f"[PreprocessingRepository] Atomically updated latest pointer for {dataset_id}:{dataset_version} -> {plan_id}")

            logical_uri = self.get_logical_uri(target_plan_path)
            return PublishedPreprocessingPlan(
                preprocessing_plan_id=plan_id,
                preprocessing_plan_version=canonical_version,
                preprocessing_plan_uri=logical_uri,
                sha256=plan_sha256,
            )
        except Exception as exc:
            for p in (temp_plan_path, temp_latest_path):
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
            if isinstance(exc, PreprocessingPlanPublishError):
                raise
            logger.exception(f"[PreprocessingRepository] Failed to publish plan: {exc}")
            raise PreprocessingPlanPublishError(f"전처리 계획 저장에 실패했습니다: {exc}") from exc

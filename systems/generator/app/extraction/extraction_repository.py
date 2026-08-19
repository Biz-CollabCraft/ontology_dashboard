"""Repository for immutable content-addressed Extraction Plan and Ontology Mapping storage."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_exception import (
    ExtractionPlanPublishError,
    ExtractionPlanNotReadyError,
    ExtractionPlanIntegrityError,
    ExtractionPlanContractInvalidError,
    OntologyMappingNotReadyError,
    OntologyMappingIntegrityError,
    OntologyMappingContractInvalidError,
)

logger = logging.getLogger(__name__)


def compute_plan_fingerprint(plan_data: dict[str, Any]) -> str:
    """Calculate deterministic SHA-256 fingerprint for extraction plan."""
    canonical = json.dumps(plan_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_plan_version(plan_data: dict[str, Any]) -> str:
    """Return content-based extraction plan version string."""
    return f"extraction-plan-{compute_plan_fingerprint(plan_data)}"


def compute_mapping_fingerprint(mapping_data: dict[str, Any]) -> str:
    """Calculate deterministic SHA-256 fingerprint for ontology mapping."""
    canonical = json.dumps(mapping_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def compute_mapping_version(mapping_data: dict[str, Any]) -> str:
    """Return content-based ontology mapping version string."""
    return f"ontology-mapping-{compute_mapping_fingerprint(mapping_data)}"


def validate_ontology_mapping_payload(
    mapping_data: dict[str, Any],
    extracted_columns: Optional[list[str]] = None,
) -> None:
    """Strictly validate ontology mapping schema and rules."""
    if not mapping_data or not isinstance(mapping_data, dict):
        raise OntologyMappingContractInvalidError("Ontology Mapping이 비어 있거나 올바른 딕셔너리 구조가 아닙니다.")

    from systems.generator.ontology_mapping.mapping_agent import load_catalog_nodes, DEFAULT_ONTOLOGY_NODES
    valid_nodes = set(load_catalog_nodes()) | set(DEFAULT_ONTOLOGY_NODES)

    non_unknown_count = 0
    for field, rec in mapping_data.items():
        if not isinstance(rec, dict):
            raise OntologyMappingContractInvalidError(f"Field '{field}'의 mapping 레코드가 dict 형식이 아닙니다.")

        target = rec.get("target_ontology")
        if not target or not isinstance(target, str):
            raise OntologyMappingContractInvalidError(f"Field '{field}'에 target_ontology가 누락되었습니다.")
        if target not in valid_nodes:
            raise OntologyMappingContractInvalidError(f"Field '{field}'의 target_ontology '{target}'가 catalog 노드에 정의되어 있지 않습니다.")

        if target != "Unknown":
            non_unknown_count += 1

        conf = rec.get("confidence")
        if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
            raise OntologyMappingContractInvalidError(f"Field '{field}'의 confidence {conf}가 [0.0, 1.0] 범위를 벗어납니다.")

        status = rec.get("status")
        if status not in ("auto_mapped", "user_confirmed", "pending", "confirmed"):
            raise OntologyMappingContractInvalidError(f"Field '{field}'의 status '{status}'가 유효한 상태 값이 아닙니다.")

        if extracted_columns is not None and field not in extracted_columns:
            raise OntologyMappingContractInvalidError(f"Mapping source_field '{field}'가 추출 데이터셋 컬럼에 존재하지 않습니다.")

    if non_unknown_count == 0:
        raise OntologyMappingContractInvalidError("모든 컬럼이 'Unknown'으로 매핑되어 유효한 온톨로지 피처를 생성할 수 없습니다.")


class ExtractionRepository:
    """Manages immutable content-addressed storage of Extraction Plans and Ontology Mappings."""

    def __init__(self, base_dir: Optional[Path] = None, mappings_dir: Optional[Path] = None) -> None:
        self._custom_base_dir = base_dir
        self._custom_mappings_dir = mappings_dir

    @property
    def base_dir(self) -> Path:
        if self._custom_base_dir is not None:
            return self._custom_base_dir
        return PATHS.models_store / "cache" / "extraction_plans"

    @property
    def mappings_dir(self) -> Path:
        if self._custom_mappings_dir is not None:
            return self._custom_mappings_dir
        return PATHS.models_store / "cache" / "mappings"

    def _safe_name(self, s: str) -> str:
        return s.replace("/", "_").replace("\\", "_")

    # --- Extraction Plan Management ---

    def get_plan_path(self, dataset_id: str, dataset_version: str, extraction_plan_version: str) -> Path:
        return self.base_dir / self._safe_name(dataset_id) / self._safe_name(dataset_version) / f"{extraction_plan_version}.json"

    def get_plan_uri(self, dataset_id: str, dataset_version: str, extraction_plan_version: str) -> str:
        plan_path = self.get_plan_path(dataset_id, dataset_version, extraction_plan_version)
        try:
            repo_root = PATHS.models_store.parent
            return str(plan_path.relative_to(repo_root).as_posix())
        except Exception:
            return f"models_store/cache/extraction_plans/{self._safe_name(dataset_id)}/{self._safe_name(dataset_version)}/{extraction_plan_version}.json"

    def find_plan(self, dataset_id: str, dataset_version: str, extraction_plan_version: str) -> dict[str, Any]:
        """Find and strictly verify content hash integrity of Extraction Plan."""
        path = self.get_plan_path(dataset_id, dataset_version, extraction_plan_version)
        if not path.exists():
            raise ExtractionPlanNotReadyError(
                f"요청한 Extraction Plan 파일이 없습니다 (dataset_id='{dataset_id}', "
                f"version='{dataset_version}', plan_version='{extraction_plan_version}'). "
                f"먼저 POST /extraction을 실행해 주세요."
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise ExtractionPlanContractInvalidError(f"Extraction Plan 파일({path}) 파싱에 실패했습니다: {exc}") from exc

        # Verify content hash matches version
        actual_ver = compute_plan_version(data)
        if actual_ver != extraction_plan_version:
            raise ExtractionPlanIntegrityError(
                f"Extraction Plan 파일의 내용 해시({actual_ver})와 "
                f"요청된 버전({extraction_plan_version})이 일치하지 않습니다."
            )
        return data

    def publish_plan(self, dataset_id: str, dataset_version: str, plan_data: dict[str, Any]) -> tuple[str, str]:
        """Atomically publish immutable content-addressed extraction plan JSON."""
        plan_version = compute_plan_version(plan_data)
        target_path = self.get_plan_path(dataset_id, dataset_version, plan_version)
        target_dir = target_path.parent

        if target_path.exists():
            logger.info(f"[ExtractionRepository] Immutable plan already exists at {target_path}, reusing without overwrite.")
            return plan_version, self.get_plan_uri(dataset_id, dataset_version, plan_version)

        target_dir.mkdir(parents=True, exist_ok=True)
        temp_path = target_dir / f".tmp_{uuid.uuid4().hex}_{plan_version}.json"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(plan_data, f, ensure_ascii=False, indent=2)

            temp_path.replace(target_path)
            logger.info(f"[ExtractionRepository] Atomically published plan {plan_version} to {target_path}")
            return plan_version, self.get_plan_uri(dataset_id, dataset_version, plan_version)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.exception(f"[ExtractionRepository] Failed to publish plan: {exc}")
            raise ExtractionPlanPublishError(f"추출 계획 저장에 실패했습니다: {exc}") from exc

    # --- Ontology Mapping Management ---

    def get_mapping_path(self, dataset_id: str, dataset_version: str, mapping_version: str) -> Path:
        return self.mappings_dir / self._safe_name(dataset_id) / self._safe_name(dataset_version) / f"{mapping_version}.json"

    def get_mapping_uri(self, dataset_id: str, dataset_version: str, mapping_version: str) -> str:
        mapping_path = self.get_mapping_path(dataset_id, dataset_version, mapping_version)
        try:
            repo_root = PATHS.models_store.parent
            return str(mapping_path.relative_to(repo_root).as_posix())
        except Exception:
            return f"models_store/cache/mappings/{self._safe_name(dataset_id)}/{self._safe_name(dataset_version)}/{mapping_version}.json"

    def find_mapping(self, dataset_id: str, dataset_version: str, mapping_version: str) -> dict[str, Any]:
        """Find and strictly verify content hash integrity and schema of Ontology Mapping."""
        path = self.get_mapping_path(dataset_id, dataset_version, mapping_version)
        if not path.exists():
            raise OntologyMappingNotReadyError(
                f"요청한 Ontology Mapping 파일이 없습니다 (dataset_id='{dataset_id}', "
                f"version='{dataset_version}', mapping_version='{mapping_version}'). "
                f"먼저 POST /extraction을 실행해 주세요."
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            raise OntologyMappingContractInvalidError(f"Ontology Mapping 파일({path}) 파싱에 실패했습니다: {exc}") from exc

        # Verify content hash matches version
        actual_ver = compute_mapping_version(data)
        if actual_ver != mapping_version:
            raise OntologyMappingIntegrityError(
                f"Ontology Mapping 파일의 내용 해시({actual_ver})와 "
                f"요청된 버전({mapping_version})이 일치하지 않습니다."
            )

        validate_ontology_mapping_payload(data)
        return data

    def publish_mapping(
        self,
        dataset_id: str,
        dataset_version: str,
        mapping_data: dict[str, Any],
        extracted_columns: Optional[list[str]] = None,
    ) -> tuple[str, str]:
        """Validate and atomically publish immutable content-addressed ontology mapping JSON."""
        validate_ontology_mapping_payload(mapping_data, extracted_columns=extracted_columns)
        mapping_version = compute_mapping_version(mapping_data)
        target_path = self.get_mapping_path(dataset_id, dataset_version, mapping_version)
        target_dir = target_path.parent

        if target_path.exists():
            logger.info(f"[ExtractionRepository] Immutable mapping already exists at {target_path}, reusing without overwrite.")
            return mapping_version, self.get_mapping_uri(dataset_id, dataset_version, mapping_version)

        target_dir.mkdir(parents=True, exist_ok=True)
        temp_path = target_dir / f".tmp_{uuid.uuid4().hex}_{mapping_version}.json"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)

            temp_path.replace(target_path)
            logger.info(f"[ExtractionRepository] Atomically published mapping {mapping_version} to {target_path}")
            return mapping_version, self.get_mapping_uri(dataset_id, dataset_version, mapping_version)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            logger.exception(f"[ExtractionRepository] Failed to publish mapping: {exc}")
            raise ExtractionPlanPublishError(f"온톨로지 매핑 저장에 실패했습니다: {exc}") from exc

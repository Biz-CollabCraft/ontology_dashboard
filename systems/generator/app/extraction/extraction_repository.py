"""Repository for atomic publishing, staging, and verification of Canonical Observation Datasets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonschema

from systems.generator.generator_config import PATHS, PROJECT_ROOT
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.extraction.extraction_exception import (
    ExtractionDatasetConflictError,
    ExtractionIntegrityError,
    ExtractionPublishFailedError,
    ExtractionRequestInvalidError,
)

logger = logging.getLogger(__name__)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ExtractionRepository:
    """Handles staging, manifest generation, schema verification, and atomic publishing of Observation Datasets."""

    def __init__(
        self,
        observations_root: Optional[Path] = None,
        manifest_schema_path: Optional[Path] = None,
        runs_root: Optional[Path] = None,
    ) -> None:
        self.observations_root = observations_root or (PATHS.data_dir / "observations")
        self.runs_root = runs_root or (PATHS.data_preprocessed / "extraction_runs")
        self.manifest_schema_path = manifest_schema_path or (
            PROJECT_ROOT / "contracts" / "schemas" / "generator-dataset-input-manifest.schema.json"
        )
        self._manifest_schema_cache: Optional[dict[str, Any]] = None

    def _get_manifest_schema(self) -> dict[str, Any]:
        if self._manifest_schema_cache is None:
            if not self.manifest_schema_path.is_file():
                raise ExtractionIntegrityError(f"Dataset Input Manifest schema not found: {self.manifest_schema_path}")
            try:
                self._manifest_schema_cache = json.loads(self.manifest_schema_path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ExtractionIntegrityError(f"Failed to parse manifest schema: {e}") from e
        return self._manifest_schema_cache

    def get_target_dir(self, dataset_id: str, dataset_version: str) -> Path:
        """Get canonical destination directory for versioned dataset."""
        return (self.observations_root / dataset_id / dataset_version).resolve()

    def get_staging_dir(self, run_id: str) -> Path:
        """Get staging directory for active extraction run."""
        p = (self.runs_root / run_id / "staging").resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def check_existing_dataset(
        self,
        dataset_id: str,
        dataset_version: str,
        expected_obs_sha256: Optional[str] = None,
        expected_prov_sha256: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Check if dataset version is already published.

        Returns existing manifest if identical, or raises ExtractionDatasetConflictError if content differs.
        """
        target_dir = self.get_target_dir(dataset_id, dataset_version)
        if not target_dir.exists() or not target_dir.is_dir():
            return None

        manifest_file = target_dir / "dataset_manifest.json"
        obs_file = target_dir / "observations.jsonl"
        prov_file = target_dir / "provenance.jsonl"

        if not manifest_file.is_file() or not obs_file.is_file():
            raise ExtractionDatasetConflictError(
                f"대상 데이터셋 디렉터리({dataset_id}/{dataset_version})가 불완전한 상태로 이미 존재합니다.",
                details=[{"dataset_id": dataset_id, "dataset_version": dataset_version, "target_dir": str(target_dir)}],
            )

        try:
            manifest_dict = json.loads(manifest_file.read_text(encoding="utf-8"))
            actual_obs_sha = compute_file_sha256(obs_file)

            # Check observations sha
            obs_entry = next((f for f in manifest_dict.get("files", []) if f.get("role") == "observations"), None)
            if obs_entry and obs_entry.get("sha256") != actual_obs_sha:
                raise ExtractionDatasetConflictError(
                    f"기존 발행된 데이터셋({dataset_id}/{dataset_version})의 observations.jsonl 체크섬이 일치하지 않습니다.",
                    details=[{"manifest_sha": obs_entry.get("sha256"), "actual_sha": actual_obs_sha}],
                )

            if expected_obs_sha256 and actual_obs_sha != expected_obs_sha256:
                raise ExtractionDatasetConflictError(
                    f"동일한 데이터셋 버전({dataset_id}/{dataset_version})이 다른 내용(체크섬={actual_obs_sha})으로 이미 발행되어 있습니다 (덮어쓰기 금지).",
                    details=[{
                        "dataset_id": dataset_id,
                        "dataset_version": dataset_version,
                        "existing_sha": actual_obs_sha,
                        "new_sha": expected_obs_sha256
                    }],
                )

            if expected_prov_sha256 and prov_file.is_file():
                actual_prov_sha = compute_file_sha256(prov_file)
                if actual_prov_sha != expected_prov_sha256:
                    raise ExtractionDatasetConflictError(
                        f"동일한 데이터셋 버전({dataset_id}/{dataset_version})의 provenance 체크섬이 상이합니다.",
                        details=[{"existing_prov_sha": actual_prov_sha, "new_prov_sha": expected_prov_sha256}],
                    )

            return manifest_dict
        except ExtractionDatasetConflictError:
            raise
        except Exception as exc:
            raise ExtractionDatasetConflictError(
                f"기존 데이터셋({dataset_id}/{dataset_version}) 확인 중 오류 발생: {exc}",
                details=[{"error": str(exc)}],
            ) from exc

    def stage_and_publish_dataset(
        self,
        run_id: str,
        dataset_id: str,
        dataset_version: str,
        observations: list[dict[str, Any]],
        provenance_records: list[dict[str, Any]],
        rejected_records: list[dict[str, Any]],
        schema_version: str = "canonical-observation-v1",
    ) -> tuple[Path, dict[str, Any]]:
        """Stage observations, rejected records, provenance, and manifest, then atomically publish."""
        target_dir = self.get_target_dir(dataset_id, dataset_version)
        target_parent = target_dir.parent
        target_parent.mkdir(parents=True, exist_ok=True)

        staging_dir = self.get_staging_dir(run_id)

        try:
            # Deterministic sorting
            # 1. observations: (asset_id, observed_at)
            sorted_obs = sorted(observations, key=lambda r: (r.get("asset_id", ""), r.get("observed_at", "")))
            # 2. provenance: (asset_id, observed_at, measurement_key, source_sequence, source_observation_id)
            sorted_prov = sorted(
                provenance_records,
                key=lambda r: (
                    r.get("asset_id", ""),
                    r.get("observed_at", ""),
                    r.get("measurement_key", ""),
                    r.get("source_sequence", 0),
                    r.get("source_observation_id", ""),
                ),
            )
            # 3. rejected: (source_offset, source_sequence)
            sorted_rej = sorted(
                rejected_records,
                key=lambda r: (
                    r.get("source_offset") or 0,
                    r.get("source_sequence") or 0,
                ),
            )

            # Write observations.jsonl
            obs_file = staging_dir / "observations.jsonl"
            with open(obs_file, "w", encoding="utf-8") as f:
                for obs in sorted_obs:
                    line = json.dumps(obs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    f.write(line + "\n")

            obs_sha256 = compute_file_sha256(obs_file) if sorted_obs else "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            obs_size_bytes = obs_file.stat().st_size

            # Write provenance.jsonl
            prov_file = staging_dir / "provenance.jsonl"
            with open(prov_file, "w", encoding="utf-8") as f:
                for prov in sorted_prov:
                    line = json.dumps(prov, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    f.write(line + "\n")

            prov_sha256 = compute_file_sha256(prov_file) if sorted_prov else "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            prov_size_bytes = prov_file.stat().st_size

            # Write rejected.jsonl
            rej_file = staging_dir / "rejected.jsonl"
            with open(rej_file, "w", encoding="utf-8") as f:
                for rej in sorted_rej:
                    line = json.dumps(rej, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    f.write(line + "\n")

            rej_sha256 = compute_file_sha256(rej_file) if sorted_rej else "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            rej_size_bytes = rej_file.stat().st_size

            # Check existing dataset with conflict guard
            existing_manifest = self.check_existing_dataset(
                dataset_id,
                dataset_version,
                expected_obs_sha256=obs_sha256,
                expected_prov_sha256=prov_sha256,
            )
            if existing_manifest is not None:
                # Clean up staging dir and return existing
                shutil.rmtree(staging_dir, ignore_errors=True)
                return target_dir, existing_manifest

            # Create and validate dataset_manifest.json with auxiliary_files
            manifest_payload = {
                "manifest_version": "generator-dataset-input-v1",
                "dataset_type": "observation",
                "dataset_id": dataset_id,
                "dataset_version": dataset_version,
                "schema_version": schema_version,
                "created_at": now_utc_iso(),
                "files": [
                    {
                        "role": "observations",
                        "path": "observations.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": obs_sha256,
                        "size_bytes": max(1, obs_size_bytes),
                    }
                ],
                "auxiliary_files": [
                    {
                        "role": "provenance",
                        "path": "provenance.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": prov_sha256,
                        "size_bytes": prov_size_bytes,
                    },
                    {
                        "role": "rejected",
                        "path": "rejected.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": rej_sha256,
                        "size_bytes": rej_size_bytes,
                    },
                ],
            }

            schema = self._get_manifest_schema()
            try:
                validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
                validator.validate(manifest_payload)
            except jsonschema.ValidationError as exc:
                raise ExtractionIntegrityError(
                    f"발행용 dataset_manifest.json 스키마 검증 실패: {exc.message}",
                    details=[{"error": exc.message, "path": list(exc.path)}],
                ) from exc

            manifest_file = staging_dir / "dataset_manifest.json"
            manifest_file.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            # Atomic copy/rename to immutable publish target
            if not target_dir.exists():
                try:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    for item in staging_dir.iterdir():
                        shutil.copy2(str(item), str(target_dir / item.name))
                except Exception as exc:
                    shutil.rmtree(target_dir, ignore_errors=True)
                    raise ExtractionPublishFailedError(f"데이터셋 원자적 발행 실패: {exc}") from exc
            else:
                raise ExtractionDatasetConflictError(
                    f"대상 데이터셋 디렉터리({dataset_id}/{dataset_version})가 이미 존재합니다 (덮어쓰기 금지).",
                    details=[{"dataset_id": dataset_id, "dataset_version": dataset_version}],
                )

            return target_dir, manifest_payload

        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

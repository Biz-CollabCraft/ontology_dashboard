"""Immutable Dataset Bundle Publisher and Publication Receipt Manager."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

import jsonschema
from pydantic import BaseModel

from systems.generator.generator_config import PROJECT_ROOT
from systems.generator.app.extraction.extraction_exception import (
    ExtractionDatasetConflictError,
    ExtractionDatasetIntegrityError,
    ExtractionNoValidObservationsError,
    ExtractionPublicationReceiptFailedError,
    ExtractionPublishFailedError,
    ExtractionRequestInvalidError,
)
from systems.generator.app.extraction.window_assembler import AssembledExtractionWindow

logger = logging.getLogger(__name__)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class PublishedObservationDataset(BaseModel):
    """Metadata describing a published immutable Observation Dataset."""

    dataset_id: str
    dataset_version: str
    dataset_dir: str

    manifest_uri: str
    manifest_sha256: str

    observations_uri: str
    observations_sha256: str

    provenance_uri: str
    provenance_sha256: str

    rejected_uri: str
    rejected_sha256: str

    observation_count: int
    rejected_count: int

    window_start: str
    window_end: str


class ExtractionWindowPublisher:
    """Publishes assembled UTC windows as immutable Dataset bundles with Manifests and Receipts."""

    def __init__(
        self,
        data_root: Optional[Path] = None,
        publications_root: Optional[Path] = None,
        manifest_schema_path: Optional[Path] = None,
        publication_schema_path: Optional[Path] = None,
    ) -> None:
        from systems.generator.generator_config import PATHS

        self.data_root = Path(data_root or (PROJECT_ROOT / "data" / "observations")).resolve()
        self.publications_root = Path(
            publications_root or (PATHS.data_preprocessed / "extraction_state" / "gen_data" / "publications")
        ).resolve()
        self.manifest_schema_path = Path(
            manifest_schema_path
            or (PROJECT_ROOT / "contracts" / "schemas" / "generator-dataset-input-manifest.schema.json")
        ).resolve()
        self.publication_schema_path = Path(
            publication_schema_path
            or (PROJECT_ROOT / "contracts" / "schemas" / "generator-extraction-publication.schema.json")
        ).resolve()

        self._manifest_schema_cache: Optional[dict[str, Any]] = None
        self._pub_schema_cache: Optional[dict[str, Any]] = None

    def _get_manifest_schema(self) -> dict[str, Any]:
        if self._manifest_schema_cache is None:
            if not self.manifest_schema_path.is_file():
                raise ExtractionRequestInvalidError(f"Manifest schema not found: {self.manifest_schema_path}")
            self._manifest_schema_cache = json.loads(self.manifest_schema_path.read_text(encoding="utf-8"))
        return self._manifest_schema_cache

    def _get_pub_schema(self) -> dict[str, Any]:
        if self._pub_schema_cache is None:
            if not self.publication_schema_path.is_file():
                raise ExtractionRequestInvalidError(f"Publication schema not found: {self.publication_schema_path}")
            self._pub_schema_cache = json.loads(self.publication_schema_path.read_text(encoding="utf-8"))
        return self._pub_schema_cache

    def validate_manifest(self, manifest_data: dict[str, Any]) -> None:
        schema = self._get_manifest_schema()
        try:
            validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
            validator.validate(manifest_data)
        except jsonschema.ValidationError as exc:
            raise ExtractionDatasetIntegrityError(
                f"Dataset manifest schema validation failed: {exc.message}",
                details=[{"path": list(exc.path), "error": exc.message}],
            ) from exc

    def validate_publication_receipt(self, receipt_data: dict[str, Any]) -> None:
        schema = self._get_pub_schema()
        try:
            validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
            validator.validate(receipt_data)
        except jsonschema.ValidationError as exc:
            raise ExtractionPublicationReceiptFailedError(
                f"Publication receipt schema validation failed: {exc.message}",
                details=[{"path": list(exc.path), "error": exc.message}],
            ) from exc

    def publish_window_dataset(
        self,
        window: AssembledExtractionWindow,
        run_id: str,
    ) -> PublishedObservationDataset:
        """Atomically publish an assembled extraction window as a verified immutable Dataset bundle."""
        if not window.observations:
            raise ExtractionNoValidObservationsError(
                f"Cannot publish dataset '{window.dataset_id}/{window.dataset_version}' with 0 valid observations."
            )

        target_parent = self.data_root / window.dataset_id
        target_parent.mkdir(parents=True, exist_ok=True)
        final_dataset_dir = target_parent / window.dataset_version

        # 1. Idempotency Check: if final_dataset_dir exists, verify checksums
        if final_dataset_dir.is_dir():
            manifest_file = final_dataset_dir / "dataset_manifest.json"
            if manifest_file.is_file():
                try:
                    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                    self.validate_manifest(manifest_data)
                    manifest_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()

                    # Verify files inside existing directory
                    obs_file = final_dataset_dir / "observations.jsonl"
                    prov_file = final_dataset_dir / "provenance.jsonl"
                    rej_file = final_dataset_dir / "rejected.jsonl"

                    if not (obs_file.is_file() and prov_file.is_file() and rej_file.is_file()):
                        raise ExtractionDatasetConflictError(
                            f"Dataset directory '{final_dataset_dir}' exists with missing files."
                        )

                    obs_sha = hashlib.sha256(obs_file.read_bytes()).hexdigest()
                    prov_sha = hashlib.sha256(prov_file.read_bytes()).hexdigest()
                    rej_sha = hashlib.sha256(rej_file.read_bytes()).hexdigest()

                    # Check match against newly computed records
                    new_obs_bytes = "".join(
                        json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                        for o in window.observations
                    ).encode("utf-8")
                    new_obs_sha = hashlib.sha256(new_obs_bytes).hexdigest()

                    if obs_sha == new_obs_sha:
                        logger.info(f"[WindowPublisher] Reusing existing identical dataset '{final_dataset_dir}'")
                        self._ensure_publication_receipt(window, final_dataset_dir, manifest_sha)
                        return PublishedObservationDataset(
                            dataset_id=window.dataset_id,
                            dataset_version=window.dataset_version,
                            dataset_dir=str(final_dataset_dir),
                            manifest_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/dataset_manifest.json",
                            manifest_sha256=manifest_sha,
                            observations_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/observations.jsonl",
                            observations_sha256=obs_sha,
                            provenance_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/provenance.jsonl",
                            provenance_sha256=prov_sha,
                            rejected_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/rejected.jsonl",
                            rejected_sha256=rej_sha,
                            observation_count=len(window.observations),
                            rejected_count=len(window.rejected_records),
                            window_start=window.window_start,
                            window_end=window.window_end,
                        )
                    else:
                        raise ExtractionDatasetConflictError(
                            f"Dataset '{final_dataset_dir}' exists with conflicting payload content."
                        )
                except ExtractionDatasetConflictError:
                    raise
                except Exception as exc:
                    raise ExtractionDatasetConflictError(
                        f"Dataset '{final_dataset_dir}' exists but is corrupt: {exc}"
                    ) from exc
            else:
                raise ExtractionDatasetConflictError(
                    f"Dataset directory '{final_dataset_dir}' exists without manifest."
                )

        # 2. Stage new Dataset bundle in temporary directory
        temp_dir = target_parent / f".tmp_{window.dataset_version}_{run_id}_{uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            now_iso = now_utc_iso()

            # observations.jsonl
            obs_lines = [
                json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for o in window.observations
            ]
            obs_bytes = "".join(obs_lines).encode("utf-8")
            obs_file = temp_dir / "observations.jsonl"
            obs_file.write_bytes(obs_bytes)
            obs_sha = hashlib.sha256(obs_bytes).hexdigest()
            obs_size = len(obs_bytes)

            # provenance.jsonl
            prov_lines = [
                json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for p in window.provenance_records
            ]
            prov_bytes = "".join(prov_lines).encode("utf-8")
            prov_file = temp_dir / "provenance.jsonl"
            prov_file.write_bytes(prov_bytes)
            prov_sha = hashlib.sha256(prov_bytes).hexdigest()
            prov_size = len(prov_bytes)

            # rejected.jsonl
            rej_lines = [
                json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                for r in window.rejected_records
            ]
            rej_bytes = "".join(rej_lines).encode("utf-8")
            rej_file = temp_dir / "rejected.jsonl"
            rej_file.write_bytes(rej_bytes)
            rej_sha = hashlib.sha256(rej_bytes).hexdigest()
            rej_size = len(rej_bytes)

            # dataset_manifest.json
            manifest_payload = {
                "manifest_version": "generator-dataset-input-v1",
                "dataset_type": "observation",
                "dataset_id": window.dataset_id,
                "dataset_version": window.dataset_version,
                "schema_version": "canonical-observation-v1",
                "created_at": now_iso,
                "files": [
                    {
                        "role": "observations",
                        "path": "observations.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": obs_sha,
                        "size_bytes": obs_size,
                    }
                ],
                "auxiliary_files": [
                    {
                        "role": "provenance",
                        "path": "provenance.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": prov_sha,
                        "size_bytes": prov_size,
                    },
                    {
                        "role": "rejected",
                        "path": "rejected.jsonl",
                        "media_type": "application/x-ndjson",
                        "sha256": rej_sha,
                        "size_bytes": rej_size,
                    },
                ],
                "extraction_context": {
                    "source_format": "gen_data_sensor_stream",
                    "source_identity": window.source_identity,
                    "source_uri": window.source_uri,
                    "site_id": window.site_id,
                    "cell_id": window.cell_id,
                    "window_start": window.window_start,
                    "window_end": window.window_end,
                    "source_start_offset": window.source_start_offset,
                    "source_end_offset": window.source_end_offset,
                    "mapping_id": window.mapping_id,
                    "mapping_version": window.mapping_version,
                    "mapping_sha256": window.mapping_sha256,
                    "source_fragment_manifest_sha256": [
                        r.fragment_manifest_sha256 for r in window.source_fragment_refs
                    ],
                },
            }

            self.validate_manifest(manifest_payload)
            manifest_bytes = (json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
            manifest_file = temp_dir / "dataset_manifest.json"
            manifest_file.write_bytes(manifest_bytes)
            manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

            # 3. Atomic directory rename
            try:
                os.replace(temp_dir, final_dataset_dir)
            except OSError:
                if final_dataset_dir.exists():
                    shutil.rmtree(final_dataset_dir)
                shutil.move(str(temp_dir), str(final_dataset_dir))

            # 4. Final verification in place
            self._verify_dataset_dir(final_dataset_dir, manifest_sha)

            # 5. Persist Publication Receipt
            self._ensure_publication_receipt(window, final_dataset_dir, manifest_sha)

            return PublishedObservationDataset(
                dataset_id=window.dataset_id,
                dataset_version=window.dataset_version,
                dataset_dir=str(final_dataset_dir),
                manifest_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/dataset_manifest.json",
                manifest_sha256=manifest_sha,
                observations_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/observations.jsonl",
                observations_sha256=obs_sha,
                provenance_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/provenance.jsonl",
                provenance_sha256=prov_sha,
                rejected_uri=f"data/observations/{window.dataset_id}/{window.dataset_version}/rejected.jsonl",
                rejected_sha256=rej_sha,
                observation_count=len(window.observations),
                rejected_count=len(window.rejected_records),
                window_start=window.window_start,
                window_end=window.window_end,
            )

        except Exception as exc:
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
            if isinstance(exc, (ExtractionDatasetConflictError, ExtractionDatasetIntegrityError, ExtractionNoValidObservationsError)):
                raise
            raise ExtractionPublishFailedError(
                f"Failed to publish dataset '{window.dataset_version}': {exc}"
            ) from exc

    def _verify_dataset_dir(self, dataset_dir: Path, expected_manifest_sha: str) -> None:
        """Verify entire directory, manifest, and file checksums."""
        m_file = dataset_dir / "dataset_manifest.json"
        if not m_file.is_file():
            raise ExtractionDatasetIntegrityError(f"dataset_manifest.json missing at '{dataset_dir}'")
        actual_m_sha = hashlib.sha256(m_file.read_bytes()).hexdigest()
        if actual_m_sha != expected_manifest_sha:
            raise ExtractionDatasetIntegrityError(
                f"Manifest SHA-256 mismatch: expected {expected_manifest_sha}, got {actual_m_sha}"
            )

        manifest = json.loads(m_file.read_text(encoding="utf-8"))
        self.validate_manifest(manifest)

        # Check all files
        all_declared = list(manifest.get("files", [])) + list(manifest.get("auxiliary_files", []))
        for fd in all_declared:
            fpath = dataset_dir / fd["path"]
            if not fpath.is_file():
                raise ExtractionDatasetIntegrityError(f"Declared file '{fd['path']}' missing at '{fpath}'")
            fbytes = fpath.read_bytes()
            if len(fbytes) != fd["size_bytes"]:
                raise ExtractionDatasetIntegrityError(
                    f"File '{fd['path']}' size mismatch: expected {fd['size_bytes']}, got {len(fbytes)}"
                )
            calc_sha = hashlib.sha256(fbytes).hexdigest()
            if calc_sha != fd["sha256"]:
                raise ExtractionDatasetIntegrityError(
                    f"File '{fd['path']}' SHA-256 mismatch: expected {fd['sha256']}, got {calc_sha}"
                )

    def _ensure_publication_receipt(
        self,
        window: AssembledExtractionWindow,
        dataset_dir: Path,
        manifest_sha: str,
    ) -> Path:
        """Atomically persist a publication receipt."""
        source_pub_dir = self.publications_root / window.source_identity
        source_pub_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = source_pub_dir / f"{window.dataset_version}.json"
        temp_receipt = source_pub_dir / f".tmp_{window.dataset_version}_{uuid4().hex}.json"

        receipt_payload = {
            "publication_schema_version": "generator-extraction-publication-v1",
            "source_identity": window.source_identity,
            "dataset_id": window.dataset_id,
            "dataset_version": window.dataset_version,
            "window_start": window.window_start,
            "window_end": window.window_end,
            "manifest_uri": f"data/observations/{window.dataset_id}/{window.dataset_version}/dataset_manifest.json",
            "manifest_sha256": manifest_sha,
            "source_fragment_refs": [
                {
                    "batch_id": r.batch_id,
                    "fragment_manifest_sha256": r.fragment_manifest_sha256,
                }
                for r in window.source_fragment_refs
            ],
            "status": "published",
            "published_at": now_utc_iso(),
        }

        self.validate_publication_receipt(receipt_payload)
        content = json.dumps(receipt_payload, indent=2, ensure_ascii=False) + "\n"

        try:
            with open(temp_receipt, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass

            try:
                os.replace(str(temp_receipt), str(receipt_file))
            except OSError:
                if receipt_file.exists():
                    receipt_file.unlink()
                shutil.move(str(temp_receipt), str(receipt_file))

            return receipt_file
        except Exception as exc:
            if temp_receipt.exists():
                try:
                    temp_receipt.unlink()
                except OSError:
                    pass
            raise ExtractionPublicationReceiptFailedError(
                f"Failed to persist publication receipt '{receipt_file}': {exc}"
            ) from exc

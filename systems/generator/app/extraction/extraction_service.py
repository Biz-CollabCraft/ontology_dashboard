"""Orchestration service for protocol extraction, parsing, dedup, and atomic publishing."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS, PROJECT_ROOT
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.extraction.extraction_exception import (
    ExtractionSourceNotFoundError,
    ExtractionSourcePathUnsupportedError,
    ExtractionSourceChecksumMismatchError,
    ExtractionIdempotencyConflictError,
    ExtractionRequestInvalidError,
    ExtractionProtocolUnsupportedError,
    ExtractionSourceIncompleteError,
    ExtractionError,
)
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionResultPayload,
    ExtractionTimeRange,
)
from systems.generator.app.extraction.mapping_repository import MappingRepository
from systems.generator.app.extraction.mapping_validator import MappingValidator
from systems.generator.app.extraction.parsers.sensor_record_parser import SensorRecordParser
from systems.generator.app.extraction.dedup_repository import DedupRepository
from systems.generator.app.extraction.checkpoint_repository import CheckpointRepository
from systems.generator.app.extraction.extraction_repository import ExtractionRepository

logger = logging.getLogger(__name__)


def compute_request_sha256(request: ExtractionRequest) -> str:
    """Compute canonical hash of extraction request payload excluding non-idempotent metadata."""
    data = request.model_dump()
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class ExtractionService:
    """End-to-end orchestration service for gen_data protocol extraction."""

    def __init__(
        self,
        mapping_repo: Optional[MappingRepository] = None,
        mapping_validator: Optional[MappingValidator] = None,
        parser: Optional[SensorRecordParser] = None,
        dedup_repo: Optional[DedupRepository] = None,
        checkpoint_repo: Optional[CheckpointRepository] = None,
        extraction_repo: Optional[ExtractionRepository] = None,
        allowed_roots: Optional[list[Path]] = None,
    ) -> None:
        self.mapping_repo = mapping_repo or MappingRepository()
        self.mapping_validator = mapping_validator or MappingValidator()
        self.parser = parser or SensorRecordParser(mapping_validator=self.mapping_validator)
        self.dedup_repo = dedup_repo or DedupRepository()
        self.checkpoint_repo = checkpoint_repo or CheckpointRepository()
        self.extraction_repo = extraction_repo or ExtractionRepository()
        self.allowed_roots = allowed_roots or [
            PATHS.data_dir.resolve(),
            PATHS.data_preprocessed.resolve(),
            PROJECT_ROOT.resolve(),
        ]

    def _resolve_source_path(self, source_uri: str) -> Path:
        """Resolve and validate source URI strictly within allowed project roots."""
        clean_uri = str(source_uri).strip()
        if not clean_uri:
            raise ExtractionSourcePathUnsupportedError("source_uri가 비어 있습니다.")

        p = Path(clean_uri)
        if ".." in p.parts:
            raise ExtractionSourcePathUnsupportedError(
                f"source_uri에 상위 디렉터리 탐색(..)이 포함되어 있습니다: '{clean_uri}'"
            )

        # Check candidate resolution
        resolved: Optional[Path] = None
        if p.is_absolute():
            resolved = p.resolve()
        else:
            candidates = [root / p for root in self.allowed_roots] + [PROJECT_ROOT / p]
            for c in candidates:
                if c.exists():
                    resolved = c.resolve()
                    break
            if resolved is None:
                resolved = (PROJECT_ROOT / p).resolve()

        # Check if inside any allowed root
        is_allowed = False
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root.resolve())
                is_allowed = True
                break
            except ValueError:
                continue

        if not is_allowed:
            raise ExtractionSourcePathUnsupportedError(
                f"source_uri가 허용된 데이터 루트를 벗어났습니다: '{clean_uri}'",
                details=[{"source_uri": clean_uri, "resolved": str(resolved)}],
            )

        if not resolved.exists() or not resolved.is_file():
            raise ExtractionSourceNotFoundError(
                f"소스 프로토콜 파일을 찾을 수 없습니다: '{clean_uri}'",
                details=[{"source_uri": clean_uri, "resolved": str(resolved)}],
            )

        return resolved

    def _verify_source_finalization(self, request: ExtractionRequest) -> bool:
        """Verify upstream run manifest if URI is supplied."""
        if not request.source_run_manifest_uri:
            return True

        manifest_path = self._resolve_source_path(request.source_run_manifest_uri)
        if request.source_run_manifest_sha256:
            actual_sha = compute_file_sha256(manifest_path)
            if actual_sha != request.source_run_manifest_sha256:
                raise ExtractionSourceChecksumMismatchError(
                    f"source_run_manifest SHA-256 불일치: 요청={request.source_run_manifest_sha256}, 실제={actual_sha}",
                    details=[{"expected": request.source_run_manifest_sha256, "actual": actual_sha}],
                )

        try:
            m_dict = json.loads(manifest_path.read_text(encoding="utf-8"))
            status = m_dict.get("status", m_dict.get("state", "completed"))
            if status not in ("completed", "finalized", "succeeded"):
                raise ExtractionSourceIncompleteError(
                    f"상위 프로토콜 실행이 아직 완료되지 않았습니다: status='{status}'",
                    details=[{"manifest_uri": request.source_run_manifest_uri, "status": status}],
                )
            return True
        except ExtractionSourceIncompleteError:
            raise
        except Exception as exc:
            raise ExtractionRequestInvalidError(
                f"source_run_manifest 파싱 실패: {exc}",
                details=[{"manifest_uri": request.source_run_manifest_uri}],
            ) from exc

    def execute_extraction(self, request: ExtractionRequest) -> ExtractionResponse:
        """Execute full extraction workflow with validation, dedup, staging, and atomic publishing."""
        req_sha256 = compute_request_sha256(request)

        # 1. Check Idempotency Key
        idempotency_record = self.dedup_repo.get_idempotency_record(
            request.idempotency_key,
            request.dataset_id,
            request.dataset_version,
        )
        if idempotency_record is not None:
            stored_sha, stored_response = idempotency_record
            if stored_sha == req_sha256:
                target_dir = self.extraction_repo.get_target_dir(request.dataset_id, request.dataset_version)
                if (target_dir / "observations.jsonl").is_file():
                    logger.info(
                        f"[ExtractionService] Returning idempotent existing response for key '{request.idempotency_key}'"
                    )
                    return ExtractionResponse.model_validate(stored_response)
            else:
                raise ExtractionIdempotencyConflictError(
                    f"동일한 멱등성 키('{request.idempotency_key}')로 상이한 요청이 이미 처리되었습니다.",
                    details=[{"idempotency_key": request.idempotency_key}],
                )

        # 2. Resolve source file and verify SHA-256
        source_path = self._resolve_source_path(request.source_uri)
        actual_source_sha256 = compute_file_sha256(source_path)
        if actual_source_sha256 != request.source_sha256:
            raise ExtractionSourceChecksumMismatchError(
                f"소스 파일 SHA-256 체크섬 불일치: 요청={request.source_sha256}, 실제={actual_source_sha256}",
                details=[{"expected": request.source_sha256, "actual": actual_source_sha256}],
            )

        # 3. Verify upstream source finalization
        is_finalized = self._verify_source_finalization(request)

        # 4. Load and validate static mapping table
        mapping_data, mapping_file_path = self.mapping_repo.load_mapping(
            request.mapping_id,
            request.mapping_version,
        )
        self.mapping_validator.validate_mapping(
            mapping_data=mapping_data,
            expected_mapping_id=request.mapping_id,
            expected_mapping_version=request.mapping_version,
            expected_mapping_sha256=request.mapping_sha256,
        )

        # 5. Check protocol and schema version compatibility
        if mapping_data.get("protocol_version") != request.protocol_version:
            raise ExtractionProtocolUnsupportedError(
                f"요청 protocol_version('{request.protocol_version}')이 매핑 선언('{mapping_data.get('protocol_version')}')과 일치하지 않습니다.",
                details=[{"requested": request.protocol_version, "mapping": mapping_data.get("protocol_version")}],
            )
        if mapping_data.get("source_schema_version") != request.source_schema_version:
            raise ExtractionProtocolUnsupportedError(
                f"요청 source_schema_version('{request.source_schema_version}')이 매핑 선언('{mapping_data.get('source_schema_version')}')과 일치하지 않습니다.",
                details=[{"requested": request.source_schema_version, "mapping": mapping_data.get("source_schema_version")}],
            )

        # 6. Acquire Single-writer Lock (Fast-fail 409)
        self.dedup_repo.acquire_lock(
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            run_id=request.run_id,
        )

        try:
            self.checkpoint_repo.save_run_state(
                run_id=request.run_id,
                status="running",
                stage="parsing",
                metadata={"request": request.model_dump()},
            )

            # 7. Parse, transform, and group records into flat wide-format
            source_identity = f"{request.source_uri}:{request.source_sha256}"
            batch_id = f"batch_{request.run_id}_01"

            # Register batch in pending status
            self.dedup_repo.create_batch(
                batch_id=batch_id,
                run_id=request.run_id,
                source_identity=source_identity,
                source_start_offset=1,
                source_end_offset=0,
                record_count=0,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
            )

            observations, provenance_records, rejected_records, processed_source_records, stats = self.parser.parse_file(
                source_path=source_path,
                mapping_data=mapping_data,
                extraction_run_id=request.run_id,
                source_direction=request.source_direction,
                dedup_checker=None,
                source_identity=source_identity,
                is_source_finalized=is_finalized,
            )

            self.checkpoint_repo.save_run_state(
                run_id=request.run_id,
                status="running",
                stage="staging",
                metadata={"stats": stats},
            )

            # 8. Stage and publish dataset atomically
            published_dir, manifest_payload = self.extraction_repo.stage_and_publish_dataset(
                run_id=request.run_id,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                observations=observations,
                provenance_records=provenance_records,
                rejected_records=rejected_records,
                schema_version="canonical-observation-v1",
            )

            # 9. Mark batch staged
            obs_file = published_dir / "observations.jsonl"
            obs_sha = compute_file_sha256(obs_file) if obs_file.exists() else ""
            self.dedup_repo.mark_batch_staged(
                batch_id=batch_id,
                staging_sha256=obs_sha,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
            )

            # 10. Commit to dedup ledger
            processed_obs_ids = [r["observation_id"] for r in processed_source_records]
            self.dedup_repo.record_processed_batch(
                source_identity=source_identity,
                source_record_ids=processed_obs_ids,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
            )

            # 11. Advance checkpoint atomically
            last_record = processed_obs_ids[-1] if processed_obs_ids else None
            self.checkpoint_repo.save_checkpoint(
                run_id=request.run_id,
                source_identity=source_identity,
                source_offset=stats.get("total_lines", 0),
                last_sequence=None,
                last_committed_batch_id=batch_id,
                processed_count=stats["parsed_records"],
                rejected_count=stats["rejected_records"],
                duplicate_count=0,
            )

            # 12. Mark batch committed
            self.dedup_repo.mark_batch_committed(
                batch_id=batch_id,
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
            )

            # 13. Construct response with auxiliary file SHA-256s
            time_range = None
            if stats.get("min_time") and stats.get("max_time"):
                time_range = ExtractionTimeRange(
                    min_time=stats["min_time"],
                    max_time=stats["max_time"],
                )

            obs_entry = next((f for f in manifest_payload.get("files", []) if f.get("role") == "observations"), {})
            aux_files = manifest_payload.get("auxiliary_files", [])
            prov_entry = next((f for f in aux_files if f.get("role") == "provenance"), {})
            rej_entry = next((f for f in aux_files if f.get("role") == "rejected"), {})

            manifest_file = published_dir / "dataset_manifest.json"
            manifest_sha = compute_file_sha256(manifest_file)

            result_payload = ExtractionResultPayload(
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                manifest_uri=f"data/observations/{request.dataset_id}/{request.dataset_version}/dataset_manifest.json",
                manifest_sha256=manifest_sha,
                observations_uri=f"data/observations/{request.dataset_id}/{request.dataset_version}/observations.jsonl",
                observations_sha256=obs_entry.get("sha256", ""),
                provenance_uri=f"data/observations/{request.dataset_id}/{request.dataset_version}/provenance.jsonl",
                provenance_sha256=prov_entry.get("sha256", ""),
                rejected_uri=f"data/observations/{request.dataset_id}/{request.dataset_version}/rejected.jsonl",
                rejected_sha256=rej_entry.get("sha256", ""),
                total_records_processed=stats["parsed_records"],
                observations_count=stats["observations_count"],
                rejected_count=stats["rejected_records"],
                asset_ids=stats["asset_ids"],
                time_range=time_range,
            )

            response = ExtractionResponse(
                request_id=request.request_id,
                idempotency_key=request.idempotency_key,
                run_id=request.run_id,
                status="succeeded",
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                result=result_payload,
            )

            # 14. Save to idempotency ledger and mark run succeeded
            self.dedup_repo.save_idempotency_record(
                idempotency_key=request.idempotency_key,
                request_sha256=req_sha256,
                response_dict=response.model_dump(),
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
            )

            self.checkpoint_repo.save_run_state(
                run_id=request.run_id,
                status="succeeded",
                stage="completed",
                metadata={"response": response.model_dump()},
            )

            return response

        finally:
            # Always release lock
            self.dedup_repo.release_lock(
                dataset_id=request.dataset_id,
                dataset_version=request.dataset_version,
                run_id=request.run_id,
            )

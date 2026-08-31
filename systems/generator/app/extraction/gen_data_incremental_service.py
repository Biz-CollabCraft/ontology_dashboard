"""Incremental append extraction service with checkpoints, file locking, and crash recovery."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence, Union

from pydantic import BaseModel

from systems.generator.app.extraction.checkpoint_repository import (
    GenDataExtractionCheckpoint,
    GenDataExtractionCheckpointRepository,
    PendingExtractionBatch,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionError,
    ExtractionMappingRebuildNotImplementedError,
    ExtractionSourceNotFoundError,
    ExtractionSourceTruncatedError,
)
from systems.generator.app.extraction.gen_data_fragment import (
    GenDataFragmentRepository,
)
from systems.generator.app.extraction.gen_data_identity import (
    compute_extraction_batch_id,
    compute_gen_data_source_identity,
    compute_source_prefix_info,
    verify_source_prefix,
)
from systems.generator.app.extraction.gen_data_lock import GenDataSourceLock
from systems.generator.app.extraction.gen_data_mapping import (
    GenDataStaticMappingConverter,
)
from systems.generator.app.extraction.gen_data_source import (
    GenDataSensorStreamSource,
)
from systems.generator.app.extraction.parsers.gen_data_sensor_stream_parser import (
    GenDataSensorStreamParser,
    RejectedGenDataRecord,
)

logger = logging.getLogger(__name__)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class IncrementalExtractionResult(BaseModel):
    """Result of an incremental extraction cycle on a gen_data sensor stream."""

    source_identity: str
    source_uri: str
    run_id: str
    batch_id: Optional[str] = None

    start_offset: int
    committed_offset: int

    records_read: int
    observations_staged: int
    rejected_staged: int

    fragment_manifest_uri: Optional[str] = None
    fragment_manifest_sha256: Optional[str] = None

    status: Literal["no_data", "fragment_committed"]


class GenDataIncrementalExtractionService:
    """Orchestrates single-writer locked incremental parsing, mapping, fragment staging, and checkpointing."""

    def __init__(
        self,
        checkpoint_repo: Optional[GenDataExtractionCheckpointRepository] = None,
        fragment_repo: Optional[GenDataFragmentRepository] = None,
        parser: Optional[GenDataSensorStreamParser] = None,
        converter: Optional[GenDataStaticMappingConverter] = None,
        lock_dir: Optional[Path] = None,
        failure_injector: Optional[Callable[[str], None]] = None,
    ) -> None:
        from systems.generator.generator_config import PATHS

        self.checkpoint_repo = checkpoint_repo or GenDataExtractionCheckpointRepository()
        self.fragment_repo = fragment_repo or GenDataFragmentRepository()
        self.parser = parser or GenDataSensorStreamParser()
        self.converter = converter or GenDataStaticMappingConverter()
        self.lock_dir = Path(
            lock_dir or (PATHS.data_preprocessed / "extraction_state" / "gen_data" / "locks")
        ).resolve()
        self.failure_injector = failure_injector

    def process_available_records(
        self,
        *,
        source: GenDataSensorStreamSource,
        mapping_data: dict[str, Any],
        run_id: str,
        max_records: int = 10000,
        max_bytes: Optional[int] = None,
    ) -> IncrementalExtractionResult:
        """Process completed records from source stream since last checkpoint.

        Invariants:
        1. Source OS-level lock is acquired.
        2. First completed record SHA-256 establishes deterministic source identity.
        3. Checkpoint is loaded and verified against file prefix and offset bounds.
        4. Crash recovery: if previous run left fragment_staged with valid manifest, checkpoint commits immediately.
        5. Completed lines are read and mapped in memory.
        6. Fragment files and manifest are written atomically and verified.
        7. Checkpoint advances through 'processing' -> 'fragment_staged' -> 'idle'.
        """
        source_path = Path(source.source_path).resolve()
        if not source_path.is_file():
            raise ExtractionSourceNotFoundError(f"Source stream file does not exist at '{source_path}'")

        # 1. Validate requested mapping table contract FIRST (before checking file size or EOF)
        self.converter.mapping_validator.validate_mapping(
            mapping_data, expected_source_format="gen_data_sensor_stream"
        )
        req_mapping_id = str(mapping_data.get("mapping_id", "")).strip()
        req_mapping_version = str(mapping_data.get("mapping_version", "")).strip()
        req_mapping_sha256 = str(mapping_data.get("mapping_sha256", "")).strip().lower()

        # 2. Inspect source file size and completed first record
        st_size = source_path.stat().st_size
        first_peek = None
        if st_size > 0:
            first_peek = self.parser.read_completed_records(source_path, start_offset=0, max_records=1)

        has_completed_first_record = (
            first_peek is not None
            and (len(first_peek.records) > 0 or len(first_peek.rejected_records) > 0)
        )

        # 3. If source identity cannot be computed from content (0 bytes or incomplete first record):
        if not has_completed_first_record:
            existing_chk = self.checkpoint_repo.find_checkpoint_by_source(source)
            if existing_chk is not None:
                # Rule: Check mapping identity match FIRST before checking truncate or no_data!
                if (
                    existing_chk.mapping_id != req_mapping_id
                    or existing_chk.mapping_version != req_mapping_version
                    or existing_chk.mapping_sha256 != req_mapping_sha256
                ):
                    logger.warning(
                        f"[IncrementalService] Mapping mismatch for source '{source.source_uri}': "
                        f"checkpoint=({existing_chk.mapping_id}, {existing_chk.mapping_version}, {existing_chk.mapping_sha256[:8]}...) vs "
                        f"requested=({req_mapping_id}, {req_mapping_version}, {req_mapping_sha256[:8]}...)"
                    )
                    raise ExtractionMappingRebuildNotImplementedError(
                        "The source was previously processed with a different mapping. Mapping-version replay is not supported in the current release.",
                        context={
                            "source_identity": existing_chk.source_identity,
                            "checkpoint_mapping_id": existing_chk.mapping_id,
                            "checkpoint_mapping_version": existing_chk.mapping_version,
                            "requested_mapping_id": req_mapping_id,
                            "requested_mapping_version": req_mapping_version,
                        },
                    )

                # Mapping matches! Now check if source was truncated below committed offset
                if st_size < existing_chk.last_committed_offset:
                    logger.error(
                        f"[IncrementalService] Source '{source.source_uri}' size ({st_size}) is less than last committed offset ({existing_chk.last_committed_offset})"
                    )
                    raise ExtractionSourceTruncatedError(
                        f"Source file '{source.source_uri}' size ({st_size} bytes) is less than last committed offset ({existing_chk.last_committed_offset} bytes)."
                    )

                if st_size == 0 and existing_chk.last_committed_offset > 0:
                    logger.error(
                        f"[IncrementalService] Source '{source.source_uri}' has 0 bytes but existing checkpoint offset is {existing_chk.last_committed_offset}"
                    )
                    raise ExtractionSourceTruncatedError(
                        f"Source file '{source.source_uri}' has been truncated to 0 bytes (last committed offset was {existing_chk.last_committed_offset})."
                    )

                reason = "EMPTY_NEW_SOURCE" if st_size == 0 else "INCOMPLETE_FIRST_RECORD"
                logger.info(f"[IncrementalService] Source '{source.source_uri}' has no new data ({reason})")
                return IncrementalExtractionResult(
                    source_identity=existing_chk.source_identity,
                    source_uri=source.source_uri,
                    run_id=run_id,
                    start_offset=existing_chk.last_committed_offset,
                    committed_offset=existing_chk.last_committed_offset,
                    records_read=0,
                    observations_staged=0,
                    rejected_staged=0,
                    status="no_data",
                )

            # No existing checkpoint found: genuine new empty or incomplete source
            if st_size == 0:
                logger.info(f"[IncrementalService] Source '{source.source_uri}' is empty new source (EMPTY_NEW_SOURCE)")
                return IncrementalExtractionResult(
                    source_identity="",
                    source_uri=source.source_uri,
                    run_id=run_id,
                    start_offset=0,
                    committed_offset=0,
                    records_read=0,
                    observations_staged=0,
                    rejected_staged=0,
                    status="no_data",
                )
            else:
                logger.info(
                    f"[IncrementalService] Source '{source.source_uri}' has {st_size} bytes but incomplete first record (INCOMPLETE_FIRST_RECORD)"
                )
                return IncrementalExtractionResult(
                    source_identity="",
                    source_uri=source.source_uri,
                    run_id=run_id,
                    start_offset=0,
                    committed_offset=0,
                    records_read=0,
                    observations_staged=0,
                    rejected_staged=0,
                    status="no_data",
                )

        assert first_peek is not None
        first_rec = first_peek.records[0] if first_peek.records else first_peek.rejected_records[0]
        source_identity = compute_gen_data_source_identity(
            source_uri=source.source_uri,
            site_id=source.site_id,
            cell_id=source.cell_id,
            first_record_sha256=first_rec.raw_sha256,
        )

        # 4. Acquire exclusive OS file lock
        lock = GenDataSourceLock(self.lock_dir, source_identity=source_identity)
        with lock:
            if self.failure_injector:
                self.failure_injector("after_lock_acquired")

            # Clean up older temporary checkpoint files
            self.checkpoint_repo.cleanup_orphan_tmp_files()

            # 5. Load and re-verify canonical checkpoint inside lock
            chk = self.checkpoint_repo.load_checkpoint(source_identity)
            if chk is not None:
                self.checkpoint_repo.validate_checkpoint_source(chk, source)

                # Check mapping identity match against checkpoint
                if (
                    chk.mapping_id != req_mapping_id
                    or chk.mapping_version != req_mapping_version
                    or chk.mapping_sha256 != req_mapping_sha256
                ):
                    logger.warning(
                        f"[IncrementalService] Mapping mismatch for source '{source_identity}': "
                        f"checkpoint=({chk.mapping_id}, {chk.mapping_version}, {chk.mapping_sha256[:8]}...) vs "
                        f"requested=({req_mapping_id}, {req_mapping_version}, {req_mapping_sha256[:8]}...)"
                    )
                    raise ExtractionMappingRebuildNotImplementedError(
                        "The source was previously processed with a different mapping. Mapping-version replay is not supported in the current release.",
                        context={
                            "source_identity": source_identity,
                            "checkpoint_mapping_id": chk.mapping_id,
                            "checkpoint_mapping_version": chk.mapping_version,
                            "requested_mapping_id": req_mapping_id,
                            "requested_mapping_version": req_mapping_version,
                        },
                    )

                # Verify file bounds and prefix integrity
                if chk.verified_prefix_length > 0:
                    verify_source_prefix(
                        source_path=source_path,
                        expected_length=chk.verified_prefix_length,
                        expected_sha256=chk.verified_prefix_sha256,
                        last_committed_offset=chk.last_committed_offset,
                    )

                if source_path.stat().st_size < chk.last_committed_offset:
                    raise ExtractionSourceTruncatedError(
                        f"Source file '{source_path}' size ({source_path.stat().st_size} bytes) is less than "
                        f"last committed offset ({chk.last_committed_offset} bytes)."
                    )


                # Crash Recovery: Check if recovering from fragment_staged
                if chk.status == "fragment_staged" and chk.pending_batch is not None:
                    pb = chk.pending_batch
                    frag_dir = self.fragment_repo.base_runs_dir / pb.run_id / "fragments" / pb.batch_id
                    # Verify staged fragment
                    self.fragment_repo.verify_fragment(frag_dir, pb.fragment_manifest_sha256)
                    # Commit staged batch
                    chk.last_committed_offset = pb.source_end_offset
                    chk.last_committed_line = pb.source_end_line
                    chk.last_committed_batch_id = pb.batch_id
                    chk.committed_batch_ids = (chk.committed_batch_ids + [pb.batch_id])[-100:]
                    chk.pending_batch = None
                    chk.status = "idle"
                    chk.updated_at = now_utc_iso()
                    self.checkpoint_repo.save_checkpoint_atomic(chk, failure_injector=self.failure_injector)
                    logger.info(f"[IncrementalService] Recovered and committed pending batch '{pb.batch_id}'")

                start_offset = chk.last_committed_offset
                start_line = chk.last_committed_line
            else:
                start_offset = 0
                start_line = 0
                now_str = now_utc_iso()
                chk = GenDataExtractionCheckpoint(
                    source_identity=source_identity,
                    source_uri=source.source_uri,
                    site_id=source.site_id,
                    cell_id=source.cell_id,
                    mapping_id=req_mapping_id,
                    mapping_version=req_mapping_version,
                    mapping_sha256=req_mapping_sha256,
                    last_committed_offset=0,
                    last_committed_line=0,
                    verified_prefix_length=0,
                    verified_prefix_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    status="idle",
                    created_at=now_str,
                    updated_at=now_str,
                )

            # Check if there is new data beyond committed offset (ONLY after mapping check!)
            file_size = source_path.stat().st_size
            if start_offset >= file_size:
                logger.info(
                    f"[IncrementalService] Source '{source.source_uri}' (identity={source_identity}) is at EOF with no new appended data (NO_NEW_APPENDED_DATA)"
                )
                return IncrementalExtractionResult(
                    source_identity=source_identity,
                    source_uri=source.source_uri,
                    run_id=run_id,
                    start_offset=start_offset,
                    committed_offset=start_offset,
                    records_read=0,
                    observations_staged=0,
                    rejected_staged=0,
                    status="no_data",
                )

            # 5. Mark status 'processing'
            chk.status = "processing"
            chk.updated_at = now_utc_iso()
            self.checkpoint_repo.save_checkpoint_atomic(chk, failure_injector=self.failure_injector)

            # 6. Read completed records
            read_result = self.parser.read_completed_records(
                source_path,
                start_offset=start_offset,
                max_records=max_records,
                max_bytes=max_bytes,
            )

            total_read = len(read_result.records) + len(read_result.rejected_records)
            if total_read == 0:
                chk.status = "idle"
                chk.updated_at = now_utc_iso()
                self.checkpoint_repo.save_checkpoint_atomic(chk)
                return IncrementalExtractionResult(
                    source_identity=source_identity,
                    source_uri=source.source_uri,
                    run_id=run_id,
                    start_offset=start_offset,
                    committed_offset=start_offset,
                    records_read=0,
                    observations_staged=0,
                    rejected_staged=0,
                    status="no_data",
                )

            # 7. Convert parsed records using static mapping
            observations = []
            rejected_records: list[Union[Any, RejectedGenDataRecord]] = list(read_result.rejected_records)
            latest_observed_at = chk.last_observed_at

            for parsed_rec in read_result.records:
                map_result = self.converter.convert(
                    record=parsed_rec,
                    source=source,
                    mapping_data=mapping_data,
                )
                if map_result.observation is not None:
                    observations.append(map_result.observation)
                    latest_observed_at = map_result.observation.observed_at
                elif map_result.rejected is not None:
                    rejected_records.append(map_result.rejected)

            end_offset = read_result.committed_candidate_offset
            end_line = start_line + total_read

            mapping_sha256 = mapping_data.get("mapping_sha256", "")
            mapping_id = mapping_data.get("mapping_id", "")
            mapping_version = mapping_data.get("mapping_version", "")

            batch_id = compute_extraction_batch_id(
                source_identity=source_identity,
                source_start_offset=start_offset,
                source_end_offset=end_offset,
                mapping_sha256=mapping_sha256,
            )

            # 8. Check for existing cross-run fragment with identical batch_id or save new
            existing_fragment = self.fragment_repo.find_fragment_by_batch_id(
                batch_id=batch_id,
                source_identity=source_identity,
                source_start_offset=start_offset,
                source_end_offset=end_offset,
                mapping_id=mapping_id,
                mapping_version=mapping_version,
                mapping_sha256=mapping_sha256,
            )

            if existing_fragment is not None:
                frag_dir, manifest, manifest_sha256 = existing_fragment
                effective_run_id = manifest.run_id
                logger.info(
                    f"[IncrementalService] Reusing existing cross-run fragment '{batch_id}' "
                    f"from run '{effective_run_id}'"
                )
            else:
                frag_dir, manifest, manifest_sha256 = self.fragment_repo.save_fragment_atomic(
                    run_id=run_id,
                    batch_id=batch_id,
                    source_identity=source_identity,
                    source_uri=source.source_uri,
                    source_start_offset=start_offset,
                    source_end_offset=end_offset,
                    source_start_line=start_line + 1,
                    source_end_line=end_line,
                    mapping_id=mapping_id,
                    mapping_version=mapping_version,
                    mapping_sha256=mapping_sha256,
                    observations=observations,
                    rejected_records=rejected_records,
                    failure_injector=self.failure_injector,
                )
                effective_run_id = run_id

            # 9. If brand new source, compute prefix checksum
            if chk.verified_prefix_length == 0:
                p_len, p_sha = compute_source_prefix_info(source_path, end_offset)
                chk.verified_prefix_length = p_len
                chk.verified_prefix_sha256 = p_sha

            # 10. Update Checkpoint to 'fragment_staged'
            staged_now = now_utc_iso()
            chk.status = "fragment_staged"
            chk.pending_batch = PendingExtractionBatch(
                batch_id=batch_id,
                run_id=effective_run_id,
                source_start_offset=start_offset,
                source_end_offset=end_offset,
                source_start_line=start_line + 1,
                source_end_line=end_line,
                record_count=total_read,
                observation_count=len(observations),
                rejected_count=len(rejected_records),
                mapping_id=mapping_id,
                mapping_version=mapping_version,
                mapping_sha256=mapping_sha256,
                fragment_manifest_uri=f"data_preprocessed/extraction_runs/{effective_run_id}/fragments/{batch_id}/fragment_manifest.json",
                fragment_manifest_sha256=manifest_sha256,
                staged_at=staged_now,
            )
            chk.updated_at = staged_now
            self.checkpoint_repo.save_checkpoint_atomic(chk, failure_injector=self.failure_injector)

            # 11. Final Commit: update committed offset and status 'idle'
            committed_now = now_utc_iso()
            chk.last_committed_offset = end_offset
            chk.last_committed_line = end_line
            chk.last_observed_at = latest_observed_at
            chk.last_committed_batch_id = batch_id
            chk.committed_batch_ids = (chk.committed_batch_ids + [batch_id])[-100:]
            chk.pending_batch = None
            chk.status = "idle"
            chk.updated_at = committed_now
            self.checkpoint_repo.save_checkpoint_atomic(chk, failure_injector=self.failure_injector)

            return IncrementalExtractionResult(
                source_identity=source_identity,
                source_uri=source.source_uri,
                run_id=run_id,
                batch_id=batch_id,
                start_offset=start_offset,
                committed_offset=end_offset,
                records_read=total_read,
                observations_staged=len(observations),
                rejected_staged=len(rejected_records),
                fragment_manifest_uri=f"data_preprocessed/extraction_runs/{effective_run_id}/fragments/{batch_id}/fragment_manifest.json",
                fragment_manifest_sha256=manifest_sha256,
                status="fragment_committed",
            )

from __future__ import annotations

from datetime import datetime, timezone

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.checkpoint_repository import GenDataExtractionCheckpointRepository
from systems.generator.app.extraction.extraction_manager import ExtractionManager
from systems.generator.app.extraction.fragment_lifecycle import GenDataFragmentLifecycleManager
from systems.generator.app.extraction.gen_data_fragment import GenDataFragmentRepository
from systems.generator.app.extraction.gen_data_incremental_service import GenDataIncrementalExtractionService
from systems.generator.app.extraction.gen_data_source import discover_gen_data_sensor_streams
from systems.generator.app.extraction.window_publish_service import ExtractionWindowPublishService
from systems.generator.app.operational_assets.mapping_management_service import MappingManagementError, MappingManagementService

from .rebuild_schema import ExtractionRebuildRequest


class RebuildService:
    async def execute(self, request: ExtractionRebuildRequest) -> dict:
        mapping_service = MappingManagementService()
        mapping = mapping_service.read(request.mapping_id, request.mapping_version)
        _, actual = mapping_service.normalize_and_validate(request.mapping_id, request.mapping_version, mapping, approved=True)
        if actual != request.mapping_sha256:
            raise MappingManagementError(422, "REBUILD_MAPPING_CHECKSUM_MISMATCH", "Replay Mapping checksum이 발행본과 일치하지 않습니다.")

        sensor_root = PATHS.gen_data_sensor_root or (PATHS.gen_data_output_dir / "sensor" if PATHS.gen_data_output_dir else None)
        sources = discover_gen_data_sensor_streams(sensor_root)
        source = next((item for item in sources if item.source_uri == request.source_uri), None)
        if source is None:
            raise MappingManagementError(404, "REBUILD_SOURCE_NOT_FOUND", "Replay 대상 gen_data source를 찾을 수 없습니다.")

        replay_root = PATHS.data_preprocessed / "extraction_replays" / request.mapping_sha256
        runs_root = replay_root / "runs"
        checkpoint_repo = GenDataExtractionCheckpointRepository(checkpoints_root=replay_root / "checkpoints")
        fragment_repo = GenDataFragmentRepository(base_runs_dir=runs_root)
        lifecycle = GenDataFragmentLifecycleManager(consumption_root=replay_root / "fragment_consumption", fragment_repo=fragment_repo)
        publisher = ExtractionWindowPublishService(fragment_repo=fragment_repo, lifecycle_mgr=lifecycle, runs_root=runs_root)
        incremental = GenDataIncrementalExtractionService(
            checkpoint_repo=checkpoint_repo,
            fragment_repo=fragment_repo,
            lock_dir=PATHS.data_preprocessed / "extraction_state" / "gen_data" / "locks",
        )
        manager = ExtractionManager(
            checkpoint_repo=checkpoint_repo,
            fragment_repo=fragment_repo,
            incremental_service=incremental,
            publish_service=publisher,
            lifecycle_mgr=lifecycle,
        )

        processed = rejected = 0
        datasets: list[dict] = []
        source_identity = None
        while True:
            result = await manager.process_source_once(
                source=source,
                mapping_data_override=mapping,
                flush_before=datetime.max.replace(tzinfo=timezone.utc),
                run_id=request.run_id,
                max_records=request.max_records,
                raise_on_error=True,
                emit_runtime_handoff=False,
            )
            source_identity = result.source_identity or source_identity
            processed += result.records_read
            rejected += result.rejected_staged
            datasets.extend(item.model_dump() for item in result.published_datasets)
            if result.status == "no_data":
                break

        return {
            "job_id": request.job_id,
            "run_id": request.run_id,
            "status": "succeeded" if processed or datasets else "no_data",
            "source_identity": source_identity,
            "mapping_id": request.mapping_id,
            "mapping_version": request.mapping_version,
            "mapping_sha256": request.mapping_sha256,
            "processed_records": processed,
            "rejected_records": rejected,
            "published_datasets": datasets,
        }

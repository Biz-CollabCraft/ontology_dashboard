"""FastAPI router for runtime pipeline inspection and internal enqueueing."""

from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from systems.generator.app.runtime_pipeline.pipeline_manager import PipelineManager
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    PipelineQueueItem,
    PipelineRunState,
)

router = APIRouter(tags=["Runtime Pipeline"])


class EnqueueRequest(BaseModel):
    job_id: str = Field(..., description="Unique job identifier")
    source_uri: str = Field(..., description="Path or URI of completed observation file")
    source_checksum: str = Field(..., description="SHA-256 checksum of source file")
    dataset_id: str = Field("canonical-ai4i-v1", description="Dataset identifier")
    dataset_version: str = Field("canonical-ai4i-physics-v3.1", description="Dataset version")


def get_manager() -> PipelineManager:
    return PipelineManager.get_instance()


@router.get("/runtime-pipeline/status")
def get_pipeline_status() -> dict[str, Any]:
    """Inspect current queue length, active running job, and recent runs."""
    return get_manager().get_status()


@router.get("/runtime-pipeline/runs/{run_id}", response_model=PipelineRunState)
def get_pipeline_run_state(run_id: str) -> PipelineRunState:
    """Fetch complete stage execution state and prediction array by run ID."""
    state = get_manager().get_run_state(run_id)
    if state is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "PIPELINE_RUN_NOT_FOUND", "message": f"Run '{run_id}' not found"},
        )
    return state


@router.get("/runtime-pipeline/queue", response_model=list[PipelineQueueItem])
def get_pipeline_queue(status: Optional[str] = Query(None, description="Filter by queue status")) -> list[PipelineQueueItem]:
    """List queued, running, succeeded, or failed queue items."""
    return get_manager().list_queue_items(status=status)


@router.post("/internal/runtime-pipeline/enqueue", response_model=PipelineQueueItem)
def enqueue_observation_source(req: EnqueueRequest) -> PipelineQueueItem:
    """Internal evaluation endpoint to enqueue completed observation file into FIFO queue."""
    return get_manager().enqueue(
        job_id=req.job_id,
        source_uri=req.source_uri,
        source_checksum=req.source_checksum,
        dataset_id=req.dataset_id,
        dataset_version=req.dataset_version,
    )

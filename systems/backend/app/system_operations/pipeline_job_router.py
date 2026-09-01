from collections.abc import Callable
from typing import Any
from fastapi import APIRouter, Depends, Request, Response, status

from .pipeline_job_schema import PipelineJobCreate


def build_pipeline_job_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any], require_csrf: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system/jobs", tags=["system-pipeline-jobs"])

    @router.get("")
    def list_jobs(status_filter: str | None = None, _: Any = Depends(require_permission("system.jobs.read")), service=Depends(get_service)):
        return {"items": service.list(status_filter)}

    @router.post("/rebuild", dependencies=[Depends(require_csrf)])
    def create_job(body: PipelineJobCreate, request: Request, response: Response, principal=Depends(require_permission("system.jobs.create")), service=Depends(get_service)):
        job, created = service.create(body, principal.user_id, getattr(request.state, "request_id", "request"))
        response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
        return job

    @router.get("/{job_id}")
    def get_job(job_id: str, _: Any = Depends(require_permission("system.jobs.read")), service=Depends(get_service)):
        return service.get(job_id)

    @router.post("/{job_id}/cancel", dependencies=[Depends(require_csrf)])
    def cancel_job(job_id: str, _: Any = Depends(require_permission("system.jobs.cancel")), service=Depends(get_service)):
        return service.cancel(job_id)

    return router

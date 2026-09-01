from collections.abc import Callable
from typing import Any
from fastapi import APIRouter,Depends,Request,status
from .impact_analysis_schema import DownstreamRebuildCreate, ImpactAnalysisCreate

def build_impact_analysis_router(*,get_service:Callable[...,Any],get_job_service:Callable[...,Any],require_permission:Callable[[str],Any],require_csrf:Callable[...,Any])->APIRouter:
    router=APIRouter(prefix="/api/system/impact-analyses",tags=["system-impact-analysis"])
    @router.get("")
    def list_items(_:Any=Depends(require_permission("system.impact.read")),service=Depends(get_service)): return {"items":service.list()}
    @router.post("",dependencies=[Depends(require_csrf)])
    def create(body:ImpactAnalysisCreate,principal=Depends(require_permission("system.impact.create")),service=Depends(get_service)): return service.create(body,principal.user_id)
    @router.get("/{analysis_id}")
    def get(analysis_id:str,_:Any=Depends(require_permission("system.impact.read")),service=Depends(get_service)): return service.get(analysis_id)
    @router.post("/{analysis_id}/execute",dependencies=[Depends(require_csrf)],status_code=status.HTTP_202_ACCEPTED)
    def execute(analysis_id:str,body:DownstreamRebuildCreate,request:Request,principal=Depends(require_permission("system.rebuild.execute")),service=Depends(get_job_service)):
        return service.create_downstream(analysis_id,body,principal.user_id,getattr(request.state,"request_id","request"))
    return router

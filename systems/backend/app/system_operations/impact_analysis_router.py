from collections.abc import Callable
from typing import Any
from fastapi import APIRouter,Depends
from .impact_analysis_schema import ImpactAnalysisCreate

def build_impact_analysis_router(*,get_service:Callable[...,Any],require_permission:Callable[[str],Any],require_csrf:Callable[...,Any])->APIRouter:
    router=APIRouter(prefix="/api/system/impact-analyses",tags=["system-impact-analysis"])
    @router.get("")
    def list_items(_:Any=Depends(require_permission("system.impact.read")),service=Depends(get_service)): return {"items":service.list()}
    @router.post("",dependencies=[Depends(require_csrf)])
    def create(body:ImpactAnalysisCreate,principal=Depends(require_permission("system.impact.create")),service=Depends(get_service)): return service.create(body,principal.user_id)
    @router.get("/{analysis_id}")
    def get(analysis_id:str,_:Any=Depends(require_permission("system.impact.read")),service=Depends(get_service)): return service.get(analysis_id)
    return router

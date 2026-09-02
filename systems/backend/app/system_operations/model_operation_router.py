from collections.abc import Callable
from typing import Any
from fastapi import APIRouter, Depends
from .model_operation_schema import ModelSelectRequest, ModelSelectionClearRequest, ModelSetOperationRequest, ModelSetRollbackRequest


def build_model_operation_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any], require_csrf: Callable[..., Any]) -> APIRouter:
    router=APIRouter(prefix="/api/system",tags=["system-model-operations"])
    @router.get("/models")
    def models(_:Any=Depends(require_permission("system.models.read")),service=Depends(get_service)): return service.list_models()
    @router.get("/models/{model_id}/selection-history")
    def history(model_id:str,_:Any=Depends(require_permission("system.models.read")),service=Depends(get_service)): return service.history(model_id)
    @router.post("/models/{model_id}/select",dependencies=[Depends(require_csrf)])
    def select(model_id:str,body:ModelSelectRequest,principal=Depends(require_permission("system.models.select")),service=Depends(get_service)): return service.select(model_id,body,principal.user_id)
    @router.post("/models/{model_id}/clear-selection",dependencies=[Depends(require_csrf)])
    def clear(model_id:str,body:ModelSelectionClearRequest,principal=Depends(require_permission("system.models.select")),service=Depends(get_service)): return service.clear(model_id,body,principal.user_id)
    @router.get("/model-sets/active")
    def active(_:Any=Depends(require_permission("system.models.read")),service=Depends(get_service)): return service.get_active()
    @router.get("/model-sets/revisions")
    def revisions(_:Any=Depends(require_permission("system.models.read")),service=Depends(get_service)): return service.revisions()
    @router.post("/model-sets/validate",dependencies=[Depends(require_csrf)])
    def validate(body:ModelSetOperationRequest,principal=Depends(require_permission("system.models.activate")),service=Depends(get_service)): return service.validate(body,principal.user_id)
    @router.post("/model-sets/activate",dependencies=[Depends(require_csrf)])
    def activate(body:ModelSetOperationRequest,principal=Depends(require_permission("system.models.activate")),service=Depends(get_service)): return service.activate(body,principal.user_id)
    @router.post("/model-sets/rollback",dependencies=[Depends(require_csrf)])
    def rollback(body:ModelSetRollbackRequest,principal=Depends(require_permission("system.models.rollback")),service=Depends(get_service)): return service.rollback(body,principal.user_id)
    return router

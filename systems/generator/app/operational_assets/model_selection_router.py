from fastapi import APIRouter, Depends, HTTPException

from .model_selection_schema import ActiveModelSetOperationRequest, ModelSelectionClearRequest, ModelSelectionRequest, ModelSetRollbackRequest
from .model_selection_service import ModelOperationError, ModelSelectionService
from .operational_asset_router import require_inventory_token


router = APIRouter(prefix="/internal/model-operations", tags=["system-model-operations"], dependencies=[Depends(require_inventory_token)])


def _call(function):
    try:
        return function()
    except ModelOperationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/models")
def list_models():
    return _call(lambda: ModelSelectionService().list_models())


@router.get("/models/{model_id}/selection")
def get_selection(model_id: str):
    return _call(lambda: ModelSelectionService().get_selection(model_id))


@router.post("/models/{model_id}/select")
def select_model(model_id: str, request: ModelSelectionRequest):
    return _call(lambda: ModelSelectionService().select(model_id, request))


@router.post("/models/{model_id}/clear-selection")
def clear_model_selection(model_id: str, request: ModelSelectionClearRequest):
    return _call(lambda: ModelSelectionService().clear(model_id, request.expected_selection_id))


@router.get("/active-model-set")
def get_active_model_set():
    return _call(lambda: ModelSelectionService().active_sets.load_active_model_set().model_dump(mode="json"))


@router.post("/active-model-set/validate")
def validate_active_model_set(request: ActiveModelSetOperationRequest):
    return _call(lambda: ModelSelectionService().validate_set(request))


@router.post("/active-model-set/activate")
def activate_model_set(request: ActiveModelSetOperationRequest):
    return _call(lambda: ModelSelectionService().activate(request))


@router.post("/active-model-set/rollback")
def rollback_model_set(request: ModelSetRollbackRequest):
    return _call(lambda: ModelSelectionService().activate(ActiveModelSetOperationRequest(**request.model_dump(exclude={"action"}))))

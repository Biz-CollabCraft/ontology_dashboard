from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from .managed_asset_schema import ManagedAssetDraftCreate, ManagedAssetDraftPublish, ManagedAssetDraftUpdate


def build_managed_asset_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any], require_csrf: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system/contracts/drafts", tags=["system-managed-contracts"])

    @router.get("")
    def list_drafts(asset_type: str | None = None, status: str | None = None, asset_id: str | None = None, _: Any = Depends(require_permission("system.contracts.read")), service=Depends(get_service)):
        return {"items": service.list(asset_type, status, asset_id)}

    @router.post("", dependencies=[Depends(require_csrf)])
    def create_draft(body: ManagedAssetDraftCreate, principal=Depends(require_permission("system.contracts.create_version")), service=Depends(get_service)):
        return service.create(body, principal.user_id)

    @router.get("/{draft_id}")
    def get_draft(draft_id: str, _: Any = Depends(require_permission("system.contracts.read")), service=Depends(get_service)):
        return service.get(draft_id)

    @router.put("/{draft_id}", dependencies=[Depends(require_csrf)])
    def update_draft(draft_id: str, body: ManagedAssetDraftUpdate, principal=Depends(require_permission("system.contracts.create_version")), service=Depends(get_service)):
        return service.update(draft_id, body, principal.user_id)

    @router.get("/{draft_id}/diff")
    def get_diff(draft_id: str, _: Any = Depends(require_permission("system.contracts.validate")), service=Depends(get_service)):
        return service.diff(draft_id)

    @router.post("/{draft_id}/validate", dependencies=[Depends(require_csrf)])
    def validate_draft(draft_id: str, principal=Depends(require_permission("system.contracts.validate")), service=Depends(get_service)):
        return service.validate(draft_id, principal.user_id)

    @router.post("/{draft_id}/publish", dependencies=[Depends(require_csrf)])
    def publish_draft(draft_id: str, body: ManagedAssetDraftPublish, principal=Depends(require_permission("system.contracts.publish")), service=Depends(get_service)):
        return service.publish(draft_id, body, principal.user_id)

    return router

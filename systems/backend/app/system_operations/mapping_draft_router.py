from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from .mapping_draft_schema import MappingDraftCreate, MappingDraftPublish, MappingDraftUpdate


def build_mapping_draft_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any], require_csrf: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system/mapping-drafts", tags=["system-mapping-management"])

    @router.get("")
    def list_drafts(_: Any = Depends(require_permission("system.assets.read")), service=Depends(get_service)):
        return {"items": service.list()}

    @router.post("", dependencies=[Depends(require_csrf)])
    def create_draft(body: MappingDraftCreate, principal=Depends(require_permission("system.assets.create_version")), service=Depends(get_service)):
        return service.create(body.mapping_id, body.target_version, body.base_version, principal.user_id)

    @router.get("/{draft_id}")
    def get_draft(draft_id: str, _: Any = Depends(require_permission("system.assets.read")), service=Depends(get_service)):
        return service.get(draft_id)

    @router.put("/{draft_id}", dependencies=[Depends(require_csrf)])
    def update_draft(draft_id: str, body: MappingDraftUpdate, principal=Depends(require_permission("system.assets.create_version")), service=Depends(get_service)):
        return service.update(draft_id, body.expected_revision, body.payload, principal.user_id)

    @router.get("/{draft_id}/diff")
    def diff_draft(draft_id: str, _: Any = Depends(require_permission("system.assets.read")), service=Depends(get_service)):
        return service.diff(draft_id)

    @router.post("/{draft_id}/validate", dependencies=[Depends(require_csrf)])
    def validate_draft(draft_id: str, principal=Depends(require_permission("system.assets.validate")), service=Depends(get_service)):
        return service.validate(draft_id, principal.user_id)

    @router.post("/{draft_id}/publish", dependencies=[Depends(require_csrf)])
    def publish_draft(draft_id: str, body: MappingDraftPublish, principal=Depends(require_permission("system.assets.publish")), service=Depends(get_service)):
        return service.publish(draft_id, body.expected_revision, principal.user_id)

    return router

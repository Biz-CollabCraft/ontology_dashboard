"""FastAPI transport adapter for Equipment-owned read routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .equipment_exception import EquipmentNotFoundError


def register_equipment_routes(
    router: APIRouter,
    *,
    service_dependency: Callable[..., Any],
    authorization_dependency: Callable[..., Any],
) -> None:
    """Attach Equipment routes to a composition-owned parent router."""

    @router.get("/equipment")
    def list_equipment(
        _: Any = Depends(authorization_dependency),
        service: Any = Depends(service_dependency),
    ) -> dict[str, Any]:
        return {"items": service.list_equipment()}

    @router.get("/equipment/{equipment_id}")
    def get_equipment(
        equipment_id: str,
        _: Any = Depends(authorization_dependency),
        service: Any = Depends(service_dependency),
    ) -> dict[str, Any]:
        try:
            return service.equipment(equipment_id)
        except EquipmentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="equipment not found") from exc

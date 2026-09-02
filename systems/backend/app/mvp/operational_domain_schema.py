"""Typed production decision context used by read-only agent tools."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RelationshipState(StrEnum):
    VERIFIED = "verified"
    ASSUMED_DEMO = "assumed_demo"
    NOT_CONNECTED = "not_connected"
    UNKNOWN = "unknown"
    CONFLICTING = "conflicting"


class ProductionOrder(FrozenModel):
    order_id: str = Field(min_length=1, max_length=240)
    product_id: str = Field(min_length=1, max_length=240)
    product_label: str = Field(min_length=1, max_length=240)
    required_quantity: int = Field(ge=0)
    completed_quantity: int = Field(ge=0)
    due_at: datetime
    priority: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=240)
    assigned_asset_id: str = Field(min_length=1, max_length=240)
    relationship_state: RelationshipState
    source_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_quantities_and_time(self) -> ProductionOrder:
        if self.completed_quantity > self.required_quantity:
            raise ValueError("completed_quantity must not exceed required_quantity")
        _require_aware(self.due_at, "due_at")
        return self


class WipRecord(FrozenModel):
    wip_id: str = Field(min_length=1, max_length=240)
    order_id: str = Field(min_length=1, max_length=240)
    operation_id: str = Field(min_length=1, max_length=240)
    asset_id: str = Field(min_length=1, max_length=240)
    quantity: int = Field(ge=0)
    lot_ids: tuple[str, ...] = Field(min_length=1)
    status: str = Field(min_length=1, max_length=80)
    relationship_state: RelationshipState
    source_refs: tuple[str, ...] = Field(min_length=1)


class AlternativeResourceCapacity(FrozenModel):
    resource_id: str = Field(min_length=1, max_length=240)
    operation_ids: tuple[str, ...] = Field(min_length=1)
    compatible_product_ids: tuple[str, ...] = Field(min_length=1)
    available_from: datetime
    available_to: datetime
    gross_capacity_units: int = Field(ge=0)
    setup_minutes: int = Field(ge=0)
    net_transferable_units: int = Field(ge=0)
    relationship_state: RelationshipState
    source_refs: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_window_and_capacity(self) -> AlternativeResourceCapacity:
        _require_aware(self.available_from, "available_from")
        _require_aware(self.available_to, "available_to")
        if self.available_from >= self.available_to:
            raise ValueError("available_from must be before available_to")
        if self.net_transferable_units > self.gross_capacity_units:
            raise ValueError(
                "net_transferable_units must not exceed gross_capacity_units"
            )
        return self


class ProductionDecisionContext(FrozenModel):
    source_classification: str = Field(min_length=1, max_length=120)
    production_orders: tuple[ProductionOrder, ...]
    wip: tuple[WipRecord, ...]
    alternative_resources: tuple[AlternativeResourceCapacity, ...]
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_relationships(self) -> ProductionDecisionContext:
        orders = {order.order_id: order for order in self.production_orders}
        for item in self.wip:
            order = orders.get(item.order_id)
            if order is None:
                raise ValueError(f"WIP {item.wip_id} references unknown order")
            if item.operation_id != order.operation_id:
                raise ValueError(
                    f"WIP {item.wip_id} operation must match its order"
                )

        order_products = {order.product_id for order in self.production_orders}
        order_operations = {order.operation_id for order in self.production_orders}
        for resource in self.alternative_resources:
            if not set(resource.operation_ids).intersection(order_operations):
                raise ValueError(
                    f"alternative resource {resource.resource_id} has no matching operation"
                )
            if not set(resource.compatible_product_ids).intersection(order_products):
                raise ValueError(
                    f"alternative resource {resource.resource_id} has no matching product"
                )
        return self


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")

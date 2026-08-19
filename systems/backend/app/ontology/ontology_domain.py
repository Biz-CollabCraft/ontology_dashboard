"""Minimal canonical Ontology record contracts used by Infra projections.

The full Ontology migration owns the broader registry/action surface.  Runtime
projection only needs the stable persisted Object/Link record shapes here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ObjectRecord(BaseModel):
    id: str
    object_type: str
    workspace_id: str
    properties: dict[str, Any]
    source_refs: list[str] = Field(default_factory=list)
    version: int = 1


class LinkRecord(BaseModel):
    id: str
    link_type: str
    source_object_id: str
    target_object_id: str
    workspace_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    version: int = 1


__all__ = ["LinkRecord", "ObjectRecord"]

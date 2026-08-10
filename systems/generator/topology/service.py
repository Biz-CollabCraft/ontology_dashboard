"""Validate source-provided asset relations before semantic topology use."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


REQUIRED_RELATION_FIELDS = ("source_asset_id", "relationship_type", "target_asset_id")


def normalize_relation(relation: Mapping[str, Any]) -> dict[str, str]:
    """Return a stable relation record; causal meaning is never inferred here."""

    missing = [field for field in REQUIRED_RELATION_FIELDS if not relation.get(field)]
    if missing:
        raise ValueError(f"asset relation is missing required fields: {missing}")
    return {field: str(relation[field]) for field in REQUIRED_RELATION_FIELDS}


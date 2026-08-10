"""Normalize source observations without generating or mutating source data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extract_observation(row: Mapping[str, Any], required_fields: tuple[str, ...]) -> dict[str, Any]:
    """Return the requested source fields and fail when the source contract is incomplete."""

    missing = [field for field in required_fields if field not in row]
    if missing:
        raise ValueError(f"source observation is missing required fields: {missing}")
    return {field: row[field] for field in required_fields}


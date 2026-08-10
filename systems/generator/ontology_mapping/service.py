"""Map extracted source fields onto stable semantic property identifiers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def map_observation(observation: Mapping[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    """Map source field names to semantic names while preserving values exactly."""

    unknown = [field for field in observation if field not in mapping]
    if unknown:
        raise ValueError(f"semantic mapping is missing source fields: {unknown}")
    return {mapping[field]: value for field, value in observation.items()}


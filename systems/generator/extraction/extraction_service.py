"""Compatibility facade for legacy extraction_service imports.

.. deprecated::
    Use `systems.generator.app.extraction.extraction_service` instead.
"""

from __future__ import annotations

from systems.generator.app.extraction.extraction_service import (
    extract_with_plan,
    load_all_sources,
    get_last_plans,
    SUPPORTED_EXTENSIONS,
)

__all__ = [
    "extract_with_plan",
    "load_all_sources",
    "get_last_plans",
    "SUPPORTED_EXTENSIONS",
]

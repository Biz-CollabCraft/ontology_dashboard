"""Compatibility facade for legacy extraction_cache imports.

.. deprecated::
    Use `systems.generator.app.extraction.extraction_repository` or `extraction_planner` instead.
"""

from __future__ import annotations

from systems.generator.app.extraction.extraction_planner import ExtractionPlanner
from systems.generator.app.extraction.extraction_repository import ExtractionRepository

_default_planner = ExtractionPlanner()
_default_repo = ExtractionRepository()


def compute_fingerprint(df_preview) -> str:
    return _default_planner.compute_fingerprint(df_preview)


def load_plan_cache() -> dict:
    # return empty or find
    return {}


def save_plan_cache(cache: dict) -> None:
    pass


__all__ = [
    "compute_fingerprint",
    "load_plan_cache",
    "save_plan_cache",
]

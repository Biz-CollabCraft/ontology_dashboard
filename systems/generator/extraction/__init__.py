"""Compatibility facade for legacy extraction package imports.

.. deprecated::
    Use `systems.generator.app.preprocessing` instead.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from systems.generator.app.preprocessing.preprocessing_service import (
    load_all_sources,
    preprocess_with_plan as extract_with_plan,
)
from systems.generator.app.preprocessing.preprocessing_profiler import build_family_registry
from systems.generator.app.preprocessing.preprocessing_planner import PreprocessingPlanner as ExtractionPlanner

_default_planner = ExtractionPlanner()


def build_extraction_plan(filepath: str, force_reanalyze: bool = False) -> dict:
    return _default_planner.build_plan(filepath, force_reanalyze=force_reanalyze)


__all__ = ["load_all_sources", "extract_with_plan", "build_extraction_plan", "build_family_registry"]

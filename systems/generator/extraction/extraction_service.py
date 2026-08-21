"""Compatibility facade for legacy extraction_service imports.

.. deprecated::
    Use `systems.generator.app.preprocessing.preprocessing_service` instead.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from systems.generator.app.preprocessing.preprocessing_service import (
    preprocess_with_plan as extract_with_plan,
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

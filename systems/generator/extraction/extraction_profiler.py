"""Compatibility facade for legacy extraction_profiler imports.

.. deprecated::
    Use `systems.generator.app.preprocessing.preprocessing_profiler` instead.
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from systems.generator.app.preprocessing.preprocessing_profiler import (
    build_family_registry,
    load_family_registry,
    profile_source_file_with_llm,
    compute_family_id,
    infer_key_signature,
    FAMILY_REGISTRY_PATH,
)

__all__ = [
    "build_family_registry",
    "load_family_registry",
    "profile_source_file_with_llm",
    "compute_family_id",
    "infer_key_signature",
    "FAMILY_REGISTRY_PATH",
]

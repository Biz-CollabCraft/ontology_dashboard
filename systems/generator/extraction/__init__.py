"""Source-consumer extraction package.

Source generation remains owned by Biz-CollabCraft/gen_data. This package only
consumes and normalizes source observations after they cross that boundary.
"""

from .extraction_agent import ExtractionAgent
from .extraction_cache import ExtractionCache
from .extraction_service import ExtractionService, extract_observation

__all__ = ["ExtractionAgent", "ExtractionCache", "ExtractionService", "extract_observation"]

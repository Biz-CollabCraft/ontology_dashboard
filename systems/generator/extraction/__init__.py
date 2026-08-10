"""Source-consumer extraction helpers.

Source generation remains owned by Biz-CollabCraft/gen_data. This package only
normalizes source observations that have already crossed that repository boundary.
"""

from .service import extract_observation

__all__ = ["extract_observation"]


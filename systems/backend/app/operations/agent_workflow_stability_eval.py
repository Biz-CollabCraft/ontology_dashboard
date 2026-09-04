"""Deprecated compatibility import for evaluation-only stability contracts.

Product runtime must not depend on this module. New evaluation code lives under
scripts.eval_support.
"""

from scripts.eval_support.agent_workflow_stability import (  # noqa: F401
    RUN_STATUSES,
    aggregate_stability_evaluation,
    measurement,
    stability_evaluation_row,
)

__all__ = [
    "RUN_STATUSES",
    "aggregate_stability_evaluation",
    "measurement",
    "stability_evaluation_row",
]

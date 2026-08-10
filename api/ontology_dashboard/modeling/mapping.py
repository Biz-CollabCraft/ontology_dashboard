"""Compatibility port for generator-owned ontology mapping.

The product API keeps these callables so the existing ML Validator/workbench
contract does not break during PR #9. Generator implementation is resolved only
when an authoring operation is invoked; backend startup therefore does not take
a hard runtime dependency on the sibling generator package.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol


CAPABILITY_PREREQUISITES = {
    "predictive_training": ("group_key", "timestamp", "measure", "label"),
    "predictive_scoring": ("group_key", "timestamp", "measure"),
    "maintenance_context": ("equipment_identifier", "maintenance_reference"),
    "replay_time_series": ("group_key", "timestamp", "measure"),
    "explanation": ("group_key", "timestamp", "measure"),
}


class MappingLLMProvider(Protocol):
    def generate_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]: ...


def _implementation():
    try:
        return import_module("systems.generator.ontology_mapping.workbench")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "generator ontology-mapping adapter is unavailable; run this authoring operation "
            "in the generator-capable deployment"
        ) from exc


def evaluate_capabilities(*args, **kwargs):
    return _implementation().evaluate_capabilities(*args, **kwargs)


def generate_mapping_set(*args, **kwargs):
    return _implementation().generate_mapping_set(*args, **kwargs)


def registered_target(*args, **kwargs):
    return _implementation().registered_target(*args, **kwargs)


def update_candidate(*args, **kwargs):
    return _implementation().update_candidate(*args, **kwargs)


def validate_mapping_set_for_approval(*args, **kwargs):
    return _implementation().validate_mapping_set_for_approval(*args, **kwargs)


__all__ = [
    "CAPABILITY_PREREQUISITES",
    "MappingLLMProvider",
    "evaluate_capabilities",
    "generate_mapping_set",
    "registered_target",
    "update_candidate",
    "validate_mapping_set_for_approval",
]

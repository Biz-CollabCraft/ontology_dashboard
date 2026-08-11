"""Compatibility port for generator-owned feature engineering."""

from __future__ import annotations

from importlib import import_module


FEATURE_ENGINE_VERSION = "ontology-feature-engine-v1"
FEATURE_PREFIX = "feature__"
ALLOWED_DERIVED_INPUTS = {
    "power_w": ("torque_nm", "rotational_speed_rpm"),
    "temperature_gap_k": ("process_temperature_k", "air_temperature_k"),
    "overstrain_load": ("tool_wear_min", "torque_nm"),
}


def _implementation():
    try:
        return import_module("systems.generator.feature.workbench")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "generator feature adapter is unavailable; run this authoring operation "
            "in the generator-capable deployment"
        ) from exc


def approved_property_mapping(*args, **kwargs):
    return _implementation().approved_property_mapping(*args, **kwargs)


def canonicalize_frame(*args, **kwargs):
    return _implementation().canonicalize_frame(*args, **kwargs)


def materialize_feature_dataset(*args, **kwargs):
    return _implementation().materialize_feature_dataset(*args, **kwargs)


def read_source_for_profile(*args, **kwargs):
    return _implementation().read_source_for_profile(*args, **kwargs)


def transform_frame(*args, **kwargs):
    return _implementation().transform_frame(*args, **kwargs)


def validate_recipe(*args, **kwargs):
    return _implementation().validate_recipe(*args, **kwargs)


def validate_recipe_set(*args, **kwargs):
    return _implementation().validate_recipe_set(*args, **kwargs)


def __getattr__(name: str):
    if name == "FeatureMaterializationResult":
        return getattr(_implementation(), name)
    raise AttributeError(name)


__all__ = [
    "ALLOWED_DERIVED_INPUTS",
    "FEATURE_ENGINE_VERSION",
    "FEATURE_PREFIX",
    "FeatureMaterializationResult",
    "approved_property_mapping",
    "canonicalize_frame",
    "materialize_feature_dataset",
    "read_source_for_profile",
    "transform_frame",
    "validate_recipe",
    "validate_recipe_set",
]

"""Compatibility port for generator-owned model experiments/training."""

from __future__ import annotations

from importlib import import_module


EXPERIMENT_ENGINE_VERSION = "predictive-experiment-runner-v1"
REQUIRED_ALGORITHMS = ("dummy_prior", "logistic_regression", "random_forest")
OPTIONAL_ALGORITHMS = ("lightgbm", "xgboost")


def _implementation():
    try:
        return import_module("systems.generator.model.experiments")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "generator experiment adapter is unavailable; run this training operation "
            "in the generator-capable deployment"
        ) from exc


def build_candidate(*args, **kwargs):
    return _implementation().build_candidate(*args, **kwargs)


def calibration_rows(*args, **kwargs):
    return _implementation().calibration_rows(*args, **kwargs)


def dependency_capabilities(*args, **kwargs):
    return _implementation().dependency_capabilities(*args, **kwargs)


def evaluation_curves(*args, **kwargs):
    return _implementation().evaluation_curves(*args, **kwargs)


def metric_set(*args, **kwargs):
    return _implementation().metric_set(*args, **kwargs)


def run_experiment(*args, **kwargs):
    return _implementation().run_experiment(*args, **kwargs)


def runtime_versions(*args, **kwargs):
    return _implementation().runtime_versions(*args, **kwargs)


def slice_metrics(*args, **kwargs):
    return _implementation().slice_metrics(*args, **kwargs)


def split_feature_frame(*args, **kwargs):
    return _implementation().split_feature_frame(*args, **kwargs)


def threshold_curve(*args, **kwargs):
    return _implementation().threshold_curve(*args, **kwargs)


def __getattr__(name: str):
    if name == "SplitFrames":
        return getattr(_implementation(), name)
    raise AttributeError(name)


__all__ = [
    "EXPERIMENT_ENGINE_VERSION",
    "OPTIONAL_ALGORITHMS",
    "REQUIRED_ALGORITHMS",
    "SplitFrames",
    "build_candidate",
    "calibration_rows",
    "dependency_capabilities",
    "evaluation_curves",
    "metric_set",
    "run_experiment",
    "runtime_versions",
    "slice_metrics",
    "split_feature_frame",
    "threshold_curve",
]

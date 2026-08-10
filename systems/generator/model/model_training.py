"""Generator-owned model training facade.

The PR #10 scaffold keeps ``ModelTraining`` as the public system surface while
the imported PR #9 implementation remains lazily loaded so architecture smoke
checks can import the package before optional ML dependencies are installed.
"""

from __future__ import annotations


class ModelTraining:
    """Facade for offline training/evaluation owned by the generator system."""

    @staticmethod
    def train_and_evaluate(*args, **kwargs):
        from .training_impl import train_and_evaluate as implementation

        return implementation(*args, **kwargs)


def train_and_evaluate(*args, **kwargs):
    from .training_impl import train_and_evaluate as implementation

    return implementation(*args, **kwargs)


def __getattr__(name: str):
    if name in {"ALL_FEATURES", "BASE_FEATURES", "DERIVED_FEATURES"}:
        from . import training_impl

        return getattr(training_impl, name)
    raise AttributeError(name)


__all__ = ["ALL_FEATURES", "BASE_FEATURES", "DERIVED_FEATURES", "ModelTraining", "train_and_evaluate"]

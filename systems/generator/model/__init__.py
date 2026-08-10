"""Model training/evaluation and immutable Model Artifact publication."""

from .model_registry import ModelRegistry, publish_model_artifact, train_and_publish_model, validate_manifest
from .model_training import ModelTraining


def __getattr__(name: str):
    if name == "train_and_evaluate":
        from .model_training import train_and_evaluate

        return train_and_evaluate
    raise AttributeError(name)


__all__ = [
    "ModelRegistry",
    "ModelTraining",
    "publish_model_artifact",
    "train_and_evaluate",
    "train_and_publish_model",
    "validate_manifest",
]

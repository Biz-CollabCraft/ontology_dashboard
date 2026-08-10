"""Feature engineering package owned by the generator system."""

from .feature_builder import FeatureBuilder
from .feature_catalog import FeatureCatalog


def __getattr__(name: str):
    if name in {"DatasetAudit", "audit_ai4i", "canonicalize", "load_ai4i"}:
        from . import dataset

        return getattr(dataset, name)
    raise AttributeError(name)


__all__ = [
    "DatasetAudit",
    "FeatureBuilder",
    "FeatureCatalog",
    "audit_ai4i",
    "canonicalize",
    "load_ai4i",
]

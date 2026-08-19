"""Legacy compatibility export for canonical predictive-maintenance projection."""

from app.infra.db.predictive_maintenance_ontology_projection import (
    DEFAULT_MAPPING,
    DEFAULT_MAPPING_VERSION,
    PredictiveMaintenanceMaterializationResult,
    PredictiveMaintenanceOntologyMaterializer,
    SOURCE_SYSTEM,
)

__all__ = [
    "DEFAULT_MAPPING",
    "DEFAULT_MAPPING_VERSION",
    "PredictiveMaintenanceMaterializationResult",
    "PredictiveMaintenanceOntologyMaterializer",
    "SOURCE_SYSTEM",
]

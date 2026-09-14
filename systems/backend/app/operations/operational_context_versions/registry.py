"""Dispatch by persisted contract identity, never by the newest application model."""
import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from . import v1, v2

MODELS = {
    'production': v1.ProductionDecisionContext,
    'maintenance_readiness': v1.MaintenanceReadinessContext,
    'quality_delivery': v1.QualityDeliveryContext,
    'impact_policy': v1.ImpactSimulationAssumptions,
}


@lru_cache(maxsize=1)
def planning_validator():
    root = Path(__file__).resolve().parents[5]
    schema = json.loads((root / 'contracts/schemas/operational-context-planning-v1.schema.json').read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_planning(payload):
    planning_validator().validate(payload)


VALIDATORS = {
    (f'operational-context.{domain}', 1): model.model_validate
    for domain, model in MODELS.items()
}
VALIDATORS[('operational-context.production', 2)] = v2.SupplyProductionContext.model_validate
VALIDATORS[('operational-context.planning', 1)] = validate_planning


def validate_payload(schema_id, schema_version, payload):
    validator = VALIDATORS.get((schema_id, schema_version))
    if validator is None:
        raise ValueError(f'unsupported operational schema: {schema_id} v{schema_version}')
    # Validation does not rewrite persisted bytes or fill in new application defaults.
    validator(payload)

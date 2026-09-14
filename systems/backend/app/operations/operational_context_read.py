"""Read contract for the shared evidence side view; no workflow commands."""
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.operations.operational_context_contract import (
    FrozenModel, OperationalContextEnvelope, OperationalRequestIdentity,
)
from app.operations.operational_impact_simulation import ImpactSimulationResult


class ContextSourceProvenance(FrozenModel):
    source_context_id: str
    schema_id: str
    schema_version: int
    source_classification: Literal['synthetic_demo_context', 'owner_system']
    valid_from: datetime
    valid_to: datetime
    source_sha256: str
    binding_sha256: str
    bound_evidence_snapshot_id: str | None


class ContextReadItem(FrozenModel):
    context: OperationalContextEnvelope
    provenance: ContextSourceProvenance | None
    reason_codes: tuple[str, ...] = ()


class OperationalContextRead(FrozenModel):
    schema_version: Literal['operational-context-read-v1'] = 'operational-context-read-v1'
    identity: OperationalRequestIdentity
    retrieved_at: datetime
    context_fingerprint: str
    domains: dict[str, ContextReadItem]
    production_impact: ImpactSimulationResult
    limitations: tuple[str, ...] = Field(default=(
        'Conditional production comparison is not realized loss or production recovery.',
        'Inspection downtime estimates are not substituted for capacity policy inputs.',
        'Schedule agreement, maintenance authorization and work start remain separate owner records.',
    ))

"""Supply-dependent production view; v1 remains asset-local and immutable."""
from typing import Literal
from pydantic import Field, model_validator
from .v1 import FrozenModel, ProductionDecisionContext

class SupplyEdge(FrozenModel):
    from_asset_id: str
    to_asset_id: str
    relation_type: Literal['SUPPLIES_AIR_TO']
    source_sha256: str = Field(min_length=1)

class SupplyBasis(FrozenModel):
    dataset_version_id: str = Field(min_length=1)
    evidence_snapshot_id: str = Field(min_length=1)
    edges: tuple[SupplyEdge,...] = Field(min_length=1)
    assumptions: tuple[str,...] = Field(min_length=1)

class SupplyProductionContext(ProductionDecisionContext):
    supply_basis: SupplyBasis

    @model_validator(mode='after')
    def connected_targets_only(self):
        targets={e.to_asset_id for e in self.supply_basis.edges}
        if len(targets)!=len(self.supply_basis.edges):raise ValueError('duplicate supply edges')
        if any(o.assigned_asset_id not in targets for o in self.production_orders):raise ValueError('order outside supply targets')
        if any(w.asset_id not in targets for w in self.wip):raise ValueError('WIP outside supply targets')
        return self

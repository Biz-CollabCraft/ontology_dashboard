"""Reject explicit contradictory maintenance planning signals."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from app.operations.operational_domain_schema import MaintenanceWindow, PartInventorySnapshot


@pytest.mark.parametrize('model,key,updates,message', [
    (MaintenanceWindow, 'maintenance_windows',
     {'active_work_order_conflict': True, 'suitability': 'suitable'}, 'conflicting maintenance window'),
    (MaintenanceWindow, 'maintenance_windows',
     {'suitability': 'unsuitable', 'conflict_reason': None}, 'requires conflict_reason'),
    (PartInventorySnapshot, 'inventory_snapshots',
     {'on_hand_quantity': 2, 'reserved_quantity': 1, 'available_quantity': 1,
      'reservation_state': 'fully_reserved'}, 'fully_reserved requires'),
    (PartInventorySnapshot, 'inventory_snapshots',
     {'on_hand_quantity': 2, 'reserved_quantity': 1, 'available_quantity': 1,
      'reservation_state': 'unavailable'}, 'unavailable reservation_state requires'),
])
def test_contradictory_explicit_signals_are_rejected(model, key, updates, message):
    path = Path(__file__).resolve().parents[1] / 'data/fixtures/operation_context/maintenance-readiness-context-v1.json'
    data = json.loads(path.read_text())[key][0]
    data.update(updates)
    with pytest.raises(ValidationError, match=message):
        model.model_validate(data)

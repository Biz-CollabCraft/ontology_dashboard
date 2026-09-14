"""Planning context projection helpers for Operations services.

This module depends only on the Operations context contract. The repository is
provided as a read port by the application dependency layer.
"""

from __future__ import annotations

from typing import Any

from app.operations.operational_context_contract import OperationalRequestIdentity


def planning_context(repository: Any, identity: OperationalRequestIdentity) -> dict[str, Any]:
    envelope = repository.lookup("planning", identity=identity, retrieved_at=identity.decision_as_of)
    if not envelope.data:
        return {
            "load_level": None,
            "runtime_hours_7d": None,
            "production_impact": None,
            "limitations": list(envelope.limitations),
        }
    return {**envelope.data, "limitations": list(envelope.limitations)}

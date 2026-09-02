import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.mvp.operational_context_contract import (
    OperationalContextStatus,
    OperationalRequestIdentity,
    require_matching_scope,
)
from app.mvp.operational_context_ports import FixtureProductionContextReadPort


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (
        ROOT
        / "data"
        / "fixtures"
        / "operation_context"
        / "production-planning-context-v1.json"
    ).read_text(encoding="utf-8")
)


def identity(
    *,
    asset_id: str = "CNC-S04-L02-03",
    as_of: datetime = datetime(2026, 8, 1, 1, tzinfo=timezone.utc),
) -> OperationalRequestIdentity:
    return OperationalRequestIdentity(
        organization_id="ORG-001",
        project_id="manufacturing-demo-project",
        workspace_id="manufacturing-demo",
        asset_id=asset_id,
        evidence_snapshot_id="ARTIFACT-GS-004",
        decision_as_of=as_of,
    )


def port(max_age_seconds: int = 86_400) -> FixtureProductionContextReadPort:
    return FixtureProductionContextReadPort(
        context=FIXTURE,
        organization_id="ORG-001",
        workspace_id="manufacturing-demo",
        source_ref=(
            "data/fixtures/operation_context/"
            "production-planning-context-v1.json"
        ),
        max_age_seconds=max_age_seconds,
    )


def test_fixture_port_returns_versioned_synthetic_context() -> None:
    result = port().lookup(
        identity=identity(),
        retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
    )

    require_matching_scope(identity(), result)
    assert result.status is OperationalContextStatus.AVAILABLE
    assert result.source_version == "OPS-SNAPSHOT-2026-08-01-A-B"
    assert result.data["source_type"] == "synthetic_capacity_model"
    assert result.data["event_impact"]["event_id"] == "EVT-GS-004"


def test_fixture_port_does_not_invent_order_wip_or_alternative_records() -> None:
    result = port().lookup(
        identity=identity(),
        retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
    )

    assert result.data["production_orders"] == []
    assert result.data["wip"] == []
    assert result.data["alternative_resources"] == []
    assert result.data["availability"] == {
        "production_orders": "not_connected",
        "wip": "not_connected",
        "alternative_resources": "not_connected",
    }


def test_out_of_window_context_is_stale_and_carries_no_domain_data() -> None:
    result = port().lookup(
        identity=identity(
            as_of=datetime(2026, 9, 2, 10, tzinfo=timezone.utc)
        ),
        retrieved_at=datetime(2026, 9, 2, 10, 1, tzinfo=timezone.utc),
    )

    assert result.status is OperationalContextStatus.STALE
    assert result.data == {}
    assert any("outside the fixture validity window" in item for item in result.limitations)


def test_freshness_expiry_is_stale_even_inside_fixture_window() -> None:
    result = port(max_age_seconds=60).lookup(
        identity=identity(),
        retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
    )

    assert result.status is OperationalContextStatus.STALE
    assert result.data == {}
    assert any("freshness policy" in item for item in result.limitations)


def test_missing_asset_impact_remains_explicit_without_fake_zero() -> None:
    result = port().lookup(
        identity=identity(asset_id="CNC-UNKNOWN"),
        retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
    )

    assert result.status is OperationalContextStatus.AVAILABLE
    assert result.data["event_impact"] is None
    assert any("No event impact" in item for item in result.limitations)


def test_configured_scope_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="configured scope mismatch"):
        port().lookup(
            identity=identity().model_copy(
                update={"workspace_id": "other-workspace"}
            ),
            retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
        )

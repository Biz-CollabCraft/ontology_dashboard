import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.mvp.operational_context_contract import (
    OperationalContextStatus,
    OperationalRequestIdentity,
    require_matching_scope,
)
from app.mvp.operational_context_ports import (
    FixtureProductionContextReadPort,
    FixtureProductionDecisionContextReadPort,
)


ROOT = Path(__file__).resolve().parents[1]
DECISION_FIXTURE = json.loads(
    (
        ROOT
        / "data"
        / "fixtures"
        / "operation_context"
        / "operational-decision-context-v1.json"
    ).read_text(encoding="utf-8")
)
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


def decision_port() -> FixtureProductionDecisionContextReadPort:
    return FixtureProductionDecisionContextReadPort(
        context=DECISION_FIXTURE,
        source_ref=(
            "data/fixtures/operation_context/"
            "operational-decision-context-v1.json"
        ),
    )


def test_decision_port_links_order_wip_and_alternative_capacity() -> None:
    requested = identity(
        as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc)
    )
    result = decision_port().lookup(
        identity=requested,
        retrieved_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
    )

    require_matching_scope(requested, result)
    assert result.status is OperationalContextStatus.AVAILABLE
    assert result.source_version == "OPS-DECISION-SNAPSHOT-2026-09-02-01"
    assert result.data["source_classification"] == "synthetic_demo_context"
    assert result.data["production_orders"][0]["order_id"] == "DEMO-PO-001"
    assert result.data["wip"][0]["quantity"] == 200
    assert result.data["wip"][0]["lot_ids"] == [
        "DEMO-LOT-014",
        "DEMO-LOT-015",
    ]
    assert (
        result.data["alternative_resources"][0]["net_transferable_units"]
        == 50
    )


def test_decision_port_filters_context_by_requested_asset() -> None:
    requested = identity(
        asset_id="CNC-UNKNOWN",
        as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc),
    )
    result = decision_port().lookup(
        identity=requested,
        retrieved_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
    )

    assert result.data["production_orders"] == []
    assert result.data["wip"] == []
    assert result.data["alternative_resources"] == []
    assert any("No production order" in item for item in result.limitations)


def test_decision_port_rejects_broken_wip_relationship() -> None:
    broken = json.loads(json.dumps(DECISION_FIXTURE))
    broken["wip"][0]["order_id"] = "UNKNOWN"
    adapter = FixtureProductionDecisionContextReadPort(
        context=broken,
        source_ref="broken",
    )

    with pytest.raises(ValueError, match="references unknown order"):
        adapter.lookup(
            identity=identity(
                as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc)
            ),
            retrieved_at=datetime(2026, 9, 2, 2, tzinfo=timezone.utc),
        )


def test_configured_scope_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="configured scope mismatch"):
        port().lookup(
            identity=identity().model_copy(
                update={"workspace_id": "other-workspace"}
            ),
            retrieved_at=datetime(2026, 8, 1, 2, tzinfo=timezone.utc),
        )

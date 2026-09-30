"""Opt-in, read-only workflow smoke against an already running local API."""
import os
from urllib.parse import quote
import httpx
import pytest
from app.identity.identity_schema import DEMO_ACCOUNTS

@pytest.mark.skipif(not os.getenv("DECISION_LIVE_API"), reason="requires explicit running local API")
@pytest.mark.parametrize("role", ["process_manager", "process_engineer"])
def test_live_detail_has_scoped_workflow_and_measured_history(role):
    base = os.environ["DECISION_LIVE_API"]
    assert base.startswith("http://127.0.0.1:")
    account = next(a for a in DEMO_ACCOUNTS if a["roles"] == [role])
    with httpx.Client(base_url=base, timeout=30) as client:
        login = client.post("/api/auth/login", json={k: account[k] for k in ("email", "password")})
        login.raise_for_status()
        project, workspace = "manufacturing-demo-project", "manufacturing-demo"
        results = client.get(f"/api/projects/{project}/workspaces/{workspace}/predictive-maintenance/results/latest", params={"limit":100})
        results.raise_for_status()
        row = next(r for r in results.json()["items"] if r["asset_id"] == "CNC-S04-L02-03")
        asset = row["asset_id"]
        event = row["artifact_id"]
        response = client.get(f"/api/objects/{quote(asset, safe='')}/detail-view", params={
            "project_id":project, "workspace_id":workspace, "event_id":event,
            "dataset_version_id":row["provenance"]["dataset_version_id"], "history_window":"24h",
        })
        response.raise_for_status()
        detail=response.json()
        assert detail["snapshot_basis"]["asset_id"] == asset
        assert detail["closed_loop"]["lifecycle_summary"]["current_step"]
        assert isinstance(detail["closed_loop"]["available_actions"], list)
        assert detail["risk_series"]
        if detail["data_status"]["source"] == "fallback":
            assert detail["data_status"]["is_data_quality_hold"] is True
            assert not detail["closed_loop"]["available_actions"]
            assert detail["snapshot_basis"]["source_sha256"] is None
            assert any(g["field"] == "canonical_evidence" for g in detail["evidence"]["gaps"])
        if role == "process_engineer":
            assert all(a["disabled_reason"] for a in detail["closed_loop"]["available_actions"]
                       if a["action_id"] == "request_inspection_work_order")
        print(f"source={detail['data_status']['source']}; {role}: latest={len(results.json()['items'])}, phase={detail['closed_loop']['lifecycle_summary']['current_step']}, history={len(detail['risk_series'])}")

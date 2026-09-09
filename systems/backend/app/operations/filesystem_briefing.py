"""Adapt exact demo file observations through the existing artifact contract."""
from app.operations.asset_detail_view_model import compose_asset_detail_view_model
from app.operations.agent_review_packet import compose_agent_review_packet
from datetime import datetime
from app.operations.operational_context_contract import OperationalRequestIdentity
from app.operations.operational_planning_context import planning_context


def filesystem_briefing_packet(*, asset_id, event_id, dataset_version_id, project_id, history_window,
    service=None, organization_id="org-ontology-demo", workspace_id="manufacturing-demo"):
    from app.diagnosis.runtime_router import _latest_complete_file_tick, _filesystem_event_artifact
    if project_id != "manufacturing-demo-project" or not event_id.startswith("FILE#"):
        raise KeyError(event_id)
    stream, latest_at, records, complete_ticks = _latest_complete_file_tick()
    run_id = stream.parents[1].name
    if dataset_version_id and dataset_version_id != run_id:
        raise KeyError(event_id)
    ticks = complete_ticks or [(latest_at, {str(row["asset_id"]): row for row in records})]
    for observed_at, rows in reversed(ticks):
        record = rows.get(asset_id)
        if not record:
            continue
        expected = f"FILE#{run_id}#{record.get('observation_id', asset_id)}"
        if expected != event_id:
            continue
        artifact = _filesystem_event_artifact(run_id=run_id, observed_at=observed_at, record=record, event_id=event_id)
        for rank, factor in enumerate(artifact.get("top_factors", []), 1):
            factor.setdefault("rank", rank)
            factor.setdefault("explanation_method", "filesystem-risk-policy-v1")
        view = compose_asset_detail_view_model(
            asset={"asset_id": asset_id, "asset_type": artifact["asset_type"], "display_name": asset_id},
            result_artifact=artifact, event_id=event_id, history_window=history_window,
            closed_loop=service._closed_loop_context_for_fixture({"event_id":event_id}) if service is not None else None,
        )
        if service is not None:
            identity = OperationalRequestIdentity(
                organization_id=organization_id, project_id=project_id, workspace_id=workspace_id,
                asset_id=asset_id, evidence_snapshot_id=event_id,
                decision_as_of=datetime.fromisoformat(observed_at.replace("Z", "+00:00")),
            )
            repository = service.operational_context_repository.capture(identity)
            view["operation_context"] = planning_context(repository, identity)
            view["evidence_context"] = service.evidence_context_for_snapshot(
                asset_id=asset_id, artifact={"artifact_id":event_id,"observed_at":observed_at},
                project_id=project_id, event_id=event_id, organization_id=organization_id,
                workspace_id=workspace_id, context_repository=repository,
            )
        return compose_agent_review_packet(project_id=project_id, view_model=view,
            sop_retrieval={"provider": "runtime_product_result", "query": {"asset_id": asset_id, "event_id": event_id, "dataset_version_id": run_id}, "top_k": 0, "returned_count": 0, "results": []},
            context=service.agent_review_context_registry.context_for_packet(view_model=view)
                if service is not None and service.agent_review_context_registry else None)
    raise KeyError(event_id)

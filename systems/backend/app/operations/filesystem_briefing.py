"""Adapt exact demo file observations through the existing artifact contract."""
from app.operations.asset_detail_view_model import compose_asset_detail_view_model
from app.operations.agent_review_packet import compose_agent_review_packet
from datetime import datetime
from app.operations.operational_context_contract import OperationalRequestIdentity
from app.operations.operational_planning_context import planning_context
import csv
import json
import os
import re
from pathlib import Path
from functools import lru_cache
from app.operations.sop_retrieval import retrieve_inspection_sops


def _file_sops(view, artifact):
    root = Path(__file__).resolve().parents[4] / 'data/fixtures/inspection_sop'
    procedures = []
    for path in sorted(root.glob('*.json')):
        try:
            procedure = json.loads(path.read_text(encoding='utf-8'))
            if artifact['asset_type'] in procedure.get('asset_types', []):
                procedures.append(procedure)
        except (OSError, ValueError):
            continue
    retrieval = retrieve_inspection_sops(fixture={'equipment': {'asset_type': artifact['asset_type']}},
                                        artifact=artifact, procedures=procedures, top_k=3)
    targets = []
    for item in retrieval['results']:
        p = item['procedure']; g = p.get('guidance') or {}
        for component in p.get('component_ids') or []:
            targets.append({'target_id': p['sop_id'] + ':' + component,
                'component_id': component, 'component_label': component.replace('_', ' '),
                'location_label': g.get('reference_location_label'),
                'inspection_method': g.get('suggested_check_method'),
                'source_ref': item['source_ref'], 'location_source_ref': item['source_ref'],
                'inspection_guidance': {**g, 'sop_id': p['sop_id'],
                    'source_type': p.get('source_kind'), 'source_ref': item['source_ref']}})
    view['inspection_targets'] = targets
    return retrieval


def _archive_roots():
    roots = [Path('/home/bistell/gen_data/output')]
    if os.getenv('GEN_DATA_OUTPUT_ROOT'):
        roots.insert(0, Path(os.environ['GEN_DATA_OUTPUT_ROOT']))
    roots.extend(Path('/home/bistell/ontology_dashboard/data_preprocessed/local-realtime/sessions').glob('*/gen-data-runtime'))
    base = Path('/home/bistell/ontology_dashboard/data/demo-scenarios')
    roots.extend(base.glob('generated/*'))
    roots.extend(base.glob('scenario*'))
    return roots


@lru_cache(maxsize=128)
def _recorded_tick(stream_name, asset_id, event_id, run_id):
    stream = Path(stream_name)
    with (stream.parents[1]/'canonical/asset_master.csv').open(encoding='utf-8-sig', newline='') as handle:
        expected = {r['asset_id'] for r in csv.DictReader(handle)}
    at, rows, matched = None, {}, False
    with stream.open(encoding='utf-8') as handle:
        for line in handle:
            try:
                row = json.loads(line)
                current = row['observed_at']
                asset = row['asset_id']
            except (ValueError, KeyError):
                continue
            if current != at:
                if matched and expected and set(rows) == expected:
                    return at, rows
                at, rows, matched = current, {}, False
            rows[asset] = row
            matched = matched or (asset == asset_id and f"FILE#{run_id}#{row.get('observation_id', asset)}" == event_id)
    if matched and expected and set(rows) == expected:
        return at, rows
    raise KeyError(event_id)


def _bound_ticks(asset_id, event_id, dataset_version_id):
    from app.diagnosis.runtime_router import _latest_complete_file_tick
    parts = event_id.split('#', 2)
    if len(parts) != 3 or not re.fullmatch(r'[A-Za-z0-9_-]+', parts[1]):
        raise KeyError(event_id)
    run_id = parts[1]
    if dataset_version_id and dataset_version_id != run_id:
        raise KeyError(event_id)
    try:
        stream, latest_at, records, complete_ticks = _latest_complete_file_tick()
        if stream.parents[1].name == run_id:
            ticks = complete_ticks or [(latest_at, {str(row['asset_id']): row for row in records})]
            if any(f"FILE#{run_id}#{rows.get(asset_id, {}).get('observation_id', '')}" == event_id for _, rows in ticks):
                return run_id, ticks
    except (KeyError, OSError, ValueError):
        pass
    for root in _archive_roots():
        stream = root/'runs'/run_id/'source/sensor_records.jsonl'
        if not stream.is_file() or not stream.resolve().is_relative_to(root.resolve()):
            continue
        try:
            return run_id, [_recorded_tick(str(stream), asset_id, event_id, run_id)]
        except (KeyError, OSError, ValueError):
            continue
    raise KeyError(event_id)


def filesystem_briefing_packet(*, asset_id, event_id, dataset_version_id, project_id, history_window,
    service=None, organization_id="org-ontology-demo", workspace_id="manufacturing-demo"):
    from app.diagnosis.runtime_router import _latest_complete_file_tick, _filesystem_event_artifact
    if project_id != "manufacturing-demo-project" or not event_id.startswith("FILE#"):
        raise KeyError(event_id)
    run_id, ticks = _bound_ticks(asset_id, event_id, dataset_version_id)
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
        retrieval = _file_sops(view, artifact)
        return compose_agent_review_packet(project_id=project_id, view_model=view,
            sop_retrieval=retrieval,
            context=service.agent_review_context_registry.context_for_packet(view_model=view)
                if service is not None and service.agent_review_context_registry else None)
    raise KeyError(event_id)

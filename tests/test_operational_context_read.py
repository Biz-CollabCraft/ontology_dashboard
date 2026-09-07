import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.dependencies import get_operational_context_repository
from app.main import app
from app.operations.agent_review_packet import _closed_loop_record
from app.operations.operational_context_read import OperationalContextRead
from app.operations.agent_review_summary_materialization import _summary_context_sha256
from test_operational_context_repository import repository, snapshot, identity
from test_predictive_maintenance_postgresql import postgresql_database
from test_operational_decision_api import api_client, login, PARAMS, ASSET_ID

ROOT = Path(__file__).resolve().parents[1]


def test_read_view_preserves_validated_provenance_and_withholds_missing_impact(repository, snapshot):
    repository.import_snapshots([snapshot])
    i = identity(snapshot)
    view = repository.read_view(identity=i, retrieved_at=i.decision_as_of, risk_status='warning')
    item = view.domains['production']
    assert item.context.data == snapshot.payload
    assert item.provenance.source_classification == 'synthetic_demo_context'
    assert item.provenance.schema_version == 1
    assert item.provenance.bound_evidence_snapshot_id is None
    assert item.context.source_refs == (snapshot.source_ref,)
    assert view.context_fingerprint == repository.version_fingerprint(i)
    assert all(x.state == 'not_calculable' and x.remaining_exposed_units is None for x in view.production_impact.options)
    schema = json.loads((ROOT/'contracts/schemas/operational-context-read.schema.json').read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(view.model_dump(mode='json'))


def test_read_view_failure_does_not_expose_unvalidated_provenance(repository, snapshot, monkeypatch):
    repository.import_snapshots([snapshot])
    i = identity(snapshot)
    captured = repository.capture(i)
    captured.rows['production']['payload_json'] = '{}'
    view = captured.read_view(identity=i, retrieved_at=i.decision_as_of, risk_status='warning')
    item = view.domains['production']
    assert item.provenance is None and item.context.data == {}
    assert item.reason_codes == ('STORAGE_OR_CONTRACT_VALIDATION_FAILED',)


def test_read_view_stale_metadata_and_missing_scope(repository, snapshot):
    repository.import_snapshots([snapshot.model_copy(update={'max_age_seconds': 1})])
    i = identity(snapshot)
    stale = repository.read_view(identity=i, retrieved_at=i.decision_as_of, risk_status='warning').domains['production']
    assert stale.provenance is not None and not stale.context.data
    assert stale.reason_codes == ('FRESHNESS_POLICY_EXCEEDED',)
    other = i.model_copy(update={'workspace_id':'other'})
    missing = repository.read_view(identity=other, retrieved_at=other.decision_as_of, risk_status='warning').domains['production']
    assert missing.provenance is None and not missing.context.data
    assert missing.reason_codes == ('NO_MATCHING_SCOPE_SNAPSHOT_AT_AS_OF',)


def test_read_api_checks_identity_and_does_not_materialize(api_client, tmp_path):
    from app.infra.db.operational_context_repository import OperationalContextRepository
    from app.infra.db.migrations import migrate
    target = str(tmp_path/'read.db'); migrate(target)
    app.dependency_overrides[get_operational_context_repository] = lambda: OperationalContextRepository(target)
    client, service = api_client
    login(client, 'manager@ontology.local', 'Manager!2026')
    url = f'/api/objects/{ASSET_ID}/operational-context'
    response = client.get(url, params=PARAMS)
    assert response.status_code == 200, response.text
    view = OperationalContextRead.model_validate(response.json())
    assert all(not item.context.data for item in view.domains.values())
    assert client.get(url, params={**PARAMS,'evidence_snapshot_id':'wrong'}).status_code == 409
    assert client.get(url, params={**PARAMS,'decision_as_of':'2026-07-01T00:00:00+09:00'}).status_code == 409
    assert client.get(url, params={**PARAMS,'decision_as_of':'2026-08-01T00:00:00'}).status_code == 422
    assert service.workflow_runs(project_id=PARAMS['project_id'],asset_id=ASSET_ID,status=None,limit=10) == []


def test_owner_record_preserves_actor_time_and_references_without_inference():
    item = {'inspection_result_id':'IR-1', 'work_order_id':'WO-1', 'event_id':'E-1',
            'recorded_by':'technician-1', 'recorded_at':'2026-08-01T00:00:00Z', 'outcome':'normal'}
    original = copy.deepcopy(item)
    record = _closed_loop_record(item, source_prefix='closed-loop://inspection-result')
    assert item == original
    assert record['owner_record_provenance']['recorded_by'] == 'technician-1'
    assert record['owner_record_provenance']['work_order_id'] == 'WO-1'
    assert 'actor_id' not in record['owner_record_provenance']
    assert record['source_ref'] == 'closed-loop://inspection-result/IR-1'
    second = _closed_loop_record({**item, 'recorded_by':'technician-2'}, source_prefix='closed-loop://inspection-result')
    assert _summary_context_sha256({'maintenance_history_summary':record}) != _summary_context_sha256({'maintenance_history_summary':second})


def test_impact_rejects_different_asof_before_calculation():
    from test_operational_impact_simulation import contexts, IDENTITY, ASSUMPTIONS
    from app.operations.operational_impact_simulation import simulate_operational_impact
    values = contexts(clear_quality=True, ready_maintenance=True)
    values['production'] = values['production'].model_copy(update={'as_of': IDENTITY.decision_as_of + timedelta(seconds=1)})
    result = simulate_operational_impact(identity=IDENTITY,risk_status='warning',contexts=values,assumptions=ASSUMPTIONS)
    assert all(option.reason_codes == ('CONTEXT_AS_OF_MISMATCH:production',) for option in result.options)
    assert all(option.remaining_exposed_units is None for option in result.options)


def test_owner_provenance_reaches_packet_and_compact_provider(tmp_path):
    from app.dependencies import build_manufacturing_service
    from app.operations.agent_review_packet import compose_agent_review_packet
    from app.operations.agent_review_summary_provider import _compact_maintenance_history
    service = build_manufacturing_service(tmp_path/'packet.db',root=ROOT)
    view = service.asset_detail_view_model(ASSET_ID, PARAMS['project_id'])
    view['closed_loop']['inspection_results'] = [{
        'inspection_result_id':'IR-proof', 'work_order_id':'WO-proof',
        'event_id':PARAMS['evidence_snapshot_id'], 'recorded_by':'technician-proof',
        'recorded_at':'2026-08-01T00:00:00+09:00', 'outcome':'data_check_required',
    }]
    from app.operations.domain_context_adapters import ManufacturingFixtureReviewContextAdapter
    fixture = service._fixture_for_asset(ASSET_ID, PARAMS['project_id'])
    retrieval = ManufacturingFixtureReviewContextAdapter(ROOT).sop_retrieval(
        fixture=fixture, artifact=service._product_result_artifact(fixture))
    packet = compose_agent_review_packet(view_model=view,sop_retrieval=retrieval,project_id=PARAMS['project_id'])
    history = packet['maintenance_history_summary']
    item = history['inspection_results'][0]
    assert item['owner_record_provenance']['recorded_by'] == 'technician-proof'
    assert item['status'] == 'data_check_required'
    assert _compact_maintenance_history(history)['inspection_results'][0] == item
    schema = json.loads((ROOT/'contracts/schemas/agent-review-packet.schema.json').read_text())
    Draft202012Validator(schema).validate(packet)


def test_activity_actor_is_preserved_under_owner_field_name():
    from app.operations.context_providers import _history_record
    record = _history_record({'activity_id':'A-1','actor_user_id':'U-1',
        'actor_display_name':'Operator', 'created_at':'2026-08-01T00:00:00Z'},
        source_prefix='closed-loop://activity')
    assert record['owner_record_provenance']['actor_user_id'] == 'U-1'
    assert 'actor_id' not in record['owner_record_provenance']

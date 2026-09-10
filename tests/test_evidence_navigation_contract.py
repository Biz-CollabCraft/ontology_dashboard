"""Cross-record evidence navigation and mandatory-condition preservation."""
import pytest
from pydantic import ValidationError
from test_operational_relation_resolver import contexts, IDENTITY
from app.operations.operational_relation_resolver import resolve_operational_relations
from app.operations.operational_evidence_selection import (
    EvidenceRelationPath, EvidenceSelectionStrategy,
    project_evidence_candidates, select_evidence_candidates,
)
from app.operations.asset_detail_view_model import _evidence_context


def candidates():
    supplied = contexts()
    resolution = resolve_operational_relations(identity=IDENTITY, contexts=supplied)
    return supplied, resolution, project_evidence_candidates(
        identity=IDENTITY, contexts=supplied, relation_resolution=resolution,
    )


def test_delivery_evidence_has_contiguous_path_from_selected_asset():
    _, _, items = candidates()
    delivery = next(item for item in items if item.fact_type == 'delivery_commitments')
    assert delivery.relation_paths
    path = delivery.relation_paths[0]
    assert path.steps[0].source_id == IDENTITY.asset_id
    assert path.steps[-1].target_type == 'delivery_commitment'
    assert delivery.source_ref in path.steps[-1].source_refs
    assert len(path.steps) >= 3
    for left, right in zip(path.steps, path.steps[1:]):
        assert (left.target_type, left.target_id) == (right.source_type, right.source_id)
    projected = _evidence_context({'selected_basis': [delivery.model_dump(mode='json')]})
    assert projected['selected_basis'][0]['relation_paths'] == [path.model_dump(mode='json')]


def test_disconnected_path_cannot_be_constructed():
    _, _, items = candidates()
    path = next(path for item in items for path in item.relation_paths if len(path.steps) >= 3)
    broken = path.steps[1].model_copy(update={'source_id':'unrelated-order'})
    with pytest.raises(ValidationError, match='disconnected'):
        EvidenceRelationPath(steps=(path.steps[0], broken))


def test_other_event_resolution_cannot_be_used_for_current_evidence():
    supplied, resolution, _ = candidates()
    other = resolution.model_copy(update={'focus':{**resolution.focus,'evidence_snapshot_id':'another-event'}})
    with pytest.raises(ValueError, match='identity'):
        project_evidence_candidates(identity=IDENTITY, contexts=supplied, relation_resolution=other)


def test_required_conditions_with_same_source_survive_small_budget():
    _, _, items = candidates()
    base = items[0]
    conditions = [base.model_copy(update={
        'candidate_id':f'condition:{condition}', 'required_for_boundary':True,
        'value_summary':condition,
    }) for condition in ['parts unavailable','technician unavailable']]
    result = select_evidence_candidates(conditions, strategy=EvidenceSelectionStrategy.DETERMINISTIC, max_candidates=1)
    assert {item.candidate_id for item in result.selected} == {item.candidate_id for item in conditions}
    assert not result.rejected


def test_disconnected_action_is_not_presented_as_asset_path():
    _, _, items = candidates()
    action = next(item for item in items if item.fact_type == 'action_requires_part')
    assert not action.relation_paths


def test_same_document_records_keep_distinct_facts_and_matching_endpoints():
    from copy import deepcopy
    supplied = contexts()
    quality = supplied['quality_delivery']
    data = deepcopy(quality.data)
    for lot in data['quality_lots']:
        lot['source_refs'] = ['shared-quality-document']
        lot['release_required'] = True
    supplied['quality_delivery'] = quality.model_copy(update={'data': data})
    resolution = resolve_operational_relations(identity=IDENTITY, contexts=supplied)
    items = project_evidence_candidates(identity=IDENTITY,contexts=supplied,relation_resolution=resolution)
    facts = [item for item in items if item.fact_type == 'quality_lots']
    assert len(facts) == len(data['quality_lots'])
    assert len({item.candidate_id for item in facts}) == len(facts)
    for fact in facts:
        assert fact.relation_paths
        assert all(path.steps[-1].target_id == fact.subject_id for path in fact.relation_paths)
    result = select_evidence_candidates(items,strategy=EvidenceSelectionStrategy.DETERMINISTIC,max_candidates=1)
    assert {item.candidate_id for item in facts} <= {item.candidate_id for item in result.selected}


def test_provider_preserves_display_values_and_paths():
    from app.operations.agent_review_summary_provider import _selected_evidence_context
    _, _, items = candidates()
    item = next(item for item in items if item.fact_type == 'delivery_commitments')
    context = _evidence_context({'selected_basis': [item.model_dump(mode='json')]})
    wire = _selected_evidence_context({'evidence_context': context})['selected_basis'][0]
    assert wire['display_fields'] == [field.model_dump(mode='json') for field in item.display_fields]
    assert wire['relation_paths'] == [path.model_dump(mode='json') for path in item.relation_paths]


def test_mixed_context_versions_are_rejected():
    supplied, resolution, _ = candidates()
    mismatched = resolution.model_copy(update={'context_version_set': {'production':'old-version'}})
    with pytest.raises(ValueError, match='versions'):
        project_evidence_candidates(identity=IDENTITY,contexts=supplied,relation_resolution=mismatched)


def test_conflicting_edge_does_not_become_a_navigable_path():
    from app.operations.operational_relation_resolver import ResolvedRelationshipState
    supplied, resolution, _ = candidates()
    edges = tuple(edge.model_copy(update={'state': ResolvedRelationshipState.CONFLICTING})
                  if edge.relationship_type == 'asset_executes_operation' else edge
                  for edge in resolution.relationships)
    resolution = resolution.model_copy(update={'relationships': edges})
    items = project_evidence_candidates(identity=IDENTITY,contexts=supplied,relation_resolution=resolution)
    assert not next(item for item in items if item.fact_type == 'delivery_commitments').relation_paths


def test_mandatory_scheduling_constraints_reach_display_and_provider():
    from copy import deepcopy
    from app.operations.agent_review_summary_provider import _selected_evidence_context
    supplied = contexts()
    envelope = supplied['maintenance_readiness']
    data = deepcopy(envelope.data)
    window = data['maintenance_windows'][0]
    window['approval_required'] = True
    window['active_work_order_conflict'] = True
    supplied['maintenance_readiness'] = envelope.model_copy(update={'data':data})
    resolution=resolve_operational_relations(identity=IDENTITY,contexts=supplied)
    items=project_evidence_candidates(identity=IDENTITY,contexts=supplied,relation_resolution=resolution)
    selected=select_evidence_candidates(items,strategy=EvidenceSelectionStrategy.DETERMINISTIC,max_candidates=1)
    candidate=next(item for item in selected.selected if item.fact_type=='maintenance_windows')
    assert candidate.required_for_boundary
    view=_evidence_context({'selected_basis':[candidate.model_dump(mode='json')]})
    fields={item['label']:item['value'] for item in view['selected_basis'][0]['display_fields']}
    assert fields['승인 필요']=='예'
    assert fields['기존 작업과 일정 충돌']=='예'
    assert _selected_evidence_context({'evidence_context':view})['selected_basis'][0]['display_fields']==view['selected_basis'][0]['display_fields']

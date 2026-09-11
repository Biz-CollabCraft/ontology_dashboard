from copy import deepcopy
import pytest
from briefing_demo_replay_support import load_cases, replay_delivery, validate_replay, digest

CASES = load_cases()

@pytest.mark.parametrize('case', CASES, ids=lambda c: str(c['case_id']))
def test_frozen_input_reaches_real_view_model_and_current_validator(case):
    before = digest(case)
    delivery = replay_delivery(case)
    result = validate_replay(case)
    assert all(delivery['checks'].values())
    assert delivery['view_model']['asset']['asset_id'] == case['packet']['asset_id']
    assert delivery['view_model']['snapshot_basis'] == case['packet']['snapshot_basis']
    assert result['replay']['input_sha256'] == delivery['input_sha256'] == case['packet_sha256']
    assert result['trace']['materialization']['status'] == 'ready'
    assert result['summary'] == case['candidate']
    assert result['replay']['live_generation'] is False
    assert digest(case) == before

@pytest.mark.parametrize('case', CASES, ids=lambda c: str(c['case_id']))
def test_invalid_execution_and_inventory_claims_never_reach_reader(case):
    result = validate_replay(case, 'rejected')
    assert result['summary'] is None
    assert result['trace']['fallback'] is True
    assert result['trace']['validation_errors']
    assert result['trace']['materialization']['status'] == 'fallback'
    assert validate_replay(case)['summary'] == case['candidate']

@pytest.mark.parametrize('case_id', [5, 6])
def test_future_or_other_event_approval_is_excluded(case_id):
    delivery = replay_delivery(next(c for c in CASES if c['case_id'] == case_id))
    assert delivery['excluded_record_count'] > 0
    assert not any(r['status'] == 'approved' for r in delivery['facts']['work_orders'])

def test_tampered_input_fails_closed_before_prose_delivery():
    case = deepcopy(CASES[0])
    case['packet']['asset_id'] = 'OTHER-ASSET'
    with pytest.raises(ValueError, match='replay_delivery_contract_failed'):
        validate_replay(case)


def test_data_quality_hold_reaches_screen_without_a_risk_value():
    delivery = replay_delivery(next(c for c in CASES if c['case_id'] == 8))
    assert delivery['facts']['data_quality_hold'] is True
    assert delivery['view_model']['data_status']['is_data_quality_hold'] is True
    assert delivery['view_model']['risk']['status_grade'] is None
    assert delivery['view_model']['risk']['current'] is None

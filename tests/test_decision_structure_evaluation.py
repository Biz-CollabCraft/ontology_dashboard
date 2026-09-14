import importlib
from pathlib import Path
import pytest

@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('evaluate_decision_structure')

@pytest.mark.parametrize('index',range(9))
def test_expected_outcomes_and_sequential_graph_parity(m,index):
    case=m.CASES[index]
    rows={a:m.run(case,a,False) for a in m.ARMS}
    for row in rows.values():
        assert row['outcome_match']
        assert row['policy_contained'] and row['human_approval_required'] and not row['mutation_attempted']
        assert row['missing_required_tools']==0
        assert row['tool_attempts']<=case.get('max_calls',5)
    a,b=rows['sequential'],rows['langgraph']
    for field in ['tool_path','action','status','retry_attempts','scheduled_backoff_seconds','interpretation_count','unique_interpreted_texts']:
        assert a[field]==b[field]
    assert a['session']['retry_budget_remaining']==b['session']['retry_budget_remaining']


def test_duplicate_sources_keep_every_location_with_one_interpretation(m):
    for arm in m.ARMS:
        row=m.run(m.CASES[6],arm,False)
        assert row['interpretation_count']==26
        assert row['unique_interpreted_texts']==12
        assert row['simulated_interpretation_batches']==1


def test_transient_recovery_is_shared_retry_logic_not_graph_only(m):
    rows=[m.run(m.CASES[3],a,False) for a in m.ARMS]
    assert all(r['tool_attempts']==3 and r['retry_attempts']==1 and r['scheduled_backoff_seconds']>0 for r in rows)

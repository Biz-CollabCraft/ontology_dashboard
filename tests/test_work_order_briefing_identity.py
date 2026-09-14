from app.operations.service import _work_order_context

def test_preserves_owner_binding_without_inventing_approval():
    row={'work_order_id':'job-1','asset_id':'CNC-1','equipment_id':'CNC-1','event_id':'FILE#run#obs','status':'in_progress','updated_at':'2026-09-08T00:00:00Z'}
    value=_work_order_context(row)
    for key in ('work_order_id','asset_id','equipment_id','event_id','status','updated_at'):
        assert value[key]==row[key]
    assert 'approved_at' not in value

def test_preserves_supplied_approval_time():
    row={'work_order_id':'job-1','approved_at':'2026-09-08T00:00:00Z'}
    assert _work_order_context(row)['approved_at']==row['approved_at']

"""Scoped maintenance facts at the selected result time; never changes risk."""
from datetime import datetime


def instant(value):
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def read_runtime_maintenance(repository, *, organization_id, project_id, workspace_id,
                             dataset_version_id, asset_id, observed_at):
    at = instant(observed_at)
    scope = (organization_id, project_id, workspace_id, dataset_version_id, asset_id)
    with repository.connection(organization_id, project_id) as c:
        records = repository.execute(c, '''SELECT maintenance_id, completed_at, maintenance_type
            FROM pm_maintenance_events WHERE organization_id=? AND project_id=?
            AND workspace_id=? AND dataset_version_id=? AND asset_id=?
            AND completed_at<=? ORDER BY completed_at DESC''', (*scope, at.isoformat())).fetchall()
        work = repository.execute(c, '''SELECT status, updated_at FROM closed_loop_work_orders
            WHERE organization_id=? AND project_id=? AND workspace_id=? AND asset_id=?
            AND created_at<=?''', (organization_id, project_id, workspace_id, asset_id, at.isoformat())).fetchall()
    # Mutable current state cannot reconstruct a historical work order after it changed.
    open_work = None if any(instant(w['updated_at']) > at for w in work) else any(
        w['status'] not in ('completed', 'cancelled') for w in work)
    context = {'last_maintenance_days_ago': (at-instant(records[0]['completed_at'])).days if records else None,
               'similar_events_30d': None, 'open_work_order_exists': open_work}
    history = [{'occurred_at': instant(r['completed_at']).isoformat(), 'kind': '정비 완료',
                'tone': 'hold', 'description': '기록된 정비 완료 · 이상 해소 여부는 별도 확인',
                'source': 'maintenance:'+r['maintenance_id']} for r in records[:30]]
    return context, history

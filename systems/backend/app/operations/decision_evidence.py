"""Read-only evidence requirements, distinct from action eligibility and ranking."""
from app.operations.decision_tools import DecisionToolName as T


def relevant_tools(facts):
    if facts.maintenance_recommended:
        return (T.GET_MAINTENANCE_CONTEXT, T.GET_PRODUCTION_CONTEXT, T.GET_RESOURCE_READINESS)
    if not facts.inspection_result_available:
        return (T.GET_ASSET_CONDITION, T.GET_INSPECTION_CONTEXT)
    return (T.GET_ASSET_CONDITION,)


def recommendation_blockers(results):
    return tuple(dict.fromkeys(reason for result in results.values()
        for reason in result.recommendation_blockers))


def measurement_required(results):
    return any(result.status == "available" and
        (result.data.get("decision_signals") or {}).get("additional_measurement_required") is True
        for result in results.values())


def remaining_tools(facts, results):
    if recommendation_blockers(results) or any(r.status != "available" for r in results.values()):
        return ()
    # A source explicitly requesting measurement suffices to propose diagnosis.
    condition = results.get(T.GET_ASSET_CONDITION)
    if not facts.maintenance_recommended and condition and measurement_required({T.GET_ASSET_CONDITION: condition}):
        return ()
    return tuple(t for t in relevant_tools(facts) if t not in results)


def evidence_notes(results):
    notes = [note for result in results.values() for note in result.limitations]
    readiness = results.get(T.GET_RESOURCE_READINESS)
    production = results.get(T.GET_PRODUCTION_CONTEXT)
    if readiness:
        data = readiness.data
        notes.extend(data.get("blocking_reasons") or [])
        for window in data.get("maintenance_windows") or []:
            if window.get("suitability") == "unsuitable":
                notes.append("정비 창 부적합: " + str(window.get("conflict_reason") or "사유 확인 필요"))
        for inventory in data.get("inventory_snapshots") or []:
            if inventory.get("reservation_state") == "fully_reserved":
                notes.append("가용 재고가 전량 예약되어 있습니다. 이번 정비의 예약 소유 관계는 별도 확인이 필요합니다.")
            elif inventory.get("available_quantity") == 0:
                notes.append("현재 가용 재고가 없습니다. 보충 예정은 현재 작업 가능함을 뜻하지 않습니다.")
    if production:
        data = production.data
        if data.get("due_pressure") == "high":
            notes.append("납기 압박이 높습니다. 납기 압박만으로 설비 위험의 긴급도를 판단할 수 없습니다.")
    return tuple(dict.fromkeys(notes))

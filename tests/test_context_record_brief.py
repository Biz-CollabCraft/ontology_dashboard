from app.operations.context_record_brief import record_limitations

def test_empty_documents_are_not_readiness_or_zero_loss():
    read={'domains':{'maintenance_readiness':{'context':{'status':'available','data':{'required_skill_codes':['skill']}}}},'production_impact':{'options':[{'reason_codes':['MISSING_WIP']}]}}
    notes=record_limitations(read)
    assert any('정비 인력·재고·일정: 문서만' in n for n in notes)
    assert any('손실 0으로 해석하지 않습니다' in n for n in notes)
    assert any('생산 운영 계획: 선택 시점 기록 미등록' in n for n in notes)

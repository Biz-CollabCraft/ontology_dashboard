# 선택지 생산 비교 입력 재적재

대상: CMP-S03-L03-01 / 2026-08-29 23:00 KST snapshot. 기존 SUPPLIES_AIR_TO 4개 관계와 연결 절삭기 재공 200개를 유지한다. 기존 문서는 보존하고 SUPPLY-DEPENDENCY-v2 4건(production, quality_delivery, impact_policy, maintenance_readiness)을 추가했다.

동일 비교 구간: 23:00~01:00 2시간, 4대 × 시간당 25개 = 100개/시간. 예비 공급 없음. 즉시 정지는 2시간 정지, 계획 정비는 23:30~00:30 1시간 점검, 운전 지속은 2시간 처리하는 샘플 조건이다. 계산 결과 차질은 각각 200/100/0개. 품질·납기와 공급 관계 및 주문/WIP ID는 보존한다. 실제 생산 손실·회복·운전 권고가 아니다.

기존 파일 조회가 사용하던 _maintenance_readiness를 DB read_view에도 적용했다. 저장된 원천 문서는 변경하지 않는다. 부품 교체 없는 점검을 가정하므로 부품 요구는 비어 있다. 인력과 일정은 가정된 후보이며 approval_required=true, approval_state=pending_human_approval, assignment_state=candidate_only, execution_state=not_started. WorkOrder 승인·배정·착수 쓰기는 수행하지 않았다.

verified.json: 실제 PostgreSQL/API 선택지 200/100/0, 승인 대기·미착수, 반복 적재 신규 0/동일 4, 관계 출처 위조 차단, 최종 AI prompt의 입력 전달 확인. 외부 모델 생성은 실행하지 않았다. 프론트 빌드 통과. 공급 계약/기존 repository 회귀 17 passed, 별도 PostgreSQL fixture 12 skipped; 실제 PG 확인은 verified.json로 구분한다.

적용 범위: 선택한 셀 한 곳. 나머지 셀은 변경하지 않았다. 비교 시간 및 처리능력 가정은 production.supply_basis.assumptions와 maintenance window, impact_policy에 저장된다. 다음 버전은 이전 파일 수정 대신 새 source_version으로 등록한다.

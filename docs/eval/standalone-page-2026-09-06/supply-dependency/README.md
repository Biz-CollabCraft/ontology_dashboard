# 공급 의존 생산 비교 (2026-09-07)

선택한 CMP-S03-L03-01의 기존 pm_asset_relations 4건을 재사용했다. 공급 대상 CNC-S03-L03-01~04의 동일 시점에 묶인 주문과 재공을 읽어 production v2 문서로 보존했다. v1의 설비 자체 주문 제한은 유지한다. v2는 원래 assigned_asset_id/asset_id를 보존하고 supply_basis에 dataset, snapshot, 관계 출처 hash와 조건을 담는다. importer가 같은 조직·프로젝트·워크스페이스·dataset의 실제 관계 hash를 검사한다.

별도 전용 PostgreSQL에 production v2 / quality_delivery v1 / impact_policy v1 3건을 추가했다. 기존 기록은 삭제하지 않았다. 재실행 inserted 0, unchanged 3. 위조 관계 hash는 거부됐다. 백업: /tmp/ontology-before-supply.dump.

검토 조건: 예비 공급 없음, 즉시 정지 시 연결 설비 잔여 재공 처리능력 0, 운전 지속 시 잔여 재공 처리 가능. 공급 관계 자체를 고장 인과관계로 바꾸지 않는다. 각 50개 재공 합계 200개에 대해 stop_now=200, continue_operation=0, planned_maintenance는 조건 미충족으로 not_calculable. 생산 차질은 조건부 비교이며 실제 손실·안전한 운전 권고·정비 승인·회복이 아니다. 압축기 생산량으로 공장 합계에 추가하지 않는다.

검증: 실제 API 200과 위 계산값, 최종 LLM prompt에 공급 대상 4대와 200개·조건을 포함함을 verified.json에 저장했다. 외부 모델 재생성은 수행하지 않았다. 프론트 빌드 통과. 계약 guard 5개와 기록 설명 1개 통과. 버전 진화 회귀 7개 통과, 해당 suite PostgreSQL 7개는 별도 fixture 설정 없어 skip (실제 PostgreSQL 검증은 verified.json과 구분).

적재 범위는 현재 선택한 3라인·3셀 한 곳이다. 다른 압축기는 자동 확장하지 않았다. 기존 계획 planning 문서, 부하 등급, 실제 가동시간, 정비 착수 기록을 새로 만들지 않았다.

# Supply options v3 전체 압축기 Context

대상: `manufacturing-demo-project` / `manufacturing-demo` / 2026-08-29 23:00 KST snapshot.

기존 `SUPPLIES_AIR_TO` 관계는 공급 연결 근거로만 사용한다. 고장 인과관계, 안전 운전 권고, 실제 생산 회복, 승인 기록으로 해석하지 않는다.

이번 v3는 4라인 × 5셀의 압축기 20대 전체에 같은 계산 계약을 적용한다. 각 압축기는 같은 셀의 절삭기 4대를 공급 대상으로 갖고, 각 절삭기는 재공 50개를 가진다.

조건부 비교:

- 즉시 정지: 공급 대상 재공 200개 중 처리 가능 0개, 잔여 차질 200개.
- 계획 정비: 23:30~00:30 60분 정지, 나머지 1시간 처리 가능 100개, 잔여 차질 100개.
- 운전 지속: 2시간 처리 가능 200개, 잔여 차질 0개. 운전 허가나 고장 미발생 보장이 아니다.

적재 결과:

- 생성: `scripts/build_supply_dependency_context.py --all-compressors`
- 검증: `80`개 Context row 검증 통과
- 로컬 PostgreSQL 적용: `inserted=80`, `unchanged=0`
- API 확인 대상: `CMP-S01-L03-01`
- API 확인 결과: production/maintenance_readiness `available`, `stop_now=200`, `planned_maintenance=100`, `continue_operation=0`

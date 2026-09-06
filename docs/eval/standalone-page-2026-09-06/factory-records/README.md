# 설비 상태·30일 사건·조치 정책

원천 기록: manifest.json. 조직·프로젝트·워크스페이스·dataset·설비·event/snapshot·모델 버전·유효기간을 함께 저장한다. 기존 Product Result 위험값은 변경하지 않는다.

- 100대 상태 기록: 가동 92, 정지 5, 정비 3. 위험 등급에서 가동 상태를 추정하지 않았다. 상태 유효기간 밖에서는 사용할 수 없다.
- 설비별 이상 사건 3건: 5일·15일·35일 전. 같은 설비, 같은 고장 유형을 (as-of-30일, as-of]로 집계하여 2건. 원천 이력의 완전한 수집 구간이 30일을 덮지 않으면 미확인.
- 모델 independent-logreg-v3.1 / 설비 유형별 정책: 주의 참고 0.30, 조치 검토 0.60. 별도 운영 정책이며 기존 위험 등급을 다시 분류하거나 작업을 승인하지 않는다.
- 기준 시각 2026-08-29 23:00 KST. 유효기간 22:00~익일 00:00, 기록 생성 23:00. 생성 전 시점에는 조회하지 않는다.
- 출처 synthetic_demo_context는 DB/API에 유지한다. 화면 반복 샘플 배지는 표시하지 않는다.

저장: factory_record_bundles 테이블의 불변 원천 JSON과 SHA256. SQL migration 0051, PostgreSQL RLS 및 수정·삭제 금지. importer는 기본 검증만 수행하며, 명시적 scope/allow-demo/apply로만 적재한다. 운영 환경의 demo import 금지. 동일 ID에 다른 자료를 덮어쓰지 않는다.

조회: GET /api/objects/{asset_id}/factory-records. events.read 권한·활성 프로젝트·워크스페이스를 검사하고 runtime의 event/snapshot 및 정확한 as-of를 검증한다. runtime 조회 실패를 fixture로 대체하지 않는다. API 집계 결과를 독립 페이지가 숫자와 기준선으로 바인딩하며 늦게 도착한 다른 설비 응답은 버린다.

변경 전 위험값/등급과 업무 권한은 유지한다. 기록 추가는 점검 요청·정비 승인·착수 계약 구현을 의미하지 않는다.

검증: 저장·시간·범위·모델·중복·이력 완전성 단위 검사 7개 통과. 프론트 표시 검사 11개 통과. 실제 PostgreSQL 및 브라우저 검증 결과는 아래 실행 기록에 별도로 남긴다.

## 실제 실행 결과

- 전용 PostgreSQL ontology_standalone/63542에 migration 0051 및 원천 묶음 1건(100대 상태·300건 사건·100대 정책)을 적재했다. 같은 묶음 재실행 inserted 0 / unchanged 1. 백업 /tmp/ontology-before-factory-records.dump.
- 세 역할 × 절삭기·압축기 2대의 실제 API/화면/새로고침 검증 통과. 잘못된 snapshot 409, 다른 workspace 403. live-verification.json 참조.
- 초기 병행 회귀에서 설비 전환 대기 1건이 시간 초과했다. 집계 API의 전체 결과 조회를 선택 설비 1건과 범위가 지정된 설비 목록 조회로 줄였다. 최종 회귀 11개 모두 통과(8개 실제 PG, 1개 지연 주입, 2개 mock 저장). browser-tests-final.txt 참조.
- 현재 사용자 탭 CNC-S04-L02-04에서 92/100대·2건·0.60 표시를 확인했다. 기존 6칸 업무 근거 레이아웃을 유지하며 추가 정책 설명은 공통 상세에만 표시한다.
- 부하 등급·7일 가동시간·생산 영향 등급 등 다른 미연결 계약은 이번 세 가지 집계 기능에 포함되지 않는다.

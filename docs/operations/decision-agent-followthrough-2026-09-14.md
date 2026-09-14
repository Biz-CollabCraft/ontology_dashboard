# 활성 경로 확인 및 복구 호출 마무리

2026-09-14. 작업 범위: DevSpace의 codex/decision-agent-mvp 백엔드·호출 스크립트·테스트·평가 문서. 프론트와 다른 checkout은 변경하지 않았다.

## 레거시 여부

FILE 브리핑은 미사용 레거시가 아니다. `operations/router.py::_selected_agent_review_packet`와 `dependencies.py::refresh_stored_agent_briefing`이 이 경로를 호출한다. 따라서 기존 테스트 실패를 제외하는 대신 현재 경로의 데이터 전달과 테스트 계약을 수정했다.

- FILE 근거와 연결된 정확한 event lineage를 packet에 사용한다. 조회한 이력을 버리고 fixture 이력을 다시 읽지 않는다.
- workflow_as_of를 보존해 관측 이후 기록된 점검·생산 협의의 시점을 정확하게 평가한다.
- 생산 승인 대기 문구 검사는 scope 검증된 별도 production_coordination 사실을 소비한다.
- 기존 서비스 대역·activity_type·stage·예외 기대를 현행 계약에 맞췄다. application 오류와 API 503 변환을 분리 검증했다.

## 호출자 복구 연결

현재 이 checkout의 프론트에는 Decision Session 호출이 없다. 프론트 별도 작업 범위를 유지하면서 `scripts/decision_session_client.py`에 인증된 Python 호출자용 키 보관·재시도를 구현했다.

실제 로컬 HTTP + 임시 PostgreSQL에서 첫 조회 저장 후 두 번째 조회에 지연을 주입했다. HTTP 응답이 유실된 뒤 서버를 강제 종료하고 동일 포트의 새 서버·새 client가 로컬 파일에 남은 request_id로 재개했다.

- 동일 request_id 및 동일 session_id 재사용.
- 첫 도구 결과 1개 재사용, 두 번째 도구만 재시도.
- 총 시도 3회, 재시도 예산 3 → 2.
- 완료 후 GET 및 동일 POST 응답 일치.
- CSRF 누락 403, 잘못된 snapshot 409, 비로그인 401.
- 관련 도메인 13개 테이블 행 해시 동일.
- 검증용 lease 0.5초, 기본 runtime lease 30초 유지.
- 실제 LLM 호출 없음. Fixture 근거와 주입 장애로 구조를 검증했으며 현장 성능·Luna 정확도 증거가 아니다.
- 검증 서버 종료, 임시 PostgreSQL DB 삭제 확인.

[HTTP 복구 증거](../eval/decision-durable-2026-09-14/http-client-recovery.json), [정리 증거](../eval/decision-durable-2026-09-14/http-client-cleanup.json).

## 최종 검사

확대 검사: **225 passed, 2 skipped, 1 failed**. 원래 지적한 FILE 이력 7개 테스트는 모두 통과하며 API 오류 매핑 검사도 추가했다.

남은 실패는 `test_agent_review_packet_golden.py::test_current_service_packets_keep_gold_contract_shape`다. 현재 SOP에는 동일 설비의 진행 중 작업·예정 정비 겹침 확인이 포함돼 있으나 과거 gold의 checklist/replacement-review 내용에는 없다. 해당 SOP fixture, golden fixture, packet projection, 비교 테스트는 이번 변경에서 수정하지 않았다. 과거 gold를 현재 구현에 맞춰 덮어써서 통과 처리하지 않았다. 이 실패가 있으므로 전체 테스트 성공으로 보고하지 않는다.

전체 architecture 검사 **PASS**. import allowlist를 완화하지 않고 위반 6건을 제거했다. `git diff --check` 통과.

과거 구조/모델 평가 결과는 당시 코드 hash와 함께 유지한다. 이번 코드 변경 이후 다시 실행한 모델 비교라고 표시하지 않는다.

## 배포 단위 및 남는 작업

변경을 LLM 계약·평가 기준, durable 실행·복구 호출, 활성 FILE 이력 수정의 세 커밋으로 분리한다. 기존 원격 `origin/codex/decision-agent-mvp`를 대상으로 하며 main merge나 배포는 포함하지 않는다.

프론트 연결은 별도 작업이다. 같은 scope에는 request_id를 유지하고 네트워크 유실·busy 409에만 재시도하며, 명시적으로 새 판단을 시작할 때 새 키를 만들어야 한다. 이번 Python client가 해당 동작의 참조 구현이다.

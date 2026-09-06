# 3역할 공통 근거 백엔드 검증

## 기준과 선택 범위

- 새 격리 worktree, 브랜치 `codex/three-role-backend-read-contract`.
- 실제 원격 main을 `git ls-remote`로 확인: `ec7d05f326ce346ec0c28c9cbb36191b589caccb`. 시작 HEAD도 동일하고 작업 전 clean/detached였다.
- 이전 통합 기준 `2e666e6d`는 main의 후속 8개 commit이다. 전체 merge/cherry-pick 대신 백엔드·공유 계약·관련 fixture/eval/script 기반을 경로별로 선택했다. 이전 프론트 변경과 과거 실행 증거 문서는 가져오지 않았다.
- 이전 401 passed/2 skipped, 팀 DB 적용, live-provider 결과는 새 후보의 검증 수치로 재사용하지 않았다. 이전 통합 worktree는 읽기만 수행했다.

기반에는 materialization lease fencing, runtime summary 저장/재사용, deterministic selection/eval 호환, versioned Context source/binding 및 동결 schema 검증이 포함된다. 이번 독립 변경은 새 Context GET API, 생산 영향 시점 오류의 미산정 containment, 원본 점검/Activity provenance의 Packet·AI 입력 보존과 prompt version 갱신이다. Closed-loop command·RBAC·상태 전이와 프론트는 변경하지 않았다.

## 최종 검증

최종 결과는 이 문서와 함께 저장한 `regression-tests.txt`를 기준으로 한다. 초기 시도에서 PostgreSQL 드라이버/테스트 fixture 누락과 테스트 입력 오류가 있었으며 수정 후 최종 후보를 다시 실행했다. 시점 오류가 기존 reliability harness를 중단시키는 문제는 예외 대신 기존 미산정 결과/reason_codes를 반환하도록 보완했다.

- [회귀 원본 출력](regression-tests.txt): **425 passed, 2 skipped (120.55s)**. skip은 SQLite 대상 PostgreSQL RLS 검사와 제거된 AdaptiveWorkbench 검사이며, 별도의 PostgreSQL RLS 검사는 통과했다.
- [인증된 API 실행 결과](api-proof.json): 원래 합성 Context 14건을 새 PostgreSQL DB에 적재하고 authenticated ASGI HTTP로 조회. 200 read/repeat, 409 wrong snapshot, 이후 as-of에 미연결/null 유지 확인. fixture Event를 사용하는 로컬 실행이며 실제 8월29일 Product Result 검증이나 브라우저/E2E 증거가 아니다.
- 새 API의 조회 시각만 변경된 반복 요청에서 동일 Context fingerprint 확인. 검증된 schema/version/checksum/classification은 구조화되어 반환된다.
- SQLite 및 PostgreSQL의 checksum 손상, tenant/as-of 격리, immutable source와 다중 binding, v1/v2 dispatch, migration 원자성, stale metadata 보존을 검증한다.
- Summary provider failure/fallback, snapshot mismatch, lease fencing, 선택/gold/eval은 관련 기존 harness를 이번 후보에서 재실행한다. 외부 LLM 호출·새 품질 측정은 하지 않았다.

## 재현

PostgreSQL client와 Python의 postgres/dev 의존성이 필요하다. 저장소의 `pgvector/pgvector:pg16` 이미지로 작업 전용 임시 컨테이너를 만들고 localhost 임의 포트에 연결했다. 각 pytest fixture와 API proof는 별도 임시 DB를 생성/삭제한다. 기존 서버를 재시작하지 않았다. 출력에는 비밀번호와 전체 env/DSN을 남기지 않는다.

```sh
# TEST_POSTGRES_HOST=127.0.0.1, TEST_POSTGRES_PORT=<전용 포트>,
# TEST_POSTGRES_USER=<전용 테스트 사용자>를 설정한다.
python -m pytest -q \
  tests/test_operational_context_read.py tests/test_operational_context_deployment.py \
  tests/test_operational_context_evolution.py tests/test_operational_context_repository.py \
  tests/test_operational_context_import_cli.py tests/test_operations_presentation_readiness.py \
  tests/test_materialization_lease_fencing.py tests/test_operational_decision_api.py \
  tests/test_operational_decision_postgresql.py tests/test_predictive_maintenance_postgresql.py \
  tests/test_asset_detail_view_model_composer.py tests/test_asset_detail_view_model_contract.py \
  tests/test_verify_contract_vectors.py tests/test_agent_review_packet_golden.py \
  tests/test_agent_review_summary_contract.py tests/test_operations.py \
  tests/test_operational_evidence_selection.py tests/test_operational_impact_simulation.py \
  tests/test_operational_context_contract.py tests/eval
python scripts/verify_operational_context_read.py --output /tmp/context-api-proof.json
```

CI workflow에도 관련 검증과 PostgreSQL Python 의존성을 포함했다. 로컬 통과가 원격 CI 완료를 의미하지 않는다.

## Claim / 발표 경계

- 새 읽기 API·DB 검증·기록 provenance 전달: 코드/계약/테스트/API 실행 기준 Verified, architecture Pass.
- 3역할 전체 제품 개편: Partially Verified. 이 작업은 공통 백엔드 읽기만 제공하며 역할 재배정/협의·승인·착수 계약은 담당자 확정 및 통합 대기.
- 현재 이벤트의 수치 생산 영향, 실제 공장 운영 성과, 새 live LLM 품질, 원격 앱 반영, 프론트 E2E: Not Proven.
- 발표 blocker: 해당 Event/as-of에 유효한 승인된 생산·자원·품질·정책 자료, 미확정 Closed-loop 읽기 계약, 프론트 소비 및 실제 시연 환경 배포/검증. 8월1일 계획을 8월29일 이벤트에 재연결해서 해소할 수 없다.

실제 연결 필드와 담당자 의존 계약은 [3역할 백엔드 읽기 계약](../../operations/three-role-backend-read-contract.md)을 참조한다.

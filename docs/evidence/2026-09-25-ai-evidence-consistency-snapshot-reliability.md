# AI Evidence Consistency(AI 근거 일관성) & Snapshot Reliability(스냅샷 신뢰성) — Evidence(근거)

작성일: 2026-09-25  
저장소: `/Users/hb/Projects/ontology-dashboard`  
시작 revision(리비전): `05be8c8e0e73040420dfb8b040e8d0b74fe473fa` on `main`  
실행 환경: DevSpace Max(DevSpace Max) workspace `ws_2273d631b2` 우선 사용.  
Working tree(작업 트리): 시작 시 clean(깨끗함); 이 파일과 계획·최소 변경은 이번 slice의 미커밋 변경이다.

## Observed code path(관측 코드 경로)

`GET /api/objects/{asset_id}/agent-review-summary` → `router._agent_review_readiness_trace` → `service.cached_agent_review_summary_for_packet` → `AgentReviewSummaryMaterializer.lookup` → `SnapshotGuardedRepository` → repository summary storage(저장소 요약 저장) → API trace(추적) → `operationsContracts.ts` → `NaturalBriefing.tsx` / `OperationsWorkflowOverviewPage.tsx`.

생성 경로는 `service._materialize_agent_review_packet_now`의 `validate_binding`이 materialization key를 다시 계산한다. 바뀐 key는 `agent_review_context_changed_during_generation`으로 저장을 차단한다. 이 경로는 이번 변경으로 바꾸지 않았다.

## Reproduced counterexample(재현 반례)

기존 코드에서 fallback summary(대체 요약)가 존재하면 `cached_agent_review_summary_for_packet`가 `EXACT_VALIDATED`를 설정했다. fallback trace와 materialization status는 보존되지만 `current_ready=true`도 파생되어, `EXACT_VALIDATED`라는 이름의 검증 의미와 충돌했다.

2026-09-23 P0의 별도 반례는 context mutation 중 저장은 차단되지만 exact miss에서 `LATEST_STORED`가 HTTP 200으로 반환되는 경우였다. 이는 stale historical(오래된 과거 결과)과 current-ready(현재 준비)를 분리해야 한다는 근거이며, 이번 fallback normalization과 같은 정책 선택으로 확대 해석하지 않는다.

## Change and validation(변경 및 검증)

실행값만 기록하며, provider(제공자)/production(운영)/capacity(용량) 결과를 추정하지 않는다.

| Check(검사) | Result(결과) | Boundary(경계) |
| --- | --- | --- |
| Focused backend fallback(대체)/exact(정확)/historical(과거)/pending(대기) tests(테스트) | 4 passed(4개 통과), `APP_ENV=test ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 PYTHONPATH=systems/backend .venv/bin/pytest -q` with 4 named tests | synthetic fixture(합성 픽스처) and FastAPI TestClient(테스트 클라이언트) only(만) |
| Frontend contract normalization(프런트 계약 정규화) test(테스트) | 20 passed(20개 통과), `npm test -- --run src/api.briefing.test.ts src/features/operations/overview/NaturalBriefing.test.tsx` | mocked HTTP(모의 HTTP) only(만) |
| Frontend type check(프런트 타입 검사) | passed(통과), `npm run lint` | compile-time(컴파일 시점) only(만) |
| `git diff --check` | passed(통과) | whitespace(공백) only(만) |

Test Scope Review(테스트 범위 검토): 변경한 readiness derivation(준비 상태 파생)과 API/UI consumer(소비자) 경계를 확인했다. 72-run stability evaluation(72회 안정성 평가), actual provider(실제 제공자), database lock(데이터베이스 잠금), multi-worker deployment(다중 워커 배포)는 실행하지 않았다.

## Reconfirmation(재확인)

2026-09-25 Decision Gate(결정 게이트) 비교표를 추가한 뒤 같은 DevSpace Max(DevSpace Max) workspace에서 기존 focused checks(집중 검사)를 다시 실행했다. backend(백엔드)는 4 passed(4개 통과), frontend(프런트)는 2 files / 20 tests passed(2개 파일 / 20개 테스트 통과), `npm run lint`는 passed(통과)였다. 이 재확인은 기존 normalization(정규화)과 API/UI consumption(소비) 계약만 다시 확인한 것이며, provider(제공자), database(데이터베이스), production(운영), 72-run stability(72회 안정성) 결과를 추가하지 않는다.

## Limitation(한계)

이 증거는 actual provider readiness(실제 제공자 준비), live HTTP(실시간 HTTP), database lock(데이터베이스 잠금), multi-worker(다중 워커), deployment(배포), schema migration(스키마 마이그레이션), 72-run stability(72회 안정성), production freshness(운영 신선도)를 검증하지 않는다.

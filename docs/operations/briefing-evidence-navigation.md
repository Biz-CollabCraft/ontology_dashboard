# 브리핑 근거 탐색 계약과 검증

기준: 2026-09-09 원격 demo `b6cdc20e`. 작업 브랜치 `codex/demo-evidence-navigation`.

## 사용자 동작

브리핑 문장의 `근거`를 열면 같은 사건의 Agent Review Packet에서 해당 인용을 찾는다. 관측값, 점검 대상, 작업 기록, 생산 맥락, 선택된 운영 근거를 상세로 표시한다. 선택된 운영 근거에는 납기·수량·시간 등 표시용 값과 연결된 객체 경로를 포함한다. 인용 문자열을 URL이나 파일 경로로 실행하지 않는다.

사건·역할·관측·업무 revision 전환은 기존 NaturalBriefing 재마운트 정책을 따른다. 근거 상세도 함께 해제되고 요청을 취소한다. 조회 결과의 프로젝트·설비·사건과 제공된 관측 시점이 현재 선택과 다르면 표시하지 않는다. 기존 providedResponse 재생 화면은 재생 시점의 근거를 현재 API와 혼합하지 않는다.

## 계약

- `relation_paths`: `steps` 배열로 이루어진 경로 목록. 각 step은 edge ID, 출발/도착 객체의 종류와 ID, 관계 종류, 원천 참조와 버전을 가진다. 선택 설비에서 도달 가능한 방향성 경로만 제공한다. 연결되지 않은 정비 후보를 설비에 임의 연결하지 않는다.
- 기존 `relation_path`는 이전 소비자 호환용 관계 이름 목록이다. 실제 객체 탐색에는 사용하지 않는다.
- `display_fields`: 서버가 선택한 업무 필드의 label/value 목록. 원천 payload를 프론트에 그대로 전달하지 않는다. 데이터가 합성이라는 공통 전제의 반복 표시는 추가하지 않는다.
- 두 필드는 AssetDetailViewModel, AgentReviewPacket JSON Schema, TypeScript 및 frontend adapter, AI 입력 allowlist를 함께 확장했다. 이전 저장본에 없으면 빈 목록으로 읽는다.
- 선택 정책은 `operational-evidence-selection-v0.2`. fact ID에 도메인·레코드 위치를 포함해 같은 문서를 참조하는 서로 다른 사실을 구분한다.
- 필수 조건은 candidate ID 단위로 보존한다. 같은 출처의 추가 필수 조건 때문에 다른 중요 문서가 밀리지 않도록 기존 예산에 추가 조건 수를 더한다. 따라서 max_candidates는 필수 조건 보존 시 초과 가능한 예산이다.
- 관계 결과와 요청 사건·판단 시각·원천 버전 집합이 맞지 않으면 실패한다. unknown/conflicting/not_connected 관계는 탐색 경로로 만들지 않는다. 이는 합성 데이터 표시와 별개의 연결 상태이다.

## 테스트 목표

1. 같은 출처의 서로 다른 필수 조건을 후보 생성부터 최종 선택까지 보존한다.
2. 납기 근거가 선택 설비부터 해당 납기 객체까지 연속된 경로를 제공한다. 같은 출처를 공유해도 다른 객체의 경로를 붙이지 않는다.
3. 다른 사건·버전, 끊긴 경로, 충돌 관계를 잘못 연결하지 않는다.
4. ViewModel과 AI payload가 상세 값·경로를 보존하고 기존 JSON Schema 사례도 계속 허용한다.
5. 근거는 사용자가 열 때만 조회하며 인용 allowlist를 벗어난 자료를 표시하지 않는다.
6. 늦게 도착한 브리핑·근거 응답과 업무 revision 변경이 이전 설명을 현재 화면에 남기지 않는다.
7. 실제 Chromium에서 근거 열기, 사건 전환, 상태 갱신과 모바일 가로 넘침을 확인한다.

## 검증 범위

백엔드 계약/조합/선택 및 기존 브리핑 갱신 회귀, 프론트 단위/변환/API 테스트, TypeScript와 production build를 실행한다. 브라우저 테스트는 실제 제품 컴포넌트와 API 응답 대역을 사용한다. 실제 배포 DB에서 정비 명령을 실행한 통합 검증이나 live LLM 생성 실험은 아니다.

여러 설비를 묶는 DecisionContext, 생산오더/공정/배정 분리, 공유 자원 충돌 비교는 후속 범위다.

실행 결과:
- 백엔드 관련 9개 파일의 계약·회귀 검사: 179 passed. 이후 추가한 두 경계 사례를 포함한 전용 파일 재검사: 9 passed.
- 프론트 브리핑/근거/adapter/API 4개 파일: 30 passed.
- Chromium 근거 탐색/선택/갱신/모바일 시나리오: 1 passed. API 응답 대역 사용.
- TypeScript, production build, 초기 JS 310 KiB 예산 검사 통과. 초기 JS 256.98 KiB.
- 기존 factory-status-original/support.js의 비모듈 스크립트 build 경고는 남아 있으며 build는 성공했다.
- 데스크톱·모바일 캡처를 직접 확인했고 가로 넘침이 없었다.

## 재검증 및 보완 — 2026-09-09

사용자 재검증 요청으로 실제 패킷 인용, 인증된 HTTP 경로, 동일 관측 시각의 업무 기록 변경을 추가 확인했다.

발견·수정한 사항:
1. 예측 Artifact 전체를 인용하면 상세가 비어 있었다. snapshot의 위험 상태·확률·관측 시점·누락 사유를 표시하도록 수정했다. null 확률은 0으로 바꾸지 않는다. GS-002/004/007 고정 패킷 인용은 각각 15/15, 13/13, 3/3 해석된다.
2. 같은 사건·관측 시각에서 정비 기록이 달라져도 UI의 시점 비교만으로는 구분할 수 없었다. 브리핑에서 받은 `summary_key`를 packet GET의 `expected_summary_key`로 전달한다. 서버가 반환할 패킷으로 동일 키를 계산해 다르면 409를 반환한다. 근거를 열 때 새 LLM 생성을 실행하지 않는다. UI는 이전 설명을 철회하고 현재 저장본을 재조회한다. 기준 키가 없는 이전 응답은 최신 근거와 임의로 연결하지 않는다.
3. 필수로 선택한 정비 가능 시간에 승인 필요·기존 작업 충돌이 표시되지 않았다. 두 조건과 품질 해제 필요 조건을 표시 필드에 포함했다. 불리언은 예/아니요로 유지한다. 별도 검토자의 재현과 수정 후 백엔드/프론트 재검사로 확인했다.

HTTP 검사는 실제 인증, FastAPI route, packet composer와 key 계산을 사용한다. 선택 사건 분기의 외부 runtime repository는 격리된 fixture source로 대체한다. 브라우저 검사는 제품 컴포넌트와 HTTP 응답 대역을 사용한다. 실제 PostgreSQL 배포 인스턴스 검증으로 해석하지 않는다.

확대 실행 중 `.env`의 heuristic fallback 비활성 설정으로 모델 Artifact가 없는 fixture 테스트가 실패했다. fixture 검사에 `APP_ENV=test ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1`을 명시했다. 실제 운영 환경의 모델 설정을 변경하지 않았다.

최종 재검증 결과:
- 백엔드 12개 파일: 255 passed (41.55초). 인증 HTTP·근거 경로·계약·ViewModel·Operations·예측→패킷→저장→조회 회귀 포함.
- 프론트 4개 파일: 33 passed.
- Chromium: 2 passed. 근거 탐색·사건 전환·갱신 및 동일 관측 시각의 409 처리 포함.
- TypeScript/production build/초기 번들 예산 검사 통과. 초기 JavaScript 257.05 KiB / 310 KiB.
- git diff --check 통과. commit/push/배포 없음.

## 실제 서비스 화면 검증 — 2026-09-09

API 응답 대역 없이 작업 브랜치의 Vite 3317 / FastAPI 8317을 실행했다. DB는 `/private/tmp/ontology-evidence-ui.sqlite`로 격리했고, 기존 `20260904T080423Z` gen_data 파일을 읽었다. 데이터 생성기를 실행한 검증은 아니다. 기본 화면과 390×844 생산 화면을 직접 확인했다.

확인한 동작:
- 엔지니어 로그인, 100대 설비 표시, 설비 선택에 따른 사건 URL·센서 상세·추세 전환.
- CMP-S01-L04-01 점검 요청 → 보전팀 수신 → 접수 → 점검 시작 → 결과 저장 → 정비 승인 요청 → 생산 관리자 수신.
- 생산 화면에 점검 내용, 담당자, 정비 내용, 예상 정지 30분, 입력한 생산 영향 전달. 작업 승인은 실행하지 않았다.
- 관찰한 브라우저 콘솔 오류 없음. 생산 모바일 화면의 scrollWidth 375 / viewport 390으로 페이지 가로 넘침 없음.
- 백엔드 health, 로그인, 선택 FILE 사건의 agent-review-packet GET 모두 200.

실제 화면 통합 판정은 부분 통과이며, 브리핑·근거 탐색 완료 판정은 보류한다.
1. 엔지니어·보전팀은 현재 역할 계약상 `agent.review.materialize` 권한이 없어 생성 버튼이 없다. 생산 관리자는 버튼이 있다.
2. 생산 관리자 생성 요청은 fallback으로 저장됐다. DB trace는 `ProviderUnavailable`, `LLM credentials or model are not configured`, validation_errors=[]였다. 외부 LLM 응답을 받은 검증이 아니다. 화면은 이를 '검증을 통과하지 못했습니다'로 표시하여 원인을 구분하지 못한다.
3. 최신 demo의 FILE 사건은 `filesystem_briefing_packet`을 사용한다. 실제 요청·점검을 저장한 뒤에도 해당 패킷의 maintenance_history_summary에 work_orders/inspection_results/activities/source_refs가 모두 비어 있다. SOP returned_count도 0이다. 이 경로는 기본 Artifact로 ViewModel을 직접 구성하여 기존 운영 맥락·관계 조합 경로를 통과하지 않는다. 앞선 fixture 기반 관계 검증으로 실제 FILE 화면의 연결을 보증할 수 없다.
4. 저장된 LLM 브리핑이 없어 실제 서비스에서 근거 펼치기까지는 검증하지 못했다. 기존 응답 대역 브라우저 테스트 2건과 구분한다.

다음 통합 작업은 FILE 패킷에 같은 사건의 업무 이력·운영 맥락을 연결하고, LLM 설정 누락 메시지를 구분한 뒤 실제 생성→근거 펼치기를 재검증하는 것이다. 화면에는 기존 '가정' 문구가 남아 있어 사용자의 표시 제외 방향과도 별도 정리가 필요하다. 이번 검증에서 서비스 소스·권한·원본 관측 파일은 수정하지 않았다.

## 브리핑 생성 역할 제한 철회 — 2026-09-09

사용자 요청으로 process_engineer와 maintenance_technician에도 agent.review.materialize를 부여했다. 생산 관리자와 함께 세 업무 역할 모두 생성·재생성할 수 있다. 인증, 프로젝트 범위 검사, CSRF 및 별도의 승인·정비 업무 권한은 유지한다. 기존 Identity 초기화가 role_permissions를 추가 반영하므로 실행 중인 격리 로컬 서버도 재시작했다.

세 계정의 실제 인증을 거치는 생성·재생성 HTTP 회귀 3건과 전용 권한 제거 시 403 유지 검사 1건, 총 4건이 통과했다. 실제 엔지니어 화면과 보전팀 선택 작업 화면에서 브리핑 생성 버튼 표시를 확인했다. LLM 설정 누락과 FILE 패킷의 업무 이력 누락은 별도 미해결 사항이다.

## 전체 픽스처 회귀 실행 — 2026-09-09

전체 통과가 아니다. 최종 결과:

| 범위 | 결과 |
| --- | --- |
| pytest tests 전체 | 1,841 passed, 23 failed, 4 setup errors, 52 skipped; 109 subtests passed, 169.90초 |
| Vitest 전체 54개 파일 | 254 passed, 4 failed (258 tests) |
| 브리핑 근거 탐색 Chromium | 2 passed; API 응답 대역 사용 |
| 역할 권한·브리핑 생성 관련 재검사 | 16 passed |
| TypeScript / production build / 번들 예산 | 통과, 초기 JS 257.05 KiB / 310 KiB |

환경은 APP_ENV=test, DATABASE_URL 빈 값, GEN_DATA_ROOT=/Users/hb/Documents/final/gen-data, ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1을 명시했다. 외부 LLM 설정은 비워 두었다. 초기 백엔드 수집 오류는 worktree에서 외부 gen_data 위치를 찾지 못한 것으로, 실제 로컬 경로를 지정하여 해결했다.

테스트 수정:
- ProductionRequestBoard / MaintenanceRequestList 테스트의 화면 설정 hook fixture 누락을 보완했다. 이로 인한 16개 실패 중 12개가 해소됐다. 실제 서비스 동작은 바꾸지 않았다.
- 브리핑 생성 제한 철회 후에도 엔지니어에게 403을 기대하던 decision-support-brief 권한 테스트를 수정했다. 생성 권한 없는 executive 계정으로 403을 검증하며 CSRF 검사도 유지했다.

남은 백엔드 실패·준비 오류는 기준 HEAD b6cdc20e를 /private/tmp에 git archive로 추출해 같은 테스트를 실행한 결과 **23 failed, 4 errors가 모두 동일하게 재현**됐다. 최초 작업 브랜치의 추가 실패 1건은 위에서 수정한 역할 권한 기대값이었다. 기준 비교는 이번 실행에서 실패한 28건을 대상으로 했으며 기준 브랜치 전체 테스트를 실행한 것은 아니다.

| 기존 문제 영역 | 건수 | 관찰한 원인 |
| --- | --- | --- |
| adapter API / ontology stage19 | 실패 4 | 제거된 datascientist/quality 데모 계정 인증 실패 |
| dataset projection stage47 | 준비 오류 4 | fde 데모 계정 인증 실패 |
| closed loop persistence | 실패 9 | 저장된 작업지시와 승인 명령 불일치 |
| maintenance loop application | 실패 8 | 비용 계산에 필요한 완료된 점검 작업지시 누락 |
| maintenance composition | 실패 1 | filesystem 기반 adapter를 이전 runtime adapter로 기대 |
| operational context SQLite | 실패 1 | 실제 partial_with_gaps를 complete로 기대 |

프론트 남은 4건은 이전 prb-impact-kpis 영역을 기대하는 2건, 전체 정지 시간 표시를 기대하는 1건, 점검 결과 없는 작업 선택 시 생산 협의 연결 중 상태를 기대하는 1건이다. 기준 demo의 c2f5382b에서 생산 영향 지표를 상세 영역으로 옮기고 시간당 정지 비용을 표시하도록 변경했다. 기대값을 단순히 통과시키기 위해 바꾸지 않았다.

52개 skip은 로컬 disposable PostgreSQL 미가용, 미장착 canonical 패키지, 제거된 기능 관련 기존 skip을 포함한다. skip은 통과로 세지 않는다. 실제 LLM 생성·배포 연결·전체 브라우저 E2E 검증으로 확대 해석하지 않는다.

원본 로그:
- /private/tmp/ontology-fixture-backend-final.log
- /private/tmp/ontology-fixture-baseline.log
- /private/tmp/ontology-fixture-frontend.log
- /private/tmp/ontology-fixture-permission.log
- /private/tmp/ontology-fixture-browser.log
- /private/tmp/ontology-fixture-build.log

테스트가 만든 maintenance-test.sqlite3는 /private/tmp/ontology-fixture-maintenance-test-20260909.sqlite3로 이동했다. commit/push/배포는 하지 않았다.

## FILE 사건의 점검·승인 이력 연결 수정 — 2026-09-09

파일 기반 센서 입력을 유지하면서 기존 maintenance event_lineage 읽기 포트로 같은 사건의 DB 기록을 조회하고, 공통 ViewModel → agent-review packet 조합에 전달하도록 수정했다. 프로젝트·작업공간·설비·사건이 다른 기록은 거절한다. 조회 실패는 briefing_history_unavailable / HTTP 503으로 처리하며 빈 이력으로 생성하지 않는다.

생산 협의는 해당 사건 activity ledger의 최신 작업지시별 요청·응답을 사용한다. 점검 작업지시의 approved는 생산 승인과 다르므로 브리핑 읽기 모델의 단계를 별도로 표현한다. 원래 상태는 production_coordination.work_order_status에 보존하며 원본 DB는 변경하지 않는다. 협의가 pending인 상태에서 승인 완료·승인 시각으로 설명하거나 요청 정지 시간을 생략하는 응답은 검토 대상으로 처리한다.

센서 observed_at은 그대로 유지한다. workflow_as_of는 센서와 읽은 업무 기록 중 최신 시각으로 고정하여 이후의 실제 점검 기록이 센서 시각보다 늦다는 이유로 사라지지 않게 한다. 전체 이력은 기존 summary_key 해시에 포함되어, 센서값이 같아도 승인 상태·요청 내용이 달라지면 저장본을 재사용하지 않는다. 프롬프트 버전도 v3.5-workflow-coordination으로 변경했다.

문장별 인용이 없는 LLM 응답은 '브리핑 전체 근거'로 전체 입력 근거를 제공한다. 이를 특정 문장과 원문이 일대일로 매칭된 것으로 표시하지 않는다. 근거 패널은 기존 expected_summary_key 일치 검사를 사용하며, 점검 findings 원문과 읽을 수 있는 상태명을 표시한다.

실제 격리 로컬 DB의 CMP-S01-L04-01에서 확인한 결과:
- 이전 '점검 기록 없음' 브리핑이 재조회 시 사라짐.
- 승인된 OpenAI 호출로 새 브리핑 생성·저장 성공: 정비 권고, 승인 대기, 요청 정지 30분, 1구역 4셀 압축 공기 공급 영향 반영.
- 전체 근거를 펼쳐 작업요청의 생산 협의 내용과 DB에 저장된 점검 발견 사항을 확인.
- 브라우저 새로고침 후 같은 저장본과 근거가 표시됨.

검증: 백엔드 관련 8개 파일 86 passed, 프론트 브리핑/근거 21 passed, Chromium 사건 전환·409 회귀 2 passed. TypeScript/build/초기 번들 예산 257.05 KiB / 310 KiB 통과. 이번 수정 후 전체 저장소 테스트를 다시 실행한 것은 아니며, 앞서 기록한 기준 demo의 기존 실패들은 별도다. 생산 계획·부품·SOP 전체 연결이나 배포 검증으로 확대 해석하지 않는다. commit/push/배포 없음.

### 브리핑 근거 화면 매핑 — 2026-09-09

- 내부 FILE 사건 식별자는 근거 패널 머리글에서 제외하고 선택한 설비·사건 범위를 표시한다. 인용 식별자와 사건 일치 검증은 유지한다.
- 반복된 진단 오류는 필드별 한국어 정보 부족 사유로 변환하고 중복을 제거한다. 누락된 근거 자체는 숨기지 않는다.
- 생산 협의 요청은 정비 내용, 요청 정지 시간, 생산 영향, 값이 있는 승인 일정으로 분리한다. 점검 결과와 활동 유형을 업무 용어로 표시하고 기록 시각은 Asia/Seoul로 변환한다.
- 검증: 관련 프런트엔드 23개 테스트 통과, 프로덕션 빌드 통과, diff check 통과. 로컬 3317 실제 화면에서 CMP-S01-L04-01 근거 패널의 DOM 및 스크린샷 확인.
- 이 변경은 표시 계층이다. 센서 기준·추세·설비 전체 이력 등 미연결 데이터가 추가 연결된 것은 아니다. 원문 점검 기록은 보존한다.

### PR #173 통합 검증 — 2026-09-09

기존 PR head bf869469의 표현 경계·실패 재시도·상태 표시 수정과 통합했다. 생산 협의 프롬프트를 보존하고 통합 버전을 v3.6-grounded-workflow로 갱신했다. 백엔드 11개 파일 112 passed, 프런트엔드 4개 파일 39 passed, Chromium 근거 탐색·사건 전환·409 처리 2 passed, TypeScript/build/번들 예산 통과. 브라우저 테스트의 내부 사건 ID 노출 기대를 새 표시 계약에 맞추고 전환된 설비의 전체 관계 경로도 검사한다. 전체 저장소 검사의 기존 실패나 미연결 도메인까지 해결한 결과는 아니다.

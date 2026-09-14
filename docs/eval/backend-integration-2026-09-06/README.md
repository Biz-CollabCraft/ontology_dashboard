# Backend integration verification — 2026-09-06

내 로컬 리뷰 기준. 원격 PR/CI 승인이나 운영 환경 검증을 의미하지 않는다.

**최신 상태:** 아래 이전 candidate 기록 이후 운영 Context DB 이관과 runtime Packet 계약 보정을 구현했다. 최신 검증은 문서 끝의 “운영 Context DB 이관 후 검증”을 기준으로 한다. 이전 live LLM 수치를 이번 코드의 품질 증거로 재사용하지 않는다.

## 산출물 보존 정책

이 문서는 검증의 최종 요약과 재현 명령만 Git에 유지한다. 실행 중 생성되는 JSON 응답, 브라우저 캡처, 로그와 임시 검증 스크립트는 로컬/CI 산출물이며 `.gitignore` 대상이다. 아래 파일명 언급은 당시 실행 산출물의 이름을 기록한 것이며 저장소에 영구 보존한다는 의미가 아니다.

## 1. PR #166 검토 결과

PR #166 (`release: 데모 기준선을 main에 고정`)은 이미 merge됐다. 기준은 main `ec7d05f326ce346ec0c28c9cbb36191b589caccb`; 새 브랜치 `codex/backend-integration-main`에 필요한 기능만 manual port했다. 원본 브랜치 전체 merge나 demo 브랜치 역통합은 하지 않았다.

AI는 구조화된 위험등급, 권한, 추천 액션, Closed-loop 상태 전이를 소유하지 않는다. 기존 deterministic packet을 기준으로 설명만 생성하는 구조를 유지한다. 그러나 PR 그대로는 아래 저장·입력·runtime 소비 경계 문제가 있었다.

## 2. 발견한 근본 원인과 수정

- **만료된 작업의 늦은 결과가 새 결과를 덮어씀:** 시작 시 unique running guard와 프로세스 내부 lock만 있고, 저장 시 소유권 검사가 없었다. Summary와 Brief 모두 현재 running run을 조건부 갱신한 뒤 결과·완료 상태를 같은 DB transaction에서 저장한다. 늦은 완료/실패는 terminal run을 되살리지 못한다. 저장 실패는 run 완료도 rollback한다. LLM 호출은 transaction 밖에 있다.
- **Brief가 요청 snapshot/risk를 그대로 신뢰:** 실제 scoped packet의 asset/Artifact/as-of를 확인하고 risk를 서버 evidence에서 유도한다. 존재하지 않는 snapshot, 다른 risk, 과거 as-of는 저장 전에 거부한다. 기존 미검증 cache는 새 prefix로 재사용하지 않는다.
- **runtime 요약 POST와 Assistant가 저장을 우회:** 별도 동적 생성 함수를 제거하고 기존 materialization 서비스를 사용한다. Packet/요약 GET/POST의 선택 resolver를 공유한다. 잘못된 event ID는 fixture 요약으로 대체하지 않는다.
- **V3.1 prediction payload를 Product Artifact로 오인:** joined prediction payload가 명시적인 legacy prediction contract인 경우 normalized runtime 경로를 사용한다. Artifact를 표방하는 payload는 계속 전체 schema 검증을 받아야 한다. 이를 검증 생략용 일반 ValueError catch로 처리하지 않았다.
- **평가 harness/fixture drift:** 이전 모듈 import, GS004 SOP, Activity ID, `approve_inspection_work_order` 기대값을 현재 계약에 맞췄다.
- **prompt를 바꿔도 cache key 버전이 동일:** prompt version을 `agent-review-summary-prompt-v1.3-hold-boundary`로 갱신했다.

## 3. 흡수한 로컬 변경

- A: data-quality-hold 설명의 확정 생산 영향 억제, 관련 negative test, gold scorer 정합성, 별도 holdout manifest/gold 지원.
- B: provider usage metadata와 추정치 구분, holdout/human-review sample builder, evidence_context schema→composer→adapter→화면 연결, 시점별 공식 fixture 선택.
- main에 이미 동일한 deterministic selector, stability/temporal harness, snapshot/recommendation guard, DB migration은 다시 덮어쓰지 않았다.

## 4. 제외·보류

- 전체 로컬 branch merge와 schema 파일 통째 교체 제외.
- 특정 한국어 문구를 강제하는 manager validator는 과도한 fallback 위험 때문에 제외.
- 과거 candidate의 120회/holdout 수치를 이번 결과로 재사용하지 않음.
- 외부 provider 호출은 최초 자동 승인 검토에서 차단됐으나 이후 사용자의 구체적 승인으로 gold 8건 × 1회 실제 평가를 완료했다. 반복 안정성과 provider 청구 비용은 미측정이다. 이후 별도 승인된 V3.1 runtime 1건의 실제 LLM→PostgreSQL→화면 E2E는 아래 후속 검증에서 확인했다.
- Neo4j graph projection, 실제 gen_data watcher 스트림, 실 MES/WMS/QMS 연결, 전체 Closed-loop 업무 완주와 운영 배포는 이번 증거 범위 밖이다.

## 5. schema/contract 최종 기준

main의 contracts와 migration을 정본으로 유지하며 `inspection_closed_no_action`, `inspection_data_check_required` 등 최신 완료 분기를 보존했다. evidence_context는 additive 정보이다. fixture의 relation/selection 표시를 live runtime 구현 증거로 확대하지 않는다. V3.1 normalized prediction과 producer Product Artifact는 서로 다른 입력 계약이며 동일 이름으로 위장하지 않는다.

## 6. 검증 범위

최종 실행 결과는 아래 기록 및 JSON 참조. PostgreSQL 16의 독립 DB를 사용했다. 테스트의 PG fixture는 매 테스트용 DB를 생성·제거한다. 원격 GitHub Actions는 실행하지 않았고 동일 테스트를 실행하는 workflow만 추가했다.

실제 HTTP 경로는 공식 로컬 V3.1 canonical 패키지 → PostgreSQL → selected Packet/Detail ViewModel → Summary 저장 → GET/POST 재사용이다. 패키지 검증은 pass, 100개 설비/100개 Result Artifact/68,208 timeline row, relational ready, graph pending이다. 이 데이터는 실설비 스트림이 아니다.

데모 manager로 명시 생성하고 engineer 화면에서 같은 snapshot의 저장본 조회, 재생성 권한 없음, fallback 표시를 확인했다. 요약은 `deterministic_fallback`이며 run은 `partial`이다. fallback을 LLM 성공으로 집계하지 않는다. backend 재시작 후에도 같은 저장본이 재사용됐다.

## 7. 발표 blocker

검증한 PostgreSQL + V3.1 + fallback 브리핑 경로는 동작한다. 사용자 승인 후 실제 OpenAI gold 8건 단회 평가도 통과하여 provider 호출 승인 blocker는 해소됐다. 이후 승인된 V3.1 runtime 1건에 대해서 기존 실행 스크립트의 실제 LLM→PostgreSQL→화면 E2E도 확인했다. 검증한 1건의 브리핑 경로를 막는 blocker는 없으며 실시간 gen_data 스트림과 전체 Closed-loop 업무 완주는 범위 밖이다. 빈 DB에 fixture dataset catalog만 넣으면 기본 runtime Dataset Version이 없어 조회가 500을 낸다. 정식 V3.1 bootstrap을 완료하는 것을 실행 전제조건으로 기록하며, 빈 DB 오류를 정상 운영 readiness로 주장하지 않는다.

별도 OperationalDecisionSupport Brief는 fixture operational context를 사용하는 경로이다. 실제 WMS/MES 가용성과 연결됐다는 증거로 사용할 수 없다. 화면의 runtime evidence_context는 시간/관계 정보를 모르면 unknown으로 남긴다.

### 최종 실행 결과

- Backend 통합/PG/contract/gold/eval: **348 passed, 1 skipped**, 94.98s. skip 1건은 이미 제거된 Adaptive Modeling Workbench 테스트이다.
- Frontend operations adapter: **12 passed**. TypeScript 및 production build pass, initial JS 293.78 KiB / 310 KiB.
- Mock gold CLI: 8 cases × 1회, accepted 8, contract error 0. 실제 LLM 평가 아님.
- HTTP backend `/health/ready`: ready. Summary 생성/조회/재요청 200, 재시작 후 재사용 true.
- PostgreSQL transaction tests: 늦은 완료/실패, 결과 write 실패 시 run rollback, run trace와 저장 summary ID 정합성 포함.
- Runtime API 회귀: 잘못된 event의 Packet/요약 GET/POST 404, 정상 생성 후 저장 GET 재사용.
- Snapshot mismatch, malformed output, provider failure, retry/fallback, deterministic selection, gold/reliability/stability/temporal harness는 위 backend suite에 포함.

명령: `PATH=/opt/homebrew/opt/libpq/bin:$PATH TEST_POSTGRES_PORT=55432 TEST_POSTGRES_USER=hb TEST_POSTGRES_PASSWORD=<local-test-password> python -m pytest tests/test_materialization_lease_fencing.py tests/test_operational_decision_api.py tests/test_operational_decision_postgresql.py tests/test_predictive_maintenance_postgresql.py tests/test_agent_review_summary_contract.py tests/test_operations.py tests/test_asset_detail_view_model_composer.py tests/test_asset_detail_view_model_contract.py tests/test_agent_review_packet_golden.py tests/test_operational_evidence_selection.py tests/test_verify_contract_vectors.py tests/eval -q`

JSON: [API persistence/reuse](api-proof.json), [V3.1 bootstrap](bootstrap.json).

평가 대상 코드 commit: `cbf4126c`. [Mock gold](mock-gold.json)와 [mock holdout](mock-holdout.json)은 각각 8건 중 8건 contract acceptance, fallback 0이다. mock 결과이므로 실제 LLM 품질/일반화 성능 증거가 아니다.

### 사용자 승인 후 실제 provider 평가

- 대상 commit: `a308f6a6d8139cd87e1299ff06e77282a5a9890c` (구현 코드 `cbf4126c`와 동일).
- 승인 범위: 공식 gold 8건, 각 1회, `api.openai.com`, `gpt-4o-mini`. 추가 live holdout/120회 평가는 실행하지 않았다.
- 실행 ID: `integration-approved-live-gold`. 결과: [live-gold.json](live-gold.json).
- 실제 LLM 후보 acceptance **8/8**, fallback **0**, contract error **0**, grounded source refs **8/8**.
- 로컬 자동 gold scorer **1.0**, required point 누락 **0**, 금지 주장 탐지 **0**. 자동 규칙 점수이며 사람의 품질 검토나 운영 정확도가 아니다.
- provider 호출 및 로컬 검증 latency: p50 **3.989s**, p95 **4.618s**, 전체 순차 batch **32.495s**. 8건 표본이므로 반복 부하 성능으로 해석하지 않는다.
- 사용량은 8건 모두 provider가 보고했으며 총 **45,638 tokens**. 단가 미설정으로 비용은 미계산; 0원이 아니다.
- prompt version: `agent-review-summary-prompt-v1.3-hold-boundary`.
- 이전 348개 backend/12개 frontend 테스트 이후 구현 변경은 없으며, 이번 변경은 평가 결과와 문서뿐이다.
- 실제 provider harness 검증과 PostgreSQL/화면 fallback 검증을 분리한다. gold 평가 당시에는 V3.1 runtime payload를 전송하지 않았다. 후속 별도 승인으로 runtime 1건 E2E를 진행했으며 아래 기록으로 구분한다.

### 기존 로컬 실행 스크립트 확인

`run_local_live.sh`를 통합 브랜치에서 실제 실행했다. 통합 전용 `.venv` 설치, 기존 격리 PostgreSQL 재사용(`SKIP_POSTGRES=1`), V3.1 idempotent bootstrap, backend 18200 및 web 13200 기동을 확인했다. 자동 watcher는 껐다. [기동 증거](script-startup.json).

현재 코드의 startup log는 SKIP_POSTGRES에서도 빈 포트를 탐색하여 DB 55433으로 표시하지만 실제 명시한 URL과 연결은 55432이다. 동작 장애가 아닌 로그 표시 불일치이며 이번 검증에서 수정하지 않았다.

사용자가 기존 스크립트의 실제 LLM→DB→화면 확인을 요청한 후 runtime 사례 1건 생성 호출을 시도했으나, 자동 승인 검토가 기존 gold 8건 승인과 다른 payload라는 이유로 거절했다. snapshot 출처와 사용자 요청을 제시한 재검토도 거절됐다. 이 거절 시점에는 실제 외부 호출이 실행되지 않았다. 이후 사용자가 해당 runtime payload의 전송을 별도로 승인하여 아래 검증을 완료했다.

### 승인된 runtime 1건 — 실제 LLM→PostgreSQL→화면 E2E 완료

- 실행 스크립트: `scripts/run_local_live.sh`; backend 18200 / frontend 13200 / 독립 PostgreSQL host port 55432. 기존 shared checkout과 서비스를 변경하지 않았다.
- 검증 candidate: `7bd23dae9e7cc2cbe3f2e467db0b3f3cae55a5c8`, 구현 코드 `cbf4126c`와 동일.
- 범위: 공식 V3.1 로컬 데모의 `CNC-S04-L02-03`, `RESULT#CNC-S04-L02-03#2026-08-29T23:00:00+09:00`, OpenAI `gpt-4o-mini`.
- manager 생성 요청: cache 미존재 202 → POST 200, `mode=llm`, `fallback=false`, validation errors 0. 이후 GET/POST 모두 동일 저장본을 재사용했다.
- DB 직접 조회: Summary `ready`, mode `llm`, 실행 `completed`, 실행 trace의 summary ID와 저장 ID가 일치한다.
- 동일 summary ID: `82e931af-48d8-4e5d-befb-f405cf6b1b27`; workflow ID: `a4206204-37e9-4f34-81bb-6d02adbff5ad`.
- engineer 브라우저 세션의 GET도 동일 summary ID, `mode=llm`, `reused=true`, status 200이다. 화면에 **LLM 브리핑 / 저장본 재사용 / 현재 역할은 저장된 브리핑만 조회 / 갱신 권한 없음**을 확인했다.
- Packet과 ViewModel의 event identity가 동일하다. 화면에 남아 있는 `시간 불명`은 runtime evidence_context의 미제공 정보를 나타내며 as-of/관계 선별 검증 완료로 포장하지 않는다.
- [HTTP 및 직접 DB 증거](live-runtime-api-proof.json), [브라우저 응답·표시 증거](live-runtime-browser-proof.json).
- 실제 LLM 1건은 성공했지만 스트리밍 watcher, 실설비 입력, 모든 액션의 Closed-loop E2E, 반복 부하/장기 안정성 검증까지 의미하지 않는다. 이번 작업은 검증 기록만 변경했으며 구현 코드는 수정하지 않았다.


### 운영 Context DB 이관 후 검증

- PG `0049_versioned_operational_context`, SQLite `0045_versioned_operational_context` 추가. 배포 migration은 스키마만 생성하며 seed하지 않는다.
- 운영 runtime 및 OperationalDecisionSupport는 버전이 있는 DB Context를 읽는다. 기존 직접 fixture 로딩, 임의의 예약 재고/품질 상태 수정, 고정 생산량/손실 계산을 제거했다. 명시적인 GS/gold fixture 경로와 SOP reference는 별개이다.
- 조직/프로젝트 RLS, workspace/asset SQL 범위, evidence snapshot/as-of, 유효기간과 freshness, 저장 payload checksum을 검증한다. 모든 도메인을 한 SQL statement로 캡처하여 동시 import 전후 버전 혼합을 막는다. 생성 중 Context 교체 시 Brief 게시를 거부하며, 버전 변경은 Brief 및 Summary cache에 반영한다.
- 같은 manifest 재적재는 idempotent. 같은 버전의 다른 내용은 트랜잭션 전체 rollback. production importer는 synthetic data를 거부한다.
- 실제 runtime API 검사에서 수동 Packet 생성 경로의 기존 계약 불일치를 발견하여 ViewModel → 공통 Packet composer로 연결했다. Evidence Context는 기존 ViewModel 계약과 같은 optional Packet 필드로 추가했다. 재생 risk history의 source kind는 실제 출처를 보존하도록 JSON/TS 계약에 반영했다.
- 전용 로컬 PostgreSQL에 합성 스냅샷 **14건** 적재, 재적재 **inserted 0 / unchanged 14** 확인. 유효기간을 바꾸지 않았다. `2026-08-29` 선택 결과에 해당하는 계획은 없으므로 생산 영향은 미산정이다. 숫자를 보여주려면 해당 시점의 승인된 원천 Context가 필요하다.
- 최종 backend/PostgreSQL/migration/contract/gold/eval: **384 passed, 2 skipped**, 121.14s. skip은 SQLite에서 PG RLS 전용 검사와 제거된 Adaptive Modeling Workbench 검사이다.
- Frontend adapter **12 passed**, TypeScript 검사 및 production build pass. 실제 브라우저 화면 재검증은 이번 변경에서 수행하지 않았다.
- 기존 로컬 실행 스크립트로 backend 18200 / web 13200 재기동. 실제 Packet과 Detail은 **JSON schema 통과**, 동일 event와 ViewModel projection 후 동일 근거를 반환한다. Context 변경으로 기존 live summary는 재사용하지 않는다.
- 새 Context로 deterministic fallback 요약 POST 200 → 저장본 GET 200 및 같은 ID 재사용 확인. 외부 provider를 호출하지 않았으므로 이 결과는 새 코드의 실제 LLM 품질 증거가 아니다.
- [DB/API 검증 증거](operational-context-db-proof.json), [운영 적용 절차](../../operations/operational-context-db-migration.md).
- **원격 운영 DB에는 적용하지 않았다.** DB 연결 대상 및 migration/import 역할 확인이 남아 있다. 실 MES/WMS/QMS 커넥터나 현재 시점 운영 데이터를 확보했다는 의미도 아니다.

최종 명령은 기존 backend suite에 `tests/test_operational_context_repository.py`, `tests/test_operational_context_import_cli.py`, `tests/test_operations_presentation_readiness.py`, `tests/test_migration_numbering.py`를 추가한 것이다. CI workflow에도 새 Context/API 회귀 검사를 포함했다. 원격 CI는 아직 실행하지 않았다.

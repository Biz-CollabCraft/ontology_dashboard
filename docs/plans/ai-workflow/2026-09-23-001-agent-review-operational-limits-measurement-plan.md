---
title: 지속 이벤트와 느린 LLM에서 생성·조회 분리의 보장 범위 검증
type: evaluation
status: blocked-on-contract-decision
date: 2026-09-23
---

# Ontology Dashboard 단일 엔지니어링 질문 검증 계획

- 상태: **9/23 PostgreSQL 최소 재현 후 strict snapshot 계약 불일치로 STOP. 전체 P0 미완료. 9/24 제품/기술 종료조건 보강; 추가 DB 실험·제품 변경 없음.**
- 핵심 질문: **“지속적인 설비 이벤트와 느린 downstream/LLM 상황에서도 현재 생성/조회 분리 및 snapshot 기반 구조가 안정적으로 동작하는가?”**
- 수행 계약: **1 question → 1 experiment cycle → 필요한 improvement 1회 → 동일 workload re-test → STOP**
- 안정성의 의미는 아래 scoped 조회 응답·snapshot 일치·최신 설명 준비 상태·중복 생성·미완료 처리량으로 한정한다. 한계 없는 시스템이나 모든 이벤트 처리 보장을 목표로 하지 않는다.
- 이번 요청은 계획서 수정만이다. 아래 계측·실험·개선 작업은 미래 실행 계획이며 지금 구현하지 않는다.

## 0. Product DoD + 이번 Deep Dive 1개 (2026-09-24)

[실행 결과](../../eval/2026-09-23-ontology-p0-contract-boundary-report.md)가 당시 “미실행” 계획보다 현재 상태의 근거다. 기존 scope 축소·최대 1회 개선 원칙은 유지한다. 새 runtime 병목을 계속 찾기보다 **현재/이력 snapshot 설명의 정확한 소비 계약**을 먼저 닫는다.

| 평가축 | 실제 근거 / 부족한 증거 |
|---|---|
| 문제정의/도메인 | 설비 이벤트의 근거/설명 제공 흐름; 현장 freshness 요구와 historical 허용 기준은 사용자 결정 미정 |
| 기술적 깊이 | 저장 직전 binding guard와 exact/latest lookup, raw context-change 재현; 기대 계약 충돌 해소·같은 조건 전후 검증 |
| 기술적 판단 | 후보축소/생성조회 분리 자산, strict gate에서 중단; exact-only 또는 historical+readiness 채택 미정 |
| 검증 | 저장 보고서의 179 rows·GET5·provider11·GET 유발0, in-flight 저장 차단; 지속 workload·운영 p95·전체 RLS·실제 모델 품질은 이 표본으로 입증 불가 |
| 제품 완성도 | API/UI에 이력 표시 구현; 새 strict 계획과 제품 표시 계약 일치·제3자 재현 확인 |
| 운영 현실성 | 단일 TestClient/PG 재현; 다중 worker·crash·운영 부하 미검증; 이번 범위 밖 |
| Ownership/협업 | Git 경계·실험/독립 oracle 자료; 실제 사용자 계약 결정과 후속 리뷰의 출처; 팀 전체 기여를 개인 성과로 합치지 않음 |

**Product DoD / Product STOP:** 한 설비의 event→근거→생성→저장→GET/UI 확인 흐름에서 pending/exact/historical/error가 사용자에게 구분되고, 근거/source key를 추적할 수 있다. GET 생성0, 잘못된 scope/새 key로 과거 prose 재표시0, 오류/지연 안내와 README의 격리 재현이 통과하면 해당 로컬 demo 제품 범위를 종료한다. 어떤 historical 표시를 허용할지는 사용자 소유이며 현재 미정이라 완료 처리하지 않는다.

**Deep Dive 1개:** 생성 중 context 변경과 exact miss에서 결과의 snapshot identity를 보존하는 경계. 기존 evidence selection은 중요 회귀로 재사용하되 새 budget/selection 최적화 캠페인을 병행하지 않는다. 이미 확보한 반례가 service lookup/materializer/UI에 연결되고 측정 가능하기 때문에 이 질문을 택했다.

**Vertical experiment:** 보존된 preflight-03의 pending/exact/historical 3상태와 in-flight 변경을 최소 회귀로 축소 → `service.py::cached_agent_review_summary_for_packet`의 exact→latest와 validate_binding을 추적 → 현재 readiness와 과거 설명을 섞지 않는 invariant → 기존 유지/ exact-only / historical+readiness 구분을 같은 case로 비교 → 사용자 선택 후 최대 1개 변경 → 같은 provider-delay·snapshot mutation에서 stale 저장/identity/GET 생성0 재검증 → 상태별 분모·current-ready 지연·과거 설명 가용성 trade-off와 한계 기록. 신규 queue/OTel로 먼저 우회하지 않는다.

AI System의 핵심은 snapshot/evidence attribution이며, Model/API는 지연·timeout/schema 실패가 계약을 어떻게 통과/거부하는지다. 현 `agent_context_tool_pipeline.py`에는 선택→실행→검증의 직렬 `StateGraph(dict)` 실험과 simple fallback이 있으나, 이 코드만으로 과거 “LangGraph 상태가 꼬였다”의 원인을 reducer/checkpoint로 단정할 수 없다. 관련 코드와 LangGraph/state Git log를 확인했지만 원인 commit·실패 trace를 특정하지 못했다. 당시 revision/입력/예상·실제 state가 복원될 때만 별도 후보로 열고 지금은 두 번째 Deep Dive로 추가하지 않는다.

**Engineering STOP:** 현재 strict 조건 미충족의 재현/원인/후보 비교는 있으나 최종 채택·필요 변경·동일 재검증이 없어 미완료다. 선택된 소비 계약으로 검증을 닫고, 남은 지속 부하/다중 worker 한계와 trigger를 기록하면 종료한다. 사용자 선택이 없으면 decision pending으로 STOP하며 실패를 pass로 바꾸지 않는다.

Non-goal: selection 재개발, 새 framework·durable graph·모델 경쟁·무제한 부하. Expansion Trigger: 같은 key/scope 계약에서 재현되는 실제 breach 또는 합의한 freshness를 막는 측정된 원인. **다음 코드 작업 1개는 보존된 3상태를 작은 contract regression으로 고정해 “HTTP200/historical ≠ current-ready”를 분리 검증하는 것**이다. 제품 응답 정책 변경은 사용자 결정 뒤다.

## 0.1 Human-Owned / AI Delegation — 2026-09-24

| 영역 | Human-owned Knowledge / 판단 | AI 활용 | 검증 |
|---|---|---|---|
| 문제·계약 | current-ready와 historical 가용성, 허용 freshness·fallback | 사례/대안 비교표 | pending/exact/historical 직접 설명 |
| invariant | prose의 원래 scope/key 보존, GET 생성0, in-flight 변경 저장 차단 | 지연/변경 fixture·계측 | key/provenance·저장 결과·호출 수 대조 |
| 구현 | exact→latest lookup, 저장 직전 binding guard, UI 이력 표시 | 최소 contract test·선택한 정책 구현 | 코드 추적·작은 변경·실행 전 예측 |
| 평가·주장 | stale를 current라 하는 FP, 유효 이력 거부 FN, 계약별 oracle | 상태별 분모/원시 로그 집계 | HTTP200을 current-ready로 세지 않음 |

**Specification 초안:** Problem=과거 설명 제공과 strict snapshot 기대의 불일치. Constraint=생성/조회 분리·현 storage 유지, 정책 선택 전 제품 변경 없음. Invariant=GET provider 호출0, 과거 prose를 새 key/current로 재표시0, context 변경 후 stale 저장0. Acceptance=선택한 소비 계약으로 3상태와 in-flight 재현이 일치. Failure=identity 위조/잘못된 저장/조회가 생성 유발. exact-only와 historical+readiness의 선택·허용 대기시간은 사람 소유이며 미정이다.

**핵심 코드/Defense:** `systems/backend/app/operations/service.py::cached_agent_review_summary_for_packet` 및 `validate_binding`, materializer lookup/publish 경로. `agent_context_tool_pipeline.py`의 실험 graph를 현재 실패 원인으로 단정하지 않는다. 필요한 지식은 snapshot binding·read/write 시점이며 LangGraph checkpoint 학습을 새 목표로 넣지 않는다. 작성자 provenance와 본인 숙지 증거는 별도 미확인이다.

**Prediction / 다음 코드 1개:** 보존된 pending/exact/historical 3상태를 contract test로 축소하기 전, exact miss와 생성 중 context 교체에서 반환 key·current-ready·저장 유무·provider 호출 수를 예상한다. 사용자 선택 전 oracle를 AI가 확정하지 않는다. 평가의 truth는 고정 source/key와 실제 저장·호출 trace이며 모델 문장 품질은 별도 Gold가 필요하다. 절약할 fixture/계측/반복 시간을 binding guard와 과거 결과 가용성 trade-off 설명에 투자한다.

### Human Gates와 학습 종료조건

아래 명세는 **AI 제안**이며 사용자가 자기 말로 Problem·Constraint·Invariant·Acceptance·Failure 다섯 항목을 기록하기 전에는 전체 구현을 위임하지 않는다. 기존 계획의 가설·선택이나 AI 작성 문서를 사용자의 판단으로 소급하지 않는다. 현재 본인 숙지 증거와 새 Gate 기록은 **unrecorded**이며 지식이 없다고 단정하지 않는다.

순서: AI 자료/코드 탐색 → **Problem Gate**(문제·범위·불변식 설명) → AI 대안 → **Decision Gate**(차이·제약·실패·선택 이유) → **Prediction Gate**(실행 전 예상 상태/이유/반증을 시각·revision과 기록) → AI 구현·자동화 → 실행 → **Evidence Gate**(예상 대비 결과·증명 범위·추가 실험 필요 판단) → AI 집계/문서 → **Defense Gate**. 기존 decision/evidence 기록에 사용자 원문과 AI 후보를 분리한다. 이미 본 결과는 사전 예측으로 쓰지 않는다. 준비용 fixture/harness 초안은 가능하지만 채택/실행/사람 판단 완료와 구분한다.

**Engineering STOP 추가:** 아래 Deep Dive를 AI·README·메모 없이 약 15분 동안 문제→도메인/runtime→현재 코드 흐름→실패→대안/선택→시험 설계→실제 결과→한계/확장 조건 순으로 설명한다. 핵심 코드를 읽고 작은 변경을 직접 수행하며 실행 전에 영향·디버깅 방향을 설명한다. 기존 Product STOP과 측정 범위는 그대로 유지하며 사람의 설명 증거를 코드 테스트 통과로 대체하지 않는다.

학습 우선순위는 “이 코드/기술이 핵심 engineering claim을 성립시키는가?”로 좁힌다. YES인 runtime 동작만 공식 문서/필요한 source·test → 최소 재현 → 사전 예측 → 실행 비교로 확인한다. 나머지 CRUD/UI/서식은 AI 초안과 검토로 처리한다. 절약 시간이나 숙련도 개선은 측정 전 수치로 주장하지 않는다.

## 1. 조사 기준과 기존 작업 보존

- 실제 저장소: DevSpace Max `/Users/hb/Projects/ontology-dashboard`.
- origin: `https://github.com/Biz-CollabCraft/ontology_dashboard.git`.
- 조사 HEAD: `71337cddd755eaa8cdb762af4598e21b2f7d085f`.
- 작업 시작 시 기존 변경: `AGENTS.md`, `docs/plans/ai-workflow/README.md`, untracked `docs/engineering/`. 이 문서는 이 변경을 덮어쓰지 않는 새 active slice다.
- 적용 규칙: `AGENTS.md`, `docs/engineering/ai-assisted-engineering-workflow.md`. Human hypothesis/decision/Changed belief를 AI가 대신 확정하지 않는다.
- 저장소 관례에 따라 `docs/plans/ai-workflow/YYYY-MM-DD-NNN-...-plan.md`에 추가한다. 과거 계획·결과를 새 가설로 재작성하지 않는다.
- 코드와 기록을 읽었으나 이번에는 서버 시작, DB 변경, provider 호출, 테스트/benchmark를 실행하지 않았다. 아래 역사적 pass는 해당 당시 revision·fixture 범위에 한정한다.

## 2. 현재 보장과 미검증 경계

문서 경로는 저장소 root 기준이다. 테스트 코드 존재, 과거 실행 기록, 현재 runtime 통과를 구분한다.

| 영역 | 확인한 구현·기존 검증 | 이번에 남은 검증 |
|---|---|---|
| Python/API/DB 기반 | FastAPI backend, PostgreSQL/SQLite migrations, Python tests, `.github/workflows/backend-decision-support.yml`의 PostgreSQL 16 test job 존재 | 이미 있는 기술을 “도입 예정”으로 쓰지 않음. 현재 HEAD의 CI 성공·운영 배포 상태는 이번에 확인하지 않음 |
| 생성/조회 분리 | `agent_review_summary_materialization.py::lookup`은 저장본 조회만 수행. `materialize`에서 생성·검증·저장. service의 cached 경로 존재 | 병렬 event 유입·LLM 정체 중 실제 API GET p95와 DB 자원 공유에 의한 영향 |
| snapshot 정합성 | key에 scope/context/source/prompt/model 등 identity 반영, cached validation, service의 저장 직전 binding 재확인 | 지속 교체·out-of-order·재시작 중 잘못된 최신 identity 반환/저장 여부. “항상 최신 prose 있음”은 별도 보장 |
| 동일 key 실행 방어 | process lock, DB running unique index, stale lease recovery 존재. service 상수 lease 120초, 충돌 대기 helper 기본 3초 | 다중 프로세스와 실제 느린 provider에서 불필요한 동시 호출·대기 오류·lease 회수 후 늦은 완료 범위 |
| 원자적 publish/fencing | `tests/test_materialization_lease_fencing.py`가 SQLite/PostgreSQL 양쪽에 publish+terminal 전이, 회수된 worker의 overwrite 금지, 저장 실패 rollback을 검사 | 테스트가 존재함을 확인. 이번 실행 pass 아님. 실제 프로세스 종료·지연·재기동을 포함한 다중 worker 부하로 확대 검증 |
| watcher/중복 병합 | `watch_agent_review_summaries.py`가 polling 실행. service는 같은 인스턴스·설비·scope의 미시작 background 요청을 최신 pending으로 병합. 실행 중 호출과 명시 event 요청은 대체하지 않음 | process-local 병합의 다중 worker 범위, candidate scan fairness, 실제 backlog. 기존 기능을 “새 queue 구현”으로 중복 계획하지 않음 |
| 정책 | `always` 기본, `hybrid/demand` 선택 구현. baseline은 마지막 성공 생성/최초 관측을 프로세스 메모리에 유지 | 재시작·급격한 변화에서 정책별 최신 설명 가용성. 정책 유예를 cache hit로 세지 않음 |
| selection | `operational_evidence_selection.py`, provider의 selected evidence prompt 경로와 평가 테스트 존재 | 후보 수/관계 fan-out 증가 시 query·selection latency와 필수 근거 보존. 과거 작은 fixture 효과를 대규모 성능으로 일반화하지 않음 |
| 장애 주입 평가 | 기존 72-row B1/B2/B3 비교와 timeout/malformed/snapshot mismatch 경계, 별도 reliability/temporal 평가 문서 존재 | 지속 이벤트×느린 downstream×다중 worker 부하·복구. 72회를 “72종 운영 장애”로 표현하지 않음 |

### 기존 평가를 재사용하는 정확한 범위

1. `docs/plans/ai-workflow/2026-09-01-004-feat-agent-workflow-stability-evaluation-plan.md`: 8 cases×3 arms×3회=72-row 비교. timeout/malformed/mismatch를 다루며 동시 key·stale recovery는 기존 contract tests와 구분한다. 429/transient 5xx는 후속 항목이다.
2. `docs/eval/2026-09-03-agent-workflow-final-evaluation-report-960f4713.md`: 과거 revision의 live 120회, 서비스 11 scenarios, container PostgreSQL 5 tests 통과 기록. PostgreSQL 5 tests는 **Operational Decision Support** 경로를 포함하므로 Agent Review 모든 경로의 다중 worker 보장으로 전용하지 않는다. 문서 자체가 production load/soak 미검증이라고 명시한다.
3. `docs/eval/2026-09-03-decision-support-stability-evaluation-report.md`: 96-run 시간 fault simulation, SQLite 신뢰성 11개. 운영·실제 제조 연동 보장이 아니다.
4. `docs/plans/ai-workflow/2026-09-04-001-db-backed-agent-review-watcher-plan.md`: DB-backed candidate→watcher→live LLM→consumer 동일 summary identity의 1건 증거 및 smoke. 지속 처리량의 증거는 아니다.
5. `docs/eval/2026-09-09-briefing-efficiency/generation-read-separation-report-ko.md`: SQLite 저장본 1,680회 조회 p95 12.74ms는 로컬 메서드 실측. 93.33% token 감소는 과거 실호출 기록을 이용한 재생이며 운영 API 지연·신규 호출·청구 절감이 아니다. 신규 P0 baseline과 직접 전후 차감하지 않는다.
6. `docs/eval/2026-09-09-briefing-efficiency/pr-verification-ko.md`: 같은 인스턴스 병합·GET 생성 금지·99 backend/17 frontend 통과 기록. 216조건의 정책 scheduler 재생은 실제 병합·운영 부하 시험이 아니며 다중 worker 병합은 제외한다.
7. `docs/eval/2026-09-07-pr167-briefing-final-evaluation.md`: 선택 정책과 exact reuse 차이, 합성 시간축, 일부 PostgreSQL skipped 경계를 기록. 과거 모델 선정·수치는 현 demo 설정이나 현 HEAD 결과로 옮기지 않는다.

기존 대화의 “후보 27→6, token 약 29%”는 버전·원시 결과를 이번 조사에서 동일 조건으로 확정하지 않았다. 다른 문서에는 후보 29→8 등 다른 조건이 있으므로, 신규 계획의 성과 수치로 복사하지 않는다. selection을 이미 구현·평가했다는 사실과 현재 처리 한계는 구별한다.


### 이번 수정에서 다시 확인한 것

HEAD와 working tree 상태, service의 process-local queue scope·superseded 처리·저장 전 validate_binding, materializer의 lookup·provider invocation 계측, 120초 lease 상수를 다시 확인했다. 위 기준과 동일하다. 9월 9일 briefing-efficiency 검증 문서도 다시 읽었다. **기존 생성/조회 분리·selection·snapshot guard·병합·장애 평가를 새 구현/새 성과로 계획하지 않는다.** 위의 광범위한 조사표는 배경 근거이며 전체 테스트 matrix를 뜻하지 않는다.

## 3. 질문의 범위와 판단 계약

이번 cycle은 **현재 단일 watcher/서비스 경로에서 지속적인 Product Result 이벤트를 처리하는 동안 느린 LLM이 설명 준비와 조회에 미치는 영향**을 검증한다. 원래부터 여러 stage인 경로의 대기 위치와 snapshot 일치를 함께 본다.

- Observed problem: 구현·기존 평가가 존재하지만 지속 유입과 느린 LLM이 겹치는 API/DB workload의 처리 특성은 별도 증거가 필요하다. 현재 운영 장애를 관측한 것은 아니다.
- Human hypothesis: 원인 가설 unrecorded. 사용자가 질문과 1회 cycle 제한을 정했다.
- AI/challenger hypothesis: provider 지연이 생성 완료와 최신 설명 준비를 늦추며, 공유 자원/순차 처리 때문에 다른 설비 조회나 대기에도 영향을 줄 수 있다.
- Falsification condition: provider 지연만 바꾼 반복 비교에서 GET·대조 설비·DB wait·미완료 age가 악화되지 않고 snapshot 계약이 유지되면 그 조건의 장애 전파 가설을 기각한다.
- Decision required: 필요한 최신 설명 준비시간과 허용 pending/fallback, 관측한 한계에 한 가지 개선이 필요한지와 비용 수용.
- Unknowns: 현재 배포의 interval/limit/provider timeout, 실사용 변화·조회 빈도, 배포 인스턴스 수. 이번 결과는 고정한 시험 topology에만 적용한다.

판정 불변조건은 ①GET에서 생성 호출 0 ②반환 prose와 요청 snapshot/scope 일치 ③LLM이 업무 side effect를 만들지 않음이다. **빠른 pending 응답과 최신 AI 설명 완성은 서로 다른 성공 기준**으로 보고한다.

## 4. 한 번의 cycle과 P0 범위

| 단계 | 할 일 | 하지 않을 일 |
|---|---|---|
| P0 | 기존 경로 고정, 최소 이벤트 replay, 지연/timeout 비교, stage 원인 규명 | queue·worker·새 정책부터 구현 |
| 조건부 대안 비교 | 관측한 한 원인에 해결 대안 최소 2개 + baseline의 작은 비교 | 모든 후보 production 구현 |
| 개선 1회 | 하나의 병목/전파 경계를 해결하는 변경만 선택 | 다음 병목까지 연속 개선 |
| 재검증·종료 | 동일 workload before/after와 Known Limitation 기록 | 목표 수치가 나올 때까지 loop 반복 |

P0 환경: 폐기 가능한 PostgreSQL, 현재 migrations와 scope/RLS, 현재 backend·watcher·selection·snapshot·generation policy. 단일 watcher와 현재 코드 기본 always를 유지한다. 실제 interval·limit·timeout·worker 수를 기록하고 전후 동일하게 유지한다. **기존 계획의 “기본 60초 대신 5초 interval” 변경은 baseline에서 제거한다.**

기존 fixture에서 유효한 합성 10설비로 시작한다. 운영 사용자·실제 공장 데이터라고 부르지 않는다. 원인 확인에 꼭 필요한 경우에만 설비 수를 100까지 확장하며 이는 목표 규모가 아니다. provider는 valid candidate/지연/timeout을 제어하는 test double을 사용한다. 앱의 실제 검증·저장·조회 경로는 유지한다. provider 품질·실청구 절감은 측정하지 않는다.

manifest에는 revision/dirty diff, DB/schema/resource, fixture hash·event 순서, policy, watcher interval·limit, provider timeout/retry, 조회 rate, 실험 clock을 고정한다. 관련 기존 contract 회귀는 실행 단계에서만 확인하며 기존 정확도·모델 비교 72/120회 평가를 반복 과제로 만들지 않는다.

## 5. 단일 workload와 제한된 scenario

입력은 Product Result/Evidence가 DB-backed candidate로 보이는 경계에 넣는다. raw sensor tick와 summary 생성 횟수를 같은 event throughput으로 계산하지 않는다. API/DB를 통과하지 않는 fixture 실험은 service-level이라고 명시한다.

한 event sequence 안에 여러 설비의 지속 변화, exact 반복, 한 설비 burst, 생성 중 snapshot 변경을 포함한다. 동일 파일·seed·조회 스케줄을 정상/지연/timeout 및 before/after에 재사용한다. 전체 조합을 곱하지 않는다.

| 구간 | 입력·조건 | 확인 목적 |
|---|---|---|
| W0 순차 대조 | 준비된 exact 저장본과 miss key를 각각 조회, provider 0.1초 | 기존 read/generate 경계, baseline stage time |
| W1 지속 유입 | 10설비에 총 0.2 event/s, GET 1 req/s를 초기 제안값으로 사용. 기본 watcher 설정 유지 | 정상 처리율, latest-ready·pending, scan 주기 영향 |
| W2 반복·burst·경쟁 | 같은 exact key 반복 10회와 한 설비 새 snapshot 10개 burst; 생성 중 다음 snapshot 도착. 다른 설비는 대조군 | reuse·중복 생성·stale 차단·설비 간 영향 |
| W3 느린 LLM | W1/W2의 같은 sequence에서 provider 지연만 10초로 변경 | 어느 stage의 대기가 늘고 조회/준비시간으로 전파되는가 |
| W4 timeout→복구 | 동일 sequence 중 한정된 60초 구간에 provider timeout 주입 후 정상 복구 | fallback·미완료 age·복구 drain과 대조군 영향 |

실행 전 수치는 고정한다. W1의 초기 rate가 현재 topology에 과하면 0.1로 낮춘 대조를 추가하고 원래 run을 숨기지 않는다. 정상 rate에서 차이가 보이지 않으면 최대 3단계(예: 0.2→0.5→1 event/s)까지만 올린다. 처리 한계 또는 원인 설명에 충분한 evidence가 확보되면 즉시 탐색을 끝낸다.

“의미 변화 없음”도 **exact identity 동일**과 **의미만 유사하고 source/snapshot key는 달라짐**으로 나눈다. 후자는 cache hit를 강제하지 않으며 이전 prose를 새 identity로 옮기지 않는다. always 정책에서 “100 events 중 의미 변화 3개니까 LLM 3회”라는 기대값을 두지 않는다.

기본 watcher scan으로 같은 key 경쟁이 발생하지 않으면 이미 존재하는 생성 경로에 동일 key 2요청을 보내는 최소 probe만 같은 sequence의 보조 구간으로 둔다. 다중 프로세스 토폴로지로 확대하지 않는다.

warm-up은 최소 2 poll cycles, 측정은 최소 3 poll cycles 및 3분 중 긴 쪽. 대표 정상/지연 쌍과 fault sequence를 각각 3회 반복하고 종료 후 최대 300초 drain한다. P0 실행 예산 제안 90분. 표본이 작으면 n과 미완료 수를 기록하고 p95 장기 보장을 주장하지 않는다.

## 6. 최소 측정 지표와 판별 기준

| 지표 | 정의와 분모 |
|---|---|
| event throughput | offered/admitted/처리 상태가 확인된 Product Result events/s. generation starts·ready summaries와 구별 |
| latency | event visible→첫 exact consumer-ready E2E p95, GET hit/miss/pending p95, 주요 stage duration |
| error/timeout | 정상 기술 오류, 주입 timeout, 허용 fallback을 분리. 미완료 요청 수·age를 함께 보고 |
| snapshot reuse | exact validated 저장본을 반환한 lookup / 전체 lookup. ready와 fallback reuse 구분 |
| generation/call | key별 generation start·provider 경계 호출·중복 호출. 내부 HTTP retry/repair는 관측 가능할 때 별도 |
| 정합성 | stale/wrong-scope output 건수, GET 유발 generation 수, unexpected side effect 수 |
| pending/backlog | 주입 manifest와 처리 기록으로 계산한 미완료 required 최신 상태 수·oldest age·복구 drain |

실제 queue가 없으면 **queue depth를 보고하지 않는다.** 위 pending/backlog는 재구성한 미완료 상태이며 broker 지표가 아니다. superseded·deferred·failed terminal을 유실과 구분한다. latest-only 경로가 중간 event 모두를 보존한다고 가정하지 않는다. queue가 실제 존재하거나 후속 비교에 도입할 때만 실제 depth를 별도 관측한다.

정상 단순 provider 대역·명시 refresh/실패 없음에서 같은 key가 1회보다 많이 생성되면 duplicate 후보로 보고 원인을 확인한다. provider boundary 호출=HTTP 1회라고 가정하지 않는다. timeout 뒤 재시도는 정상 키 중복과 별도 분류한다.

- Hard failure: stale/wrong-scope prose, GET generation, unexpected 업무 side effect 중 1건이면 해당 보장 실패. 입력/trace/DB 상태를 보관하고 더 높은 rate는 중단한다.
- 전파 후보: 지연 run에서 대조 설비 GET p95가 동일 rate 정상 run의 2배 초과하거나 비주입 기술 오류 >1%가 두 관측 창 연속 지속.
- 처리 한계 후보: 미완료 required 수와 oldest age가 3 poll cycles 연속 증가하거나 종료 300초 후에도 미완료가 남음.
- 설명 지연은 provider가 느려진 만큼 증가할 수 있다. 이를 무조건 버그로 부르지 않고 poll 대기/직렬 대기/LLM/저장 중 증가분을 분해한다. 필요 freshness는 실행 전에 별도 고정하며 현장 SLA를 만들어내지 않는다.
- 중단: 30초 완료 0 또는 30초간 비주입 technical error >10%이면 새 유입을 끊고 drain한다.

## 7. Observability — 기존 계측 우선, 필요 시 최소 tracing

경로는 `event → context selection → snapshot validation → generation decision → LLM → view model`이다. 전체 p95만으로는 어느 단계가 원인인지 모를 수 있으므로 **stage breakdown 필요성은 있다. 다만 OTel 채택은 아직 결정하지 않는다.**

1. 기존 decision/lookup/completion/failure 로그와 generation_metrics를 먼저 inventory한다. event_id, snapshot/summary key, workflow_run_id로 연결 가능한지 확인한다.
2. 기존 로그 + 시험 manifest + monotonic stage timestamp로 하나의 실패/지연 event 경로를 재구성할 수 있으면 거기서 끝낸다.
3. 서로 다른 단계·생성/조회 요청을 연결할 수 없거나 지연 위치가 불명확할 때만 **최소 tracing**을 계획한다.

조건부 최소 tracing 계약:

| 항목 | 필요한 내용 |
|---|---|
| 식별 | trace_id, event_id, snapshot/summary key, workflow_run_id, 생성/조회 request_id |
| span | event receive, context selection, snapshot check, generation decision, LLM generation, view model |
| 공통 필드 | start/end/duration, result/error class, parent 또는 link, attempt, scope의 시험 식별자 |
| 경계 | background 생성과 나중 GET는 같은 연속 요청으로 꾸미지 않고 summary key/span link로 연결. 기존 stage가 없으면 임의 span을 만들지 않음 |
| 출력 | 우선 JSON 등 로컬 조회 가능한 최소 기록. OTel SDK는 연결/전파 구현에 필요할 때만 비교 후보 |

목적은 latency breakdown, downstream 지연 영향, 장애 전파 위치, 동일 event의 경로 추적이다. P0 계측이 business policy·동시성·snapshot 의미를 바꾸면 안 되며 계측 설정은 before/after 동일하게 유지한다. prompt/응답 본문·키·민감정보를 span에 담지 않는다.

**관측 작업의 종료조건:** “문제가 발생했을 때 요청/이벤트 하나의 처리 경로를 따라가면서 주요 병목 또는 실패 위치를 정량적으로 특정할 수 있음.” Grafana/Prometheus/Loki/Tempo 전체 구축·영구 모니터링 플랫폼·tracing 자체의 포트폴리오 기능화는 제외한다.

## 8. 원인 규명 후 최소 2개 대안 비교

먼저 정상/지연의 동일 event 경로를 대조하고, 증가 시간이 어디서 발생하는지 숫자로 설명한다. LLM이 느리다는 사실만으로 queue 필요성을 결론 내리지 않는다. 원인 확정을 위해 변수 1개만 바꾸는 작은 probe는 같은 cycle에 포함하되, 다른 병목으로 실험 범위를 옮기지 않는다.

failure 또는 필요한 범위의 한계가 확인된 경우에만 아래 중 **관측 원인을 해결할 대안 최소 2개**를 고른다. baseline은 별도 0번 선택지다. 모든 행을 실행하지 않는다.

| 관측 원인 | 비교 가능한 두 방향 | 비용과 판별 근거 |
|---|---|---|
| 생성 작업 대기가 조회로 전파 | 기존 생성 경로의 실행 자원 분리 vs bounded generation concurrency | 같은 sequence의 GET/ready p95, 미완료 age, 자원 비용 |
| 같은 상태의 생성 낭비 | 현재 guard/병합 범위의 최소 보강 vs 기존 정책 옵션 제한 활용 | 호출 수와 exact current-ready 가용성·중요 변화 지연. old prose 재사용 금지 |
| 처리량보다 유입이 많아 pending 증가 | bounded admission/최신 상태 병합 vs 기존 DB job/worker 활용 또는 최소 async queue | 완료 지연·생략 의미·최종 정합성·운영 복잡도. queue가 서비스율을 자동 높인다고 가정하지 않음 |
| 실제 지배 구간이 query/scan | query/index의 좁은 수정 vs scan 범위/batch 조정 | 동일 selection 계약·scan 대기·query 시간. 신규 DB 최적화 프로젝트로 확대 금지 |

격리된 작은 실험 또는 코드/실행 근거로 비교하며 불확실한 효과를 수치로 꾸미지 않는다. 후보 모두를 production 구현하지 않고, **하나의 개선만** 선택해 적용하는 계획을 작성한다. async/queue는 내구성·분리 요구가 실제로 확인된 경우에만 후보이며 Redis/Kafka를 먼저 선정하지 않는다.

선택 기준: scoped hard gate 유지, 관측한 지배 원인 개선, current-ready/GET/pending의 trade-off와 구현·운영 비용. 호출 감소만으로 policy가 더 낫다고 판단하지 않는다. Human decision과 Changed belief는 사용자가 기록할 때까지 pending/unrecorded다.

## 9. 재검증과 Stop Rule

선택 개선 1회 뒤 같은 event 파일·seed·입력률·topology의 비변경 조건·provider delay/timeout schedule·조회 시각·계측으로 재검증한다. 변경 자체가 topology라면 그 차이만 명시하고 자원 차이도 비용으로 보고한다.

before/after에는 stage/E2E/GET p95, 처리량·미완료 수/age, 오류·fallback, 호출·중복·reuse, stale 건수, n·반복 변동을 남긴다. 좋은 평균만 고르지 않는다. queue 후보는 빠른 접수 응답과 최종 consumer-ready 시간을 분리하며 실제 queue depth·drain을 추가한다. 필요한 contract 회귀만 재사용한다.

**보강 완료 Stop Rule:**

1. 미검증 지속 이벤트·지연 조건을 실제 시험했다.
2. failure 또는 현재 보장 범위를 정량 설명했다.
3. 하나의 주요 병목/전파 위치를 stage 근거로 특정했다.
4. 해결 대안 최소 2개와 baseline을 비교했다.
5. 선택 개선 1개만 한 번 적용했다.
6. 동일 workload의 before/after와 trade-off를 확인했다.
7. 남은 한계를 Known Limitation으로 기록했다.
8. 새 문제가 최초 질문의 scoped 결론을 무효화하지 않으면 후속으로 넘기고 **STOP**한다.

시험 범위가 충족되고 보강 필요성이 없으면 **측정 완료·현 구조 유지**로 종료하며 개선/절감 성과를 만들어내지 않는다. 보강 완료 항목 4~6은 해당 없음으로 표시한다. 원인 불명확이면 “관측 부족”, 개선 후 stale 등 최초 invariant가 깨지면 “채택 실패/보류”로 기록한다. 실패를 성공으로 닫지 않으며 두 번째 개선 cycle을 자동 시작하지도 않는다.

**“더 개선할 수 있음”은 추가 구현의 근거가 아니다.**

## 10. Known Limitations와 기존 계획 대비 축소

Known Limitation 양식: 조건 / 실제 증거 또는 미검증 / 최초 결론 무효화 여부 / 이번 제외 이유 / 별도 후속 질문. 아래 항목은 현재 미검증 후보이며 장애가 확정된 것이 아니다.

| 기존 항목 | 수정 |
|---|---|
| 100설비·2 project·여러 rate·정책 조합 | 합성 10설비·단일 topology·고정 event sequence. 꼭 필요할 때만 확장 |
| 다중 worker, lease 경계, crash/restart full matrix | P0에서 제외. 현재 cycle 결론을 해당 topology 밖으로 확대하지 않음 |
| 429/5xx/malformed/adapter fault 각각 시험 | LLM 지연·timeout→복구로 제한. 기존 장애·정확도 평가 재사용 |
| fan-out 5배·history 1만/10만·30분 soak | 기본 범위에서 제거. 다른 병목은 Known Limitation |
| baseline에서 polling interval 변경 | 현재 설정 고정. polling 조정은 원인 확인 후 선택 후보일 때만 |
| 모든 상태·비용·장기 tail 계측 | 질문에 필요한 throughput/p95/stage/호출/reuse/pending/stale만 선택 |
| 문제별 연속 P1/P2 개선 | 한 원인·최소 2대안·개선 최대 1회·동일 재검증 후 종료 |

비범위: context selection 재개발, 후보 축소 성과 재측정 캠페인, 모델/프롬프트 정확도 경쟁, snapshot 분리 재구현, 새 agent framework, 모든 센서 ingest·ML 학습, 실제 제조 시스템 연동, UI 기능, 운영 DB 부하/배포, Grafana/Prometheus/Loki/Tempo 일괄 구축, OTel 의무 도입, 신규 Redis/Kafka/Queue 확정, CI/CD 전면 개편.

퀄리타스 JD는 Python/API·RDB·비동기 처리·운영 검증 설명의 참고 기준이다. 이미 있는 기술과 테스트를 활용하며 기술 항목을 채우기 위해 도입하지 않는다. 재고 앱과 같은 대규모 transaction/queue 프로젝트를 반복하지 않는다.

## 11. 포트폴리오 서사와 결과 문서

서사: 제조 데이터에서 판단 근거를 안정적으로 제공 → context selection/snapshot/생성·조회 분리 → 기존 정확도·장애 주입 평가 → 운영 workload 검증 공백 확인 → 지속 이벤트·느린 downstream 측정 → 병목/장애 전파 위치 특정 → 필요 시 개선 1회 → 동일 workload 재검증 → 남은 한계·종료 이유.

향후 산출물은 experiment manifest, 고정 event sequence, 대표 stage trace, 최소 failure 증거, 대안 비교표, before/after, Known Limitation이다. SQLite 실측/기록 재생/정책 simulation/PostgreSQL E2E/live provider를 구별하고 raw 기록 위치·hash를 남긴다.

결과 문서의 10개 질문: ①발견 문제 ②중요성 ③기존 보장 ④미지 조건 ⑤실험 방식 ⑥원인 근거 ⑦비교 대안 ⑧선택 이유 ⑨실제 개선과 비용 ⑩왜 멈췄는가.

- Evidence: 실제 코드·기존 검증 문서 재확인, 계획 수정 완료.
- Result: not_measured — 새 runtime 시험·LLM 호출 없음.
- Implementation: 없음 — harness/계측/서비스/DB/CI 변경하지 않음.
- Human decision: pending. Changed belief: unrecorded.
- 현재 결론: 과거 검증을 재사용하되 운영 부하 보장으로 확대하지 않으며, 이번 질문에 필요한 한 cycle만 계획한다.

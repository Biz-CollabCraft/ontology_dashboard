# AI Evidence Consistency(AI 근거 일관성) & Snapshot Reliability(스냅샷 신뢰성) 계획

작성일: 2026-09-25  
저장소: `/Users/hb/Projects/ontology-dashboard`  
시작 기준: `main` @ `05be8c8e0e73040420dfb8b040e8d0b74fe473fa`  
실행 환경: DevSpace Max(DevSpace Max) workspace `ws_2273d631b2`를 우선 사용한다.  
Source of truth(원본 진실원천): 이 저장소의 코드, 계획, evidence(근거), decision(결정)이다. Career OS는 원본 링크, 요약, 역량 연결만 가질 수 있다.

## Problem framing(문제 정의)

- **Observed problem(관측 문제):** 제조 예지보전에서 sensor event(센서 이벤트), maintenance history(정비 이력), operational context(운영 맥락)가 바뀌는 중 slow provider(느린 제공자) 호출이 완료되면 서로 다른 시점의 evidence(근거)가 섞이거나, historical result(과거 결과)가 current result(현재 결과)처럼 소비될 위험이 있다. 2026-09-23 P0는 generation 중 context mutation(문맥 변경)의 저장을 차단했지만, exact miss(정확 일치 실패)에서 `LATEST_STORED`를 반환하는 policy(정책)와 strict current(엄격한 현재성)의 차이를 확인하고 STOP했다.
- **Human hypothesis(사람 가설):** unrecorded(미기록).
- **Human prediction(사람 예측):** unrecorded(미기록).
- **AI/challenger hypothesis(AI/반대 가설):** snapshot identity(스냅샷 식별자)와 deterministic evidence selection(결정론적 근거 선택)을 LLM summary(요약)와 분리하고, exact/current/historical(정확/현재/과거) 상태를 명시하면 stale result(오래된 결과)의 current-ready(현재 준비 완료) 오인을 막을 수 있다. fallback(대체 요약)은 `EXACT_VALIDATED`가 아니어야 한다.
- **Falsification condition(반증 조건):** 동일 fixture(픽스처)에서 (a) fallback이 `current_ready=true`가 되거나, (b) exact/historical/pending(정확/과거/대기) 중 어느 상태든 API와 ViewModel(뷰모델)의 의미가 다르거나, (c) mutation 후 다른 snapshot key(스냅샷 키)를 저장하면 AI 가설을 기각하고 변경을 되돌릴 후보로 둔다.
- **Decision required(필요한 사람 결정):** 사용자가 (1) exact-only(정확 일치 전용), (2) exact current-ready(정확 현재 준비)와 disclosed historical fallback(명시된 과거 대체)을 분리, (3) historical fallback(과거 대체)을 현재처럼 유지 중 어느 제품 정책을 채택할지 결정한다. 이번 작업은 이 선택을 강제하지 않는다.
- **Stop condition / budget(중단 조건 / 예산):** 현재 P0 경로의 contract clarification(계약 명확화) 한 건, focused unit/integration/regression/contract(단위/통합/회귀/계약) 검증, 계획·evidence·decision 기록까지만 허용한다. provider(제공자) 호출, 실서비스, 새 제품 기능, LangGraph(랭그래프), multi-agent(멀티에이전트), RAG, queue(큐), OTel은 범위 밖이다. 검증 후 Decision Gate(결정 게이트)에서 STOP한다.

## Domain and responsibility boundary(도메인 및 책임 경계)

센서 이벤트는 계속 도착하고, 정비·운영 기록은 뒤늦게 정정될 수 있으며, 여러 화면·report(리포트)·recommendation projection(추천 투영)이 같은 summary를 읽는다. provider 호출은 느릴 수 있으므로 generation 중 context mutation을 정상 상태로 간주할 수 없다.

- deterministic policy(결정론적 정책)는 candidate(후보) 정렬, 필수 evidence(근거), dedupe(중복 제거), missing evidence(누락 근거), token budget(토큰 예산), snapshot key, scope(범위), publish eligibility(게시 적격성)를 소유한다.
- LLM은 이미 고정된 evidence set(근거 집합)을 summary/coordination(요약/조정)하는 역할만 가진다. LLM은 selector(선택기), current-state authority(현재 상태 권위), policy state(정책 상태)가 아니다.
- trace/provenance(추적/출처)는 evidence set hash(근거 집합 해시), snapshot key, provider call(제공자 호출), validator(검증기), publish(게시), UI consumption(UI 소비)을 연결한다.

## Snapshot identity(스냅샷 식별자) 후보와 계약

| 후보 | 장점 | 한계 | 현재 계약에서의 역할 |
| --- | --- | --- | --- |
| timestamp(시각) | 읽기 쉽고 freshness(신선도) 표시에 유용 | 동일 시각 변경과 순서 역전을 식별하지 못함 | `decision_as_of` provenance(출처) |
| content hash(내용 해시) | 실제 근거·prompt·model 변화를 감지 | 변경 원인을 사람이 바로 알기 어려움 | `summary_key` materialization identity(구체화 식별자) |
| version set(버전 집합) | source/context의 불변 binding(결속) 표현 | 모든 upstream(상류) writer가 버전을 유지해야 함 | context version validation(문맥 버전 검증) |
| event sequence(이벤트 순번) | out-of-order event(순서 역전 이벤트) 검출에 유용 | 전체 공급자 순번이 필요 | 후속 multi-worker(다중 워커) 계약 후보 |

현재 최소 slice는 timestamp 단독을 채택하지 않는다. `summary_key`와 scope/context binding을 exact identity로 사용하고, `decision_as_of`는 표시와 provenance로만 사용한다.

## Current-state contract(현재 상태 계약)

| 상태 | `reuse_eligibility` | `current_ready` | `historical_available` | 소비 규칙 |
| --- | --- | --- | --- | --- |
| exact validated(정확 검증됨) | `EXACT_VALIDATED` | true | false | 요청한 snapshot과 검증된 요약 |
| disclosed history(명시된 과거) | `LATEST_STORED` | false | true | 이전 업무 시점임을 UI에 표시 |
| pending/ineligible(대기/부적격) | `INELIGIBLE` | false | false | 새 current 요약은 없음 |
| fallback(대체 요약) | `INELIGIBLE` | false | false | deterministic fallback은 별도 `fallback`/reason으로 표현하며 validated current로 승격하지 않음 |

exact-only는 stale prose(오래된 문장) 오해를 가장 강하게 막지만 availability(가용성)를 낮춘다. disclosed historical fallback은 가용성을 보존하지만 UX disclosure(UX 명시)와 정책 비용이 있다. 이 선택은 사람 소유이다.

## State transitions(상태 전이), invalidation(무효화), and coexistence(공존)

1. request(요청)는 scope와 snapshot identity를 확정하고 deterministic selector가 evidence set을 고정한다.
2. provider 호출 전후 validator가 key, scope, evidence binding을 검증한다.
3. generation 중 snapshot change(스냅샷 변경)는 저장을 차단하고 결과를 폐기한다. 재계산은 선택된 정책과 bounded retry(제한된 재시도)에만 따른다.
4. exact cache miss는 product policy에 따라 pending 또는 disclosed historical을 반환한다. GET은 generation을 시작하지 않는다.
5. duplicate generation(중복 생성)은 same-key lock/active-run 계약으로 합친다. multi-worker와 deploy 중 old/new key coexistence(구·신 키 공존)는 현재 단일 프로세스 증거 밖이며 schema/key compatibility와 rollback plan이 필요하다.
6. cache invalidation은 identity-input 변경으로 일어나며, fallback 또는 historical record가 current-ready로 재해석되어서는 안 된다.

## Alternatives and discriminating experiment(대안 및 판별 실험)

- **Baseline(기준선):** summary 존재 여부만으로 exact readiness를 파생한다.
- **Challenger(도전자):** `ready` materialization이고 fallback이 아닌 경우만 `EXACT_VALIDATED`로 정규화한다.
- **Invariant(불변식):** fallback은 `current_ready=false`; exact validated는 true/false; historical은 false/true; pending은 false/false; scope/key/mismatch block과 GET-no-generation(조회 시 생성 없음)을 유지한다.
- **Fixture/workload(픽스처/작업부하):** deterministic invalid provider candidate(결정론적 잘못된 제공자 후보)와 기존 exact/historical/pending synthetic fixture(합성 픽스처).
- **Metric(지표):** boolean pair(불리언 쌍), enum(열거값), materialization status, provider-call count(제공자 호출 수), stale save count(오래된 저장 수). 이번 예산에서 실제로 실행하지 않은 지표는 `not measured(미측정)`으로 남긴다.
- **Adoption/rejection gate(채택/기각 게이트):** fallback focused regression이 기존 검사에서 validated current를 보고하면 challenger 채택을 기각한다. 통과는 synthetic contract evidence일 뿐 actual provider readiness(실제 제공자 준비), performance(성능), capacity(용량), multi-worker 보증이 아니다.

## Test plan(테스트 계획)

| 종류 | 검증 대상 |
| --- | --- |
| Unit(단위) | selector ordering/dedupe/missing-required/token budget, key/validator, fallback readiness 정규화 |
| Integration(통합) | service→repository→router의 exact/historical/pending/fallback trace |
| Regression(회귀) | 2026-09-23 mutation block, GET-no-generation, latest stored provenance |
| Fault Injection(결함 주입) | snapshot mismatch, provider timeout/invalid output, duplicate/out-of-order event, cache-key mismatch |
| Contract(계약) | API boolean pair, ViewModel disclosure, output-viewmodel consistency |

TDD(테스트 주도 개발)는 Red(실패) → Green(통과) → Refactor(정리)로 한 번의 focused change에 적용한다. Test Scope Review(테스트 범위 검토)는 변경한 readiness derivation과 그 소비 경계만 포함하는지, 72-run 안정성 평가를 재실행 또는 생산 규모 주장으로 바꾸지 않는지를 확인한다.

## Operations, deployment, and CI(운영, 배포, CI)

- `/health`와 actual provider readiness(실제 제공자 준비)를 분리한다. provider smoke(제공자 스모크)는 명시 승인과 격리 환경에서만 한다.
- schema/cache key compatibility(스키마/캐시 키 호환성), old/new version coexistence(구/신 버전 공존), multi-worker duplicate contract(다중 워커 중복 계약), migration(마이그레이션), rollback(롤백)을 release gate(배포 게이트)로 기록한다.
- CI는 focused contract tests, type check(타입 검사), diff check(차이 검사)를 우선하고, 실제 provider·production·72-run 결과와 합치지 않는다.

## Existing evaluation boundary(기존 평가 경계)

72-run stability evaluation(72회 안정성 평가)은 8 Gold fixture(골드 픽스처) × 3 arm(경로) × 3 repeat(반복)의 historical stability harness(과거 안정성 하니스)이며, 이 slice의 snapshot correctness(스냅샷 정확성) 또는 current readiness(현재 준비) 증거가 아니다. 새 focused experiment는 현재 코드의 contract normalization만 판별한다. 두 결과의 분모, revision, provider, fixture, 목적을 합산하거나 서로의 production claim(운영 주장)으로 사용하지 않는다.

## Decision Gate(결정 게이트)

- **Evidence(근거):** `docs/evidence/2026-09-25-ai-evidence-consistency-snapshot-reliability.md`.
- **Human decision(사람 결정):** pending(대기). exact-only, disclosed historical fallback, fallback UX/availability 범위 중 하나의 제품 정책 선택이 필요하다.
- **Changed belief(변경된 믿음):** unrecorded(미기록).
- **STOP:** 최소 fallback normalization과 focused verification 이후 멈춘다. 다음 최소 작업은 사람이 선택한 소비 정책을 기준으로 exact-only 또는 disclosed-history UI/API policy를 하나만 검증하는 것이다.

# Runtime / Simulation 기반 Closed-loop 대범위 보강 계획

Status: draft
Date: 2026-08-26
Base reference: PR #128 `feat(mvp): 역할별 overview와 asset detail 작업 흐름 정리`
Related:

- `docs/mvp/runtime-ownership-integration.md`
- `docs/closed-loop-product-consumption-contract.md`
- `docs/closed-loop-runtime-overlay-contract.md`
- `docs/mvp/asset-detail-overview-ui-decision-log.md`
- `docs/plans/2026-08-24-001-feat-asset-detail-ui-agent-flow-plan.md`

## 1. 목적

PR #128은 역할별 Overview, Asset Detail Side Task View, 작업 상태 큐, Report 출력 진입을
정리해 사용자가 "상황 -> 설비 -> 작업"으로 이동할 수 있는 read surface를 만든다.
이 계획은 그 read surface를 실제 runtime/simulation/closed-loop 데이터와 연결하기 위한
후속 구현 단위를 정의한다.

목표는 새 Generator Runtime 경로를 도입하는 것이 아니라, live sensor와 simulation overlay가
서로 다른 source에서 오더라도 Backend Diagnosis 이후에는 하나의 Product Result/Evidence
파이프라인으로 수렴시키는 것이다.

```text
Live Sensor Observation
또는 Simulation / Maintenance Replay Overlay Observation
  -> Backend Diagnosis consume
  -> history_requirement / readiness 판단
  -> runtime inference
  -> Product Result Artifact append
  -> Evidence / API / ViewModel
  -> PR #128 UI read surface
  -> Closed-loop 작업요청 / 승인 / 정비 / 재관측
```

## 2. PR 범위 결정

이 작업은 작은 API 보강 PR이 아니라, PR #128 read surface를 실제 runtime product flow로
동작시키는 대범위 Integration PR로 잡는다.

큰 PR의 acceptance boundary는 다음이다.

```text
sensor tick 자동 감지
  -> observation consume
  -> 새 inference 실행
  -> Product Result append
  -> API/ViewModel 갱신
  -> PR #128 UI live update
  -> Closed-loop 작업요청/정비/replay 연결
```

이 범위를 하나의 PR 또는 같은 PR stack으로 묶어야 하는 이유는, 각 단계가 따로 merge되면
다음 간극이 다시 남기 때문이다.

- Backend는 Product Result를 만들지만 UI가 latest/readiness를 보지 못함
- UI는 처리 탭을 보여주지만 Closed-loop persisted state가 없음
- 정비 완료는 기록되지만 replay/post-maintenance Product Result가 없음
- Generator는 score를 만들지만 Backend 승격 gate가 없어 Product Result가 아님
- runtime status가 없어 사용자는 "대기 중", "이력 부족", "실패", "예측 완료"를 구분하지 못함

따라서 이 계획의 구현 단위는 다음처럼 정의한다.

- 1차 통합 PR: Backend Runtime Execution -> Product Result append -> API/ViewModel -> PR #128 UI live update
- 같은 PR 또는 즉시 후속 stack: Closed-loop mutation -> Maintenance replay -> post-maintenance Product Result
- 병렬 shadow PR: Generator Runtime score batch -> Backend Inbox shadow -> parity 비교
- 별도 후순위 PR: Generator canonical 전환과 Backend direct inference 제거

즉, Generator owner가 runtime 전환을 승인하더라도 PR #128과 Closed-loop가 직접 소비하는 계약은
계속 Backend Product Result/Evidence다. Generator 결과는 Product Result 승격 전까지 shadow
input 또는 provenance로만 다룬다.

## 3. 현재 기준

### 3.1 PR #128이 제공한 기반

PR #128의 범위는 UI/UX 책임 정리와 read-only 업무 표면이다.

- `AssetDetailViewModel`을 canonical consumer contract로 삼는다.
- classic/workflow Overview variant를 병행하되 같은 MVP adapter 계약을 소비한다.
- 현장 관리자와 생산 관리자의 첫 질문을 분리한다.
- Side Task View를 `상태`와 `처리`로 나눈다.
- 작업 상태 큐와 처리 탭은 closed-loop state를 받을 수 있는 surface로 준비한다.
- Frontend는 WorkOrder ID, Recommendation state, `available_actions`, risk, criticality,
  `review_priority`를 합성하지 않는다.
- 실제 mutation, Closed-loop state machine, Runtime Overlay 이후 재예측, agent workflow는
  후속 작업으로 남긴다.

따라서 PR #128 이후의 핵심 과제는 화면 추가가 아니라, PR #128이 기다리는 데이터를
Backend에서 안정적으로 만들어 내려주는 것이다.

### 3.2 기존 runtime 계약

현재 MVP의 안전한 계약은 다음이다.

```text
gen_data
  -> canonical / live / simulation observation 생성
  -> runtime_overlay.observations.available 발행

systems/generator
  -> training
  -> feature_schema / label_schema / history_requirement
  -> Model Artifact / metrics / threshold metadata 발행
  -> Golden Vector / feature parity evidence 제공

systems/backend/app/diagnosis
  -> observation/history 소비
  -> history_requirement/readiness 판단
  -> Model Artifact 로드
  -> runtime feature 실행
  -> model inference
  -> Product Result Artifact / Evidence 생성

Closed-loop
  -> Product Result / Evidence / RecommendationDecision 소비
  -> Inspection / WorkOrder / MaintenanceAction 상태 전이
```

`Prediction score` 또는 Generator의 raw batch는 Product Result가 아니다. 작업요청 수집과
Closed-loop trigger는 Backend가 Product Result/Evidence 또는 RecommendationDecision으로
승격한 뒤에만 발생한다.

### 3.3 #127과의 관계

PR #127의 Generator Runtime Pipeline은 snapshot 검증, checksum/source identity, checkpoint,
outbox, feature parity 관점에서 재사용 가치가 있다. 그러나 현재 MVP의 canonical runtime path로
채택하려면 Backend consumer, Product Result 승격, 기존 Backend inference 전환, lineage/E2E까지
같은 migration unit으로 닫아야 한다.

이 계획은 PR #127의 runtime ownership 이전을 전제로 하지 않는다. 필요한 아이디어만 다음처럼
선별한다.

| 구분 | 처리 |
|---|---|
| Model Artifact snapshot 검증 | Backend Diagnosis runtime 로드 전 검증으로 도입 검토 |
| Feature parity / Golden Vector | Generator가 발행하고 Backend가 CI에서 비교 |
| source checksum / source identity | Backend consume cursor/idempotency에 반영 |
| checkpoint/outbox 패턴 | Backend ingestion/replay worker 설계 참고 |
| Generator Runtime Prediction worker | 현재 MVP canonical path로 채택하지 않음 |
| Generator -> Backend raw score delivery | Backend consumer가 없는 한 Product Result 입력으로 사용하지 않음 |

## 4. 핵심 원칙

1. Observation source는 여러 개일 수 있지만 Product Result/Evidence producer는 하나로 유지한다.
2. Frontend는 raw observation, raw score, Generator batch를 직접 해석하지 않는다.
3. Closed-loop는 Product Result/Evidence/RecommendationDecision만 소비한다.
4. 정비 완료는 정상 판정이 아니다. 정비 후 첫 inference-ready Observation에서 새 Product Result가
   생성된 뒤에만 정상/주의/경고/위험을 판단한다.
5. `warming_up`, `history_insufficient`, `score=null`, partial model failure는 작업요청 생성 금지
   상태로 fail-closed 처리한다.
6. 정비 전 Product Result/Evidence는 immutable하게 보존하고, 정비 후 결과는 append-only로 새로 만든다.
7. `source_kind`와 lineage를 통해 live/simulation/maintenance replay를 구분하되 UI/API 소비 계약은
   같은 shape를 유지한다.
8. Generator는 feature/model 계약의 owner이고, Backend Diagnosis는 runtime product truth의 owner다.
9. 큰 PR 내부에서 트랙을 나누더라도 Product Result/Evidence를 우회하는 임시 UI/Closed-loop 경로는 만들지 않는다.
10. Backend direct inference 제거는 shadow parity와 rollback 조건이 확인된 뒤 별도 PR에서만 수행한다.

## 5. 대상 사용자 흐름

### 5.1 Live 흐름

```text
live sensor tick
  -> gen_data live observation 저장
  -> observation available marker
  -> Backend consume cursor가 새 tick 감지
  -> same-asset history window 구성
  -> readiness 판단
  -> Product Result/Evidence append
  -> latest/timeline/detail API 갱신
  -> PR #128 Overview/Side Task View에서 새 상태 표시
  -> 필요 시 Inspection 후보 또는 작업요청 후보 노출
```

### 5.2 Simulation / maintenance replay 흐름

```text
MaintenanceAction complete
  -> MaintenanceEvent append
  -> maintenance replay 요청
  -> gen_data가 대상 설비 overlay branch 생성
  -> branch-local simulation clock fast-forward
  -> runtime_overlay.observations.available 발행
  -> Backend consume cursor가 overlay observation 반영
  -> history_requirement 충족 전까지 warming_up/history_insufficient
  -> 첫 inference-ready observation에서 새 Product Result/Evidence append
  -> 정비 전/후 Product Result lineage 연결
  -> PR #128 UI가 전후 비교와 재관측 상태 표시
```

## 6. 데이터 계약 보강

### 6.1 Observation source envelope

Backend consumer가 live와 simulation을 같은 파이프라인에서 처리하려면 observation handoff에
아래 envelope가 필요하다.

```json
{
  "source_kind": "live_sensor | simulation_overlay | maintenance_replay",
  "asset_id": "CNC-S04-L02-03",
  "observed_at": "2026-08-26T06:00:00Z",
  "source_ref": {
    "uri": "runtime_overlay/...",
    "sha256": "..."
  },
  "dataset_version_id": "...",
  "lineage": {
    "simulation_session_id": null,
    "overlay_branch_id": null,
    "history_segment_id": null,
    "maintenance_event_id": null,
    "maintenance_action_id": null,
    "state_version": null
  }
}
```

규칙:

- `source_kind`는 Product Result의 provenance에 보존한다.
- live source는 maintenance lineage가 `null`일 수 있다.
- maintenance replay source는 `maintenance_event_id`, `overlay_branch_id`,
  `history_segment_id`, `state_version`을 보존해야 한다.
- `gen_data`는 availability만 발행하고 readiness를 판정하지 않는다.
- Backend는 같은 `(source_ref.sha256, asset_id, observed_at, source_kind)`를 중복 처리하지 않는다.

### 6.2 Product Result Artifact lineage

정비 후 Product Result에는 아래 필드를 보존해야 한다.

```text
source_kind
source_observation_ref.uri
source_observation_ref.sha256
previous_product_result_id
maintenance_event_id
maintenance_action_id
overlay_branch_id
history_segment_id
simulation_session_id
state_version
model_artifact_uri
model_artifact_sha256
feature_schema_version
history_requirement_version
policy_version
```

규칙:

- `previous_product_result_id`는 정비 전 비교 기준을 가리키며 기존 Artifact를 수정하지 않는다.
- `history_insufficient` 상태에서는 Product Result를 정상으로 생성하지 않는다. 필요하면 별도 runtime
  status/readiness record로 남긴다.
- Product Result가 생성된 경우에만 Evidence projection, Report, Closed-loop가 소비할 수 있다.

### 6.3 AssetDetailViewModel 연결

PR #128 UI는 다음 ViewModel 필드를 기대한다.

- `risk`
- `features[].current`
- `features[].history.points`
- `asset.criticality`
- `operation_context`
- `maintenance_context`
- `review_priority`
- `closed_loop`
- `available_actions`
- `evidence.gaps`
- `data_status`

후속 Backend 작업은 이 필드를 frontend가 합성하지 않도록 Backend adapter에서 채워야 한다.
값이 없으면 `null`, empty array, gap, unavailable reason으로 내려야 하며 `0`, `normal`, `low`,
`false`로 보정하지 않는다.

## 7. Backend 작업 계획

아래 항목은 각각 독립 제품 기능 PR이라는 뜻이 아니라, 대범위 Integration PR 안에서
검증 가능한 backend 하위 track 또는 커밋 묶음으로 본다. 최소 완료선은 B1~B4가 서로 이어져
runtime Product Result가 UI까지 도달하는 것이다.

### Track B1. Runtime source consume cursor/idempotency

목표:

- live/simulation observation availability를 Backend가 중복 없이 소비한다.
- 처리 여부, checksum, cursor, failure reason을 DB 또는 durable store에 남긴다.

범위:

- `runtime_overlay.observations.available` reader 정리
- source envelope parser/validator
- consume cursor 저장
- duplicate skip
- checksum mismatch fail-closed
- `source_kind` 분기

완료 조건:

- 같은 marker를 두 번 소비해도 Product Result가 중복 생성되지 않는다.
- checksum이 바뀐 동일 URI는 오류로 남고 조용히 덮어쓰지 않는다.
- live와 maintenance replay source가 같은 consumer entrypoint를 통과한다.

검증:

- unit: cursor duplicate/mismatch cases
- integration: temp overlay available file -> consumer -> stored cursor
- architecture check: Backend consumer가 Generator Python 구현을 import하지 않음

### Track B2. Diagnosis readiness/runtime inference 통합

목표:

- Backend Diagnosis가 source observation과 same-asset history를 구성하고, Model Artifact의
  `history_requirement`에 따라 추론 가능 여부를 판단한다.

범위:

- same-asset history window query
- `observed_at < current_observed_at` invariant
- Model Artifact manifest/checksum/compatibility validation
- feature executor compatibility check
- `warming_up` / `history_insufficient` status record
- `predictor.predict()` execution

완료 조건:

- current observation이 history baseline에 중복되지 않는다.
- required history가 부족하면 Product Result를 생성하지 않는다.
- unsupported transform 또는 feature mismatch는 fail-fast/fail-closed로 남긴다.

검증:

- unit: history window excludes current row
- unit: insufficient history does not create Product Result
- contract: Generator Golden Vector와 Backend runtime feature 결과 비교
- regression: existing Product Result/Evidence tests pass

### Track B3. Product Result/Evidence append 및 lineage

목표:

- live/simulation 모두 같은 Product Result Artifact/Evidence producer 경로를 사용한다.
- 정비 전/후 lineage가 append-only로 보존된다.

범위:

- `build_product_result_artifact()` input 확장
- Product Result provenance에 source/maintenance lineage 추가
- `pm_result_artifacts` append path 정리
- `prediction_results.payload_json`와 index/read-model semantics 분리 유지
- Evidence projection consumer compatibility 확인

완료 조건:

- maintenance replay 이후 새 Product Result가 별도 ID로 생성된다.
- 정비 전 Product Result는 수정되지 않는다.
- Evidence projection은 raw observation이나 raw score를 직접 읽지 않는다.

검증:

- PostgreSQL-backed replay: pre-maintenance result + post-maintenance result 모두 존재
- contract: product-result-artifact schema validation
- projection: Event Evidence / Report mapper compatibility

### Track B4. Product API/ViewModel 보강

목표:

- PR #128 UI가 필요한 runtime/closed-loop/readiness 데이터를 Backend API로 받을 수 있게 한다.

범위:

- latest result query
- asset timeline query
- asset detail ViewModel composer 보강
- maintenance lineage query
- runtime status/readiness field
- `closed_loop` summary envelope 연결
- `available_actions` read model 연결

완료 조건:

- Overview, Objects, Operations, Report가 같은 Product Result snapshot을 소비한다.
- Frontend가 `review_priority`, WorkOrder ID, action state를 합성하지 않아도 표시된다.
- missing runtime data는 gap/unavailable로 표시된다.

검증:

- API contract tests
- `tests/test_asset_detail_view_model_composer.py`
- `tests/test_asset_detail_view_model_contract.py`
- `tests/test_mvp.py`

## 8. Frontend 작업 계획

Frontend 작업은 PR #128의 화면 구조를 바꾸는 작업이 아니라, PR #128이 이미 만든 read surface를
Backend Product Result/ViewModel에 연결하는 작업이다. 이 부분은 Backend B1~B4와 같은 큰 PR
acceptance 안에서 같이 검증되어야 한다.

### Track F1. PR #128 read surface와 runtime API 연결

목표:

- PR #128의 workflow Overview와 Side Task View가 fixture/local fallback이 아니라 Backend API의
  canonical ViewModel을 우선 소비한다.

범위:

- `mvpAdapters`의 raw fallback 축소
- `closed_loop` / `available_actions` rendering source 고정
- runtime status badge
- `source_kind` 표시
- `history_insufficient` / `warming_up` / evidence gap 표시
- latest/timeline/detail refetch 경로

완료 조건:

- WorkOrder ID, Recommendation state, permissions를 frontend에서 만들지 않는다.
- Product Result가 새로 생기면 Side Task View와 Overview가 refetch로 갱신된다.
- raw score/batch를 표시하지 않는다.

검증:

- `npm test -- mvpAdapters`
- `npm test -- --run src/features/mvp/context/MvpSelectionContext.test.ts src/features/mvp/api/mvpAdapters.test.ts`
- `npm run build`
- Playwright: field operator, process manager, report entry, runtime status

### Track F2. Replay/live refresh UX

목표:

- 실시간 push 인프라가 없어도 MVP에서 새 Product Result 생성을 사용자가 볼 수 있게 한다.

방향:

- replay SSE는 "session progress changed" signal로 사용한다.
- live는 짧은 polling 또는 manual refresh로 시작한다.
- event를 받으면 raw payload를 화면에 직접 반영하지 않고 latest/timeline/evidence/detail API를 refetch한다.

완료 조건:

- replay event 수신 후 새 Product Result가 있으면 정비 후 비교가 갱신된다.
- live polling은 Product Result API만 조회한다.
- 네트워크 오류는 이전 snapshot과 unavailable banner로 처리한다.

검증:

- Playwright route mock: replay SSE -> latest refetch
- Playwright route mock: runtime unavailable -> gap/hold 표시

## 9. Closed-loop 작업 계획

Closed-loop는 독립 상태 머신처럼 보이지만, 이 계획에서는 Product Result/Evidence 이후의
작업요청/정비/replay를 닫는 runtime loop의 후반부다. 따라서 C1~C2는 Backend Product Result
append와 ViewModel 계약이 확인된 뒤 같은 stack에서 병렬 진행한다.

### Track C1. 작업요청 수집/상태 전이 API 연결

목표:

- PR #128의 처리 탭이 실제 작업요청, 점검, 추천, 승인, 정비 API로 연결될 수 있게 한다.

범위:

- Inspection WorkOrder request/approve/start/complete
- Recommendation create/decision
- Maintenance WorkOrder approve
- MaintenanceAction start/complete
- idempotency key
- permission/role check
- Activity append
- API response -> `closed_loop` summary 갱신

완료 조건:

- Frontend는 mutation 전후에 Persistence가 확정한 ID만 사용한다.
- 동일 idempotency key 재시도는 같은 결과를 반환한다.
- 권한 없는 role은 disabled reason 또는 403으로 일관되게 처리된다.

검증:

- Backend router/service tests
- frontend mutation flow tests
- E2E: request inspection -> approve -> start -> complete

### Track C2. Maintenance complete -> replay -> post-maintenance prediction

목표:

- 정비 완료 이후 Runtime Overlay 생성과 Backend 재예측을 연결한다.

범위:

- `MaintenanceEvent` 완료 후 replay request
- overlay branch lineage 저장
- Backend consume trigger
- readiness status
- 첫 inference-ready Product Result append
- previous/current result comparison API

완료 조건:

- 정비 완료 직후 화면은 `warming_up` 또는 `history_insufficient`를 표시한다.
- 충분한 overlay observation 이후 새 Product Result/Evidence가 생성된다.
- 정비 전/후 비교가 같은 asset, same branch lineage로 연결된다.

검증:

- PostgreSQL integration E2E
- Playwright: maintenance complete -> waiting -> post result displayed
- lineage API: maintenance_event_id -> overlay_branch_id -> post_product_result_id

## 10. Generator 작업 계획

Generator는 runtime product truth를 만들지 않고, Backend runtime이 신뢰할 수 있는
model/feature 계약을 강화한다. Generator Runtime 전환을 병렬로 준비하더라도, canonical 전환
전에는 shadow 결과만 만들고 Backend Product Result/Evidence 승격 gate를 우회하지 않는다.

### Track G1. Feature parity / Golden Vector

목표:

- 학습 시 feature 계산과 Backend runtime feature 계산이 같은 입력에서 같은 값을 내는지 검증한다.

범위:

- Generator가 Golden Vector input/output 발행
- feature_schema transform allowlist 명시
- history_requirement version 명시
- Backend CI에서 Golden Vector comparison
- unsupported transform fail-fast rule

완료 조건:

- Backend가 지원하지 않는 feature transform을 가진 Model Artifact는 runtime에서 거부된다.
- 같은 Golden Vector에서 feature order/type/value가 일치한다.

검증:

- `systems/verify_contract_vectors.py`
- backend feature parity test
- Model Artifact compatibility test

### Track G2. Model Artifact snapshot validation

목표:

- Backend Diagnosis가 runtime inference 전에 active Model Artifact snapshot의 파일/checksum/schema
  정합성을 확인한다.

범위:

- manifest required roles 검증
- `model`, `feature_schema`, `label_schema`, `history_requirement`, `metrics` checksum 검증
- model version / dataset version compatibility
- threshold metadata는 Product Result policy 입력으로만 사용

완료 조건:

- 깨진 Model Artifact로 Product Result를 생성하지 않는다.
- Artifact mismatch는 evidence gap이 아니라 runtime unavailable/fail-closed로 남는다.

### Track G3. Runtime score batch shadow handoff

목표:

- Generator Runtime owner가 승인된 경우를 대비해, raw score batch를 Backend Inbox에 shadow로
  전달하고 parity evidence를 만든다.

범위:

- runtime score batch envelope
- outbox retry/dead-letter
- `event_id + payload_sha256` 멱등성
- source/model/feature lineage 필수화
- Backend runtime result와 same-observation parity 비교

완료 조건:

- Generator score batch가 Product Result로 즉시 승격되지 않는다.
- Backend는 score batch를 shadow 저장하고 Product API/UI/Closed-loop에 노출하지 않는다.
- mismatch는 Product Result overwrite가 아니라 parity failure로 남는다.

## 11. API 설계 방향

기존 public API를 깨지 않고 additive하게 확장한다.

후보:

```text
GET /api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance/results/latest
GET /api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance/timeline
GET /api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance/observations
GET /api/projects/{project_id}/workspaces/{workspace_id}/maintenance/events/{event_id}/lineage
POST /api/projects/{project_id}/workspaces/{workspace_id}/maintenance/maintenance-events/{id}/replay
```

테스트/운영 보조 후보:

```text
POST /internal/runtime-overlay/consume-once
GET /internal/runtime-overlay/consume-status
```

주의:

- `/internal/runtime-overlay/consume-once`는 public product action이 아니다.
- Frontend는 internal endpoint를 직접 호출하지 않는다.
- Frontend refresh는 public Product API를 기준으로 한다.

## 12. E2E 시나리오

### Scenario A. Live observation to action candidate

```text
Given live observation available marker가 생성됨
When Backend consumer가 새 observation을 처리함
And history_requirement가 충족됨
Then 새 Product Result/Evidence가 append됨
And Overview에 위험 설비가 표시됨
And Side Task View 처리 탭에 작업요청 후보가 표시됨
And WorkOrder ID는 실제 mutation 전까지 표시되지 않음
```

### Scenario B. Data quality hold

```text
Given sensor quality가 invalid 또는 missing임
When Backend Diagnosis가 observation을 처리함
Then Product Result는 정상으로 보정되지 않음
And ViewModel은 data_quality_hold/evidence gap을 표시함
And Closed-loop 작업요청은 자동 생성되지 않음
```

### Scenario C. Maintenance replay

```text
Given critical Product Result에서 점검/정비가 완료됨
When maintenance replay가 요청됨
Then overlay branch가 생성되고 lineage가 저장됨
And Backend는 warming_up/history_insufficient를 먼저 표시함
When 충분한 overlay observation이 쌓임
Then 정비 후 새 Product Result/Evidence가 append됨
And UI는 정비 전/후 결과를 비교함
```

### Scenario D. Permission and idempotency

```text
Given process_engineer가 점검 결과를 기록함
When process_manager가 recommendation decision을 승인함
Then maintenance WorkOrder가 requested 상태로 생성됨
And 같은 Idempotency-Key 재시도는 같은 WorkOrder를 반환함
And maintenance_technician만 작업 시작/완료를 수행할 수 있음
```

## 13. Acceptance Criteria

전체 계획의 완료 기준:

- live와 simulation source가 같은 Backend Diagnosis Product Result path로 수렴한다.
- Product Result/Evidence는 append-only이며 정비 전/후 lineage를 복원할 수 있다.
- PR #128 UI가 raw score, raw JSONL, fixture-only value를 제품 truth로 해석하지 않는다.
- Closed-loop는 Product Result/Evidence/RecommendationDecision만 trigger로 사용한다.
- `history_insufficient`, `warming_up`, data quality hold는 정상 상태로 보정되지 않는다.
- Backend API와 Frontend가 같은 `AssetDetailViewModel` 계약을 소비한다.
- E2E에서 "센서/시뮬레이션 observation -> 재예측 -> Evidence -> 작업요청/정비 -> 정비 후 재예측"
  흐름을 재현할 수 있다.
- Generator Runtime shadow가 켜져도 canonical Product Result/Evidence 소비자는 영향을 받지 않는다.
- Backend direct inference 제거는 이 PR의 완료 조건이 아니다.

## 14. 권장 통합 PR 구성과 병렬 순서

권장 PR 범위는 작게 쪼개진 기능 PR 나열이 아니라, 다음 3개 stack이다.

1. Integration PR 1: Runtime Product Loop
   - Runtime source envelope/cursor/idempotency
   - Backend Diagnosis readiness/history/runtime inference
   - Product Result/Evidence lineage append
   - AssetDetailViewModel/API runtime status
   - PR #128 UI live update

2. Integration PR 2: Closed-loop Maintenance Loop
   - Product Result/Evidence 기반 작업요청 수집
   - RecommendationDecision/WorkOrder/MaintenanceAction mutation
   - persisted ID/state 기반 ViewModel 연결
   - Maintenance complete -> replay
   - post-maintenance Product Result 비교

3. Shadow PR: Generator Runtime Migration Evidence
   - Golden Vector / feature parity
   - Model Artifact snapshot validation
   - Runtime score batch outbox
   - Backend Inbox shadow 저장
   - parity/mismatch evidence

Integration PR 1과 2는 겹치는 계약을 `AssetDetailViewModel`, Product Result/Evidence,
Maintenance API로 고정하면 병렬 진행 가능하다. Shadow PR은 Product Result를 직접 만들지
않는다는 조건에서 병렬 진행 가능하다.

이 순서는 PR #128이 만든 read surface를 깨지 않고, 먼저 Backend product truth를 안정화한 뒤
Frontend와 Closed-loop mutation을 붙이는 흐름이다.

## 15. 보류 및 재검토 조건

Generator Runtime 또는 별도 Model Serving은 아래 조건이 생기면 다시 검토한다.

- Backend inference 부하를 독립적으로 scale해야 한다.
- 다중 모델 serving과 artifact 교체 빈도가 높아진다.
- ML framework/runtime dependency를 Backend에서 분리해야 한다.
- GPU 또는 별도 inference 자원이 필요하다.
- 여러 서비스가 같은 model runtime을 소비해야 한다.

그 전까지 MVP canonical path는 다음으로 유지한다.

```text
Observation available
  -> Backend Diagnosis
  -> Product Result/Evidence
  -> PR #128 UI
  -> Closed-loop 작업 흐름
```

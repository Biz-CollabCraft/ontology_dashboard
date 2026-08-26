# PR #128 기반 Runtime / Closed-loop 대범위 병렬 작업 제안

Status: draft
Date: 2026-08-26
Base: PR #128 `feat(mvp): 역할별 overview와 asset detail 작업 흐름 정리`
Reference: Issue #99 `Maintenance Loop Prototype 검증 근거 및 이식 전 계약 Gate`

## 1. 제안 목적

PR #128은 화면을 새로 확장하는 작업이 아니라, 사용자 업무 흐름을 다음처럼 정리한 PR이다.

```text
상황 확인
  -> 설비 선택
  -> 상태/근거 확인
  -> 처리 탭에서 작업 흐름 진입
  -> Report 출력
```

따라서 후속 작업은 화면을 더 만드는 것이 아니라, PR #128이 기다리는 Backend runtime result,
closed-loop state, available action, lineage를 실제 데이터로 채우는 것이다.

이번 제안은 작은 read-model 보강이 아니라 다음 end-to-end 범위를 하나의 큰 Integration
PR/stack acceptance 단위로 잡는다.

```text
sensor tick 자동 감지
  -> observation consume
  -> 새 inference 실행
  -> Product Result append
  -> API/read model 갱신
  -> PR #128 UI live update
  -> Closed-loop 작업요청/정비/replay 연결
```

Generator Runtime 전환은 이 흐름과 병렬로 준비할 수 있지만, 첫 canonical path는 Backend
Runtime Execution E2E로 닫는다.

## 2. 고정 원칙

1. PR #128 UI는 raw observation, raw score, Generator batch를 직접 소비하지 않는다.
2. Frontend는 `AssetDetailViewModel`, Product API, Maintenance API만 소비한다.
3. Closed-loop는 Product Result/Evidence/RecommendationDecision만 trigger로 사용한다.
4. Product Result Artifact는 append-only다. latest는 query 결과이지 저장 overwrite가 아니다.
5. Generator Runtime 전환이 승인되어도 Product Result/Evidence core 의미는 바꾸지 않는다.
6. Generator 산출물이 추가되면 core schema 재설계가 아니라 provenance/source trace로 연결한다.
7. Backend Diagnosis는 Product Result/Evidence 승격 gate를 맡는다.
8. Generator가 runtime owner라면 raw score producer contract를 끝까지 책임진다.
9. Backend direct inference 제거는 shadow parity와 rollback 가능 상태 확인 뒤 별도 마지막 PR로만 수행한다.

## 3. 큰 범위

포함:

- live/simulation observation available marker 감지
- Backend consume cursor/checksum/idempotency
- observation/history window 구성
- Backend runtime inference execution
- Product Result Artifact / Evidence append
- runtime status/readiness API
- `AssetDetailViewModel`의 `current_result_summary` / `runtime_status`
- PR #128 UI polling/refetch 또는 replay signal 기반 live update
- Closed-loop 작업요청/승인/정비 mutation
- Maintenance replay -> post-maintenance Product Result
- Generator Runtime shadow 수신과 parity 비교

제외:

- Product Result/Evidence core 의미 변경
- Frontend의 raw score 직접 소비
- Closed-loop의 raw Generator batch 직접 소비
- Generator canonical 전환 즉시 적용
- Backend direct inference 선삭제

## 4. PR #128이 요구하는 후속 입력

PR #128의 Overview, Objects, Operations, Side Task View가 안정적으로 동작하려면 Backend가
다음 값을 제공해야 한다.

```text
risk
features.current
features.history.points
asset.criticality
operation_context
maintenance_context
review_priority
closed_loop summary
available_actions
data_status
evidence.gaps
current_result_summary
runtime_status
```

Frontend는 위 값을 계산하지 않는다. 값이 없으면 `null`, empty array, gap, unavailable reason으로
표시한다.

## 5. 병렬 Track

### Track A. Backend Runtime Execution E2E

담당: Backend Diagnosis / Runtime owner

이 Track이 critical path다. Generator Runtime 전환 여부와 무관하게, PR #128을 실제 제품 흐름으로
살리려면 Backend가 runtime execution을 먼저 닫아야 한다.

책임:

- sensor/live output 또는 simulation overlay available marker 감지
- consume cursor/checksum/idempotency 저장
- same-asset observation/history window 구성
- `history_requirement` 기반 readiness 판단
- `predictor.predict()` 실행
- `build_product_result_artifact()` 호출
- Product Result Artifact / Evidence append-only 저장
- runtime status/readiness record 생성
- latest/timeline/detail read model 갱신
- `AssetDetailViewModel` composer에 `current_result_summary`와 `runtime_status` 제공

완료 기준:

- 새 tick 또는 overlay observation을 처리하면 새 Product Result가 append된다.
- 같은 tick을 재처리해도 Product Result가 중복 생성되지 않는다.
- Product Result가 생성되지 않는 상태는 `warming_up`, `history_insufficient`, `failed_*`로 드러난다.
- latest는 query로만 선택되고 기존 Result는 overwrite되지 않는다.

금지:

- history 부족 상태를 정상 Product Result로 보정
- current observation을 history baseline에 중복 포함
- asset 기준 overwrite
- Generator shadow score를 곧바로 Product Result로 승격

### Track B. Generator Runtime Producer / Migration Shadow

담당: Generator owner

이 Track은 Generator Runtime 전환이 승인된 경우에만 canonical path 후보가 된다. 승인 전에는
shadow producer 또는 future Model Serving 검토용 foundation으로 둔다.

책임:

- Runtime Observation enqueue
- history/readiness 판단
- runtime feature engineering
- Model Artifact 로드 및 snapshot/checksum 검증
- model inference
- raw score batch 생성
- Outbox retry/dead-letter
- Backend 응답 코드별 처리
- shadow parity 비교 evidence 제공

Backend로 넘겨야 하는 최소 contract:

```text
event_id
asset_id
observed_at
score
output_status
source_uri
source_checksum
model_id
model_version
model_artifact_sha256
feature_schema_version
history_requirement_version
```

Simulation / maintenance replay source이면 추가:

```text
source_kind
maintenance_event_id
maintenance_action_id
overlay_branch_id
history_segment_id
state_version
simulation_session_id
```

금지:

- Product Result Artifact 생성
- Evidence 생성
- severity/status/recommendation 결정
- WorkOrder 또는 MaintenanceAction 생성
- Frontend/Closed-loop가 직접 소비할 화면용 payload 생성

### Track C. Backend Diagnosis Generator Inbox / Product Result Gate

담당: Backend Diagnosis / Product Result owner

Track A는 기존 Backend runtime execution을 닫고, 이 Track은 Generator Runtime migration을 위한
Inbox/materialization 경계를 준비한다. Generator owner 전환이 승인된 경우에도 Backend Diagnosis는
Product Result/Evidence 승격 gate를 유지한다.

책임:

- Generator score batch 수신
- shadow Inbox 저장
- contract/scope/lineage 검증
- idempotency/conflict 처리
- Backend runtime result와 Generator score parity 비교
- canonical 전환 후 threshold/decision policy 적용
- canonical 전환 후 Product Result Artifact / Evidence materialization

구현 우선순위:

1. `/internal/prediction-results` 또는 동등 Inbox endpoint를 shadow 수신으로 구현한다.
2. `event_id + payload_sha256` 멱등성과 conflict를 구현한다.
3. 같은 Observation에 대해 Backend runtime result와 Generator score parity를 비교한다.
4. canonical 전환 전에는 shadow 결과를 Product API/UI/Closed-loop에 노출하지 않는다.
5. 전환 승인 후에만 Generator score를 Product Result materialization 입력으로 사용한다.

금지:

- Generator가 누락한 feature/history/source lineage를 Backend에서 추론해 보정
- raw score를 Product Result 없이 Frontend/Closed-loop에 노출
- asset 기준 overwrite로 기존 Product Result를 갱신
- Evidence를 UI/ViewModel consumer에서 재생성

### Track D. Closed-loop Domain / Maintenance API

담당: Closed-loop owner

Issue #99 기준으로 Inspection, Recommendation, Decision, WorkOrder, MaintenanceEvent의 기본
상태 전이와 이식 Gate는 상당 부분 마련되어 있다. PR #128 후속에서는 이 상태를 화면이 소비할 수
있는 read model과 mutation response로 연결하고, Maintenance replay trigger까지 end-to-end로 잇는다.

책임:

- Product Result/Evidence 기반 Inspection 후보 연결
- RecommendationDecision / WorkOrder / MaintenanceAction 상태 전이
- idempotency key 처리
- role/permission/scope 검증
- Activity append
- MaintenanceEvent 완료
- replay request 발행
- runtime status와 post-maintenance Product Result를 작업 상태에 연결
- `closed_loop` summary와 `available_actions` 제공

PR #128에 넘겨야 하는 최소 contract:

```text
closed_loop.event_status
closed_loop.work_orders[]
closed_loop.maintenance_actions[]
closed_loop.maintenance_events[]
closed_loop.activities[]
available_actions[]
disabled_reason
lineage references
```

금지:

- raw Generator score로 작업요청 생성
- Product Result/Evidence 없이 RecommendationDecision 생성
- 정비 완료를 정상 Product Result로 표시
- Frontend가 WorkOrder ID나 action state를 합성하게 만들기

### Track E. Frontend PR #128 Live Integration

담당: Frontend / Product API owner

PR #128 UI는 이미 read surface를 제공한다. 후속은 raw data 계산이 아니라 API 연결과 live refresh이다.

책임:

- Backend `AssetDetailViewModel` 우선 소비
- latest/timeline/evidence/detail refetch
- `current_result_summary`와 `runtime_status` 분리 표시
- `closed_loop` summary 표시
- `available_actions` 기반 버튼/disabled state 표시
- `history_insufficient`, `warming_up`, `data_quality_hold`, evidence gap 표시
- replay/live signal 수신 후 Product API refetch
- 새 Product Result 감지 후 Overview/Side Task View/Report entry 갱신

금지:

- raw JSONL, Generator batch, raw score 직접 해석
- probability threshold로 frontend status 재계산
- WorkOrder ID, Recommendation state, permission 합성
- missing runtime 값을 `0`, `normal`, `low`, `false`로 보정

## 6. 병렬 진행 방식

병렬 진행의 공통 경계는 Product Result/Evidence와 PR #128 ViewModel이다.
Generator migration을 병렬로 열 경우에는 `Prediction Result Batch`도 별도 freeze한다.

```text
Track A Backend Runtime Execution
  -> Product Result/Evidence append

Track B Generator
  -> score batch contract

Track C Backend Generator Inbox
  -> shadow/parity/materialization gate

Track D Closed-loop
  -> Product Result/Evidence 기반 작업 상태 전이

Track E Frontend
  -> PR #128 live read surface API 연결
```

초기 운영 정본은 Backend Runtime Execution으로 둔다.

```text
1. Backend Runtime Execution E2E로 sensor/overlay observation -> Product Result append -> UI update를 먼저 닫는다.
2. Closed-loop는 Product Result/Evidence 기반으로 작업요청/정비/replay를 병렬 연결한다.
3. Generator Runtime은 shadow로 수신해 score/lineage parity를 비교한다.
4. Generator owner 전환이 승인되고 E2E가 통과하면 canonical source flag를 전환한다.
5. rollback 가능 상태 확인 후 기존 Backend direct inference 제거를 별도 마지막 PR로 진행한다.
```

## 7. 큰 범위 구현 순서

### Step 1. Runtime tick consume / idempotency

- live sensor 또는 simulation overlay available marker를 Backend worker가 감지한다.
- 처리 cursor, source checksum, consume status를 저장한다.
- duplicate tick은 skip/reuse하고 checksum conflict는 fail-closed로 남긴다.

완료 기준:

- 같은 marker를 두 번 처리해도 Product Result가 중복 생성되지 않는다.
- 처리 실패 상태가 runtime status로 조회된다.

### Step 2. Observation -> Diagnosis execution

- 새 observation과 same-asset history window를 구성한다.
- `history_requirement`를 확인한다.
- 준비되면 inference를 실행한다.
- 부족하면 Product Result를 만들지 않고 `warming_up`/`history_insufficient`를 기록한다.

완료 기준:

- current observation이 history에 섞이지 않는다.
- inference 가능한 tick에서 `predictor.predict()`가 실행된다.
- 불가능한 tick은 정상으로 보정되지 않는다.

### Step 3. Product Result/Evidence append

- 기존 Product Result/Evidence core 계약을 유지한다.
- `build_product_result_artifact()`로 Artifact를 생성한다.
- 새 runtime result는 새 artifact/result ID로 append한다.
- latest는 query에서 선택한다.

완료 기준:

- 같은 asset의 정비 전/후 Result가 둘 다 조회된다.
- 기존 Result가 overwrite되지 않는다.
- Evidence projection/report consumer가 raw input을 재생성하지 않는다.

### Step 4. Runtime status + AssetDetailViewModel + API

- `current_result_summary`와 `runtime_status`를 분리한다.
- Product Result 판단 시점과 runtime 진행 시점을 따로 노출한다.
- PR #128 UI가 필요한 `risk`, `data_status`, `evidence.gaps`, `closed_loop` summary를 내려준다.

완료 기준:

- Overview, Side Task View, Operations, Report entry가 같은 ViewModel snapshot을 소비한다.
- runtime 대기/실패 상태가 기존 Product Result를 덮어쓰지 않는다.

### Step 5. Frontend live update

- polling 또는 replay/live signal로 runtime status/latest result 변화를 감지한다.
- 변화가 있으면 latest/detail/evidence/ViewModel API를 refetch한다.
- raw observation/raw score는 화면에 직접 반영하지 않는다.

완료 기준:

- 새 Product Result가 생기면 #128 Overview와 Side Task View가 갱신된다.
- `history_insufficient`/`warming_up`이 UI에 별도 상태로 표시된다.

### Step 6. Closed-loop mutation/API 연결

- 작업요청, 승인, 점검 시작/완료, RecommendationDecision, MaintenanceAction을 API로 연결한다.
- mutation 응답은 persisted ID와 resulting state를 반환한다.
- `available_actions`는 Backend가 계산한다.

완료 기준:

- PR #128 처리 탭이 persisted ID/state만 표시한다.
- 권한 없는 액션은 disabled reason 또는 403으로 일관되게 처리된다.

### Step 7. Maintenance replay / simulation overlay 연결

- MaintenanceEvent 완료 후 replay request를 발행한다.
- Runtime Overlay observation available을 Backend Diagnosis가 소비한다.
- 이력 부족이면 `warming_up`/`history_insufficient`를 표시한다.
- 첫 inference-ready observation에서 새 Product Result/Evidence를 append한다.

완료 기준:

- PR #128 UI에서 정비 전/후 상태가 같은 asset lineage로 비교된다.

### Step 8. Generator Runtime shadow integration

- Generator score batch를 Backend Inbox에 shadow 저장한다.
- 같은 Observation에 대해 기존 Backend 결과와 score/source/model lineage를 비교한다.
- Shadow 결과는 Product API/UI/Closed-loop에 노출하지 않는다.

완료 기준:

- parity 기준과 mismatch 처리 규칙이 문서화된다.
- Generator 산출물 누락을 Backend가 추론 보정하지 않는다.

### Step 9. Generator Runtime canonical 전환 여부 결정

- 팀 승인, shadow parity, Product Result/Evidence E2E, rollback 조건이 모두 충족되면 전환한다.
- 전환 전까지 Backend Diagnosis path가 운영 정본이다.
- 전환 후에도 Product Result/Evidence core 계약은 유지한다.

완료 기준:

- canonical source flag가 하나만 활성화된다.
- Backend direct inference 제거는 별도 후속 PR로 진행한다.

## 8. Contract Freeze

### 유지

- Product Result core:
  - `failure_probability`
  - `status_grade`
  - `top_factors`
  - `recommended_action`
  - `evidence_payload`
- Event Evidence projection 의미
- AssetDetailViewModel 소비 의미
- Closed-loop trigger 의미

### Additive만 허용

- source/provenance reference
- runtime status/readiness
- maintenance/replay lineage
- Generator event/batch reference

### 금지

- Product Result를 Generator batch로 대체
- raw score를 UI/Closed-loop trigger로 사용
- schema 확장을 이유로 fixture truth를 먼저 창작
- existing Product Result overwrite

## 9. E2E 목표

### E2E A. Sensor tick to UI live update

```text
sensor tick / observation available
  -> Backend consume
  -> Diagnosis inference
  -> Product Result/Evidence append
  -> runtime status predicted
  -> AssetDetailViewModel updated
  -> PR #128 Overview/Side Task View refetch
```

### E2E B. PR #128 runtime read

```text
Product Result/Evidence exists
  -> AssetDetailViewModel composed
  -> Overview risk queue 표시
  -> Side Task View 상태/처리 표시
  -> Report 출력 진입
```

### E2E C. 작업요청 수집

```text
Product Result/Evidence
  -> Inspection candidate
  -> WorkOrder request
  -> approve/start/complete
  -> Activity append
  -> PR #128 처리 탭 refetch
```

### E2E D. 정비 후 재예측

```text
MaintenanceAction complete
  -> MaintenanceEvent
  -> replay requested
  -> Runtime Overlay Observation available
  -> Backend Diagnosis readiness
  -> post-maintenance Product Result/Evidence
  -> PR #128 UI pre/post 비교
```

### E2E E. Generator shadow

```text
Generator score batch
  -> Backend Inbox shadow 저장
  -> Backend runtime result와 parity 비교
  -> mismatch는 Product Result로 승격하지 않음
```

## 10. 팀 합의가 필요한 결정

1. 큰 Integration PR의 acceptance criteria를 sensor tick -> UI live update까지로 볼지.
2. PR #128 이후 MVP canonical runtime source는 우선 Backend Diagnosis로 유지할지.
3. Generator Runtime을 shadow부터 둘지, 별도 후순위 migration으로 둘지.
4. `Prediction Result Batch` 최소 contract를 어디서 freeze할지.
5. 정비 후 runtime status의 public read location을 `AssetDetailViewModel` summary와 상세 Product API 중 어디까지 노출할지.
6. 기존 Backend direct inference 제거 시점을 어떤 gate 이후로 둘지.

## 11. 결론

PR #128을 기준으로 보면 후속 작업의 중심은 UI 확장이 아니라 Backend/Product/Closed-loop 데이터
연결과 runtime execution E2E다. Generator Runtime 전환은 병렬로 준비할 수 있지만, PR #128 UI와
Closed-loop는 계속 Backend Product Result/Evidence만 소비해야 한다.

권장 진행은 다음이다.

```text
PR #128 read surface 확정
  -> Backend Runtime Execution E2E
  -> Product Result append-only path
  -> runtime status + UI live update
  -> Closed-loop mutation/API 연결
  -> maintenance replay/post-result E2E
  -> Generator Runtime shadow
  -> canonical 전환 여부 결정
```

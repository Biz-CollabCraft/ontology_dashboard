# PR #128 기반 Runtime / Closed-loop 대범위 병렬 작업 제안

Status: draft
Date: 2026-08-26
Base: PR #128 `feat(mvp): 역할별 overview와 asset detail 작업 흐름 정리`
Evidence state: 문서-only 제안; 구현과 E2E runtime 동작은 이 PR에서 `Not Proven`
Reference:

- PR #127 `Generator Runtime Prediction Result Pipeline 및 Outbox 전달 경계 구현`
- Issue #99 `Maintenance Loop Prototype 검증 근거 및 이식 전 계약 Gate`
- `contracts/schemas/prediction-result-batch.schema.json`

## 1. 제안 목적

이 문서는 PR #128 이후의 병렬 개발 순서를 제안한다. 여기의 `완료 기준`과 E2E 문장은
후속 구현 PR/stack에서 검증해야 할 acceptance criteria이며, 이 문서 PR이 Backend Inbox,
Product Result append, Product API/UI live update, Closed-loop mutation, maintenance replay를
이미 구현했다는 뜻이 아니다.

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
  -> Generator observation consume
  -> Generator runtime inference
  -> Prediction Result Batch / Outbox
  -> Backend Prediction Inbox
  -> Backend validation / policy / idempotency
  -> Product Result append
  -> API/read model 갱신
  -> PR #128 UI live update
  -> Closed-loop 작업요청/정비/replay 연결
```

Generator Runtime 전환은 PR #127을 upstream prediction producer로 두고 병렬 개발한다.
첫 Integration target은 Generator Prediction Result Batch를 Backend가 수신해 Product Result/Evidence로
승격하는 E2E다.

## 2. 고정 원칙

1. PR #128 UI는 raw observation, raw score, Generator batch를 직접 소비하지 않는다.
2. Frontend는 `AssetDetailViewModel`, Product API, Maintenance API만 소비한다.
3. Closed-loop는 Product Result/Evidence/RecommendationDecision만 trigger로 사용한다.
4. Product Result Artifact는 append-only다. latest는 query 결과이지 저장 overwrite가 아니다.
5. Generator Runtime 전환이 승인되어도 Product Result/Evidence core 의미는 바꾸지 않는다.
6. Generator 산출물이 추가되면 core schema 재설계가 아니라 provenance/source trace로 연결한다.
7. Backend Diagnosis는 Product Result/Evidence 승격 gate를 맡는다.
8. Generator는 raw score / Prediction Result Batch producer contract를 끝까지 책임진다.
9. Backend direct inference 제거는 Generator delivery, Backend Inbox, Product Result 승격, rollback 가능 상태 확인 뒤 별도 마지막 PR로만 수행한다.

## 3. 큰 범위

포함:

- live/simulation observation available marker 감지
- Generator runtime observation/history consume
- Generator Prediction Result Batch / Outbox
- Backend Prediction Inbox/checksum/idempotency
- Backend validation/product policy
- Product Result Artifact / Evidence append
- runtime status/readiness API
- `AssetDetailViewModel`의 `current_result_summary` / `runtime_status`
- PR #128 UI polling/refetch 또는 replay signal 기반 live update
- Closed-loop 작업요청/승인/정비 mutation
- Maintenance replay -> post-maintenance Product Result
- Generator Runtime delivery와 failure status 검증

제외:

- Product Result/Evidence core 의미 변경
- Frontend의 raw score 직접 소비
- Closed-loop의 raw Generator batch 직접 소비
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

### Track A. Generator Runtime Prediction Producer

담당: Generator owner

이 Track은 PR #127 기반 upstream prediction path다. Generator는 Product Result/Evidence를 만들지
않지만, live/simulation observation을 consume해 Backend가 승격 가능한 Prediction Result Batch를
생산해야 한다.

책임:

- sensor/live output 또는 simulation overlay available marker 감지
- same-asset observation/history window 구성
- `history_requirement` 기반 readiness 판단
- Model Artifact snapshot/checksum 검증
- runtime feature 계산
- model inference
- Prediction Result Batch 생성
- Outbox retry/dead-letter
- Backend 응답 코드별 retry/stop 처리
- source/model/feature/history/maintenance lineage 전달

완료 기준:

- 새 tick 또는 overlay observation을 처리하면 Prediction Result Batch가 발행된다.
- 같은 tick을 재처리해도 중복 Batch가 생성되거나 중복 delivery되지 않는다.
- inference 불가 상태는 `warming_up`, `history_insufficient`, `failed_*`로 드러난다.
- Product Result/Evidence, severity, recommendation은 생성하지 않는다.

금지:

- history 부족 상태를 정상 score로 보정
- current observation을 history baseline에 중복 포함
- Product Result Artifact / Evidence 생성
- WorkOrder 또는 MaintenanceAction 생성

### Track B. Backend Prediction Inbox / Product Result Gate

담당: Backend Diagnosis / Product Result owner

이 Track이 PR #128과 Closed-loop를 실제 제품 흐름으로 살리는 critical path다. Backend는 Generator
Prediction Result Batch를 수신하고, 검증된 결과만 Product Result/Evidence로 승격한다.

책임:

- Prediction Result Batch 수신
- contract/scope/lineage 검증
- `event_id + payload_sha256` idempotency/conflict 처리
- allowed source/model/status 검증
- threshold/status/recommendation product policy 적용
- `build_product_result_artifact()` 호출
- Product Result Artifact / Evidence append-only 저장
- runtime status/readiness record 생성
- latest/timeline/detail read model 갱신
- `AssetDetailViewModel` composer에 `current_result_summary`와 `runtime_status` 제공

Generator가 Backend로 넘겨야 하는 최소 contract:

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

이 최소 handoff는 `contracts/schemas/prediction-result-batch.schema.json`와
`contracts/examples/prediction-result-batch/` 예제로 freeze한다. 이 계약은 raw upstream
batch이며 Product Result Artifact, Event Evidence, UI trigger가 아니다.

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

- Generator가 누락한 feature/history/source lineage를 Backend에서 추론해 보정
- raw score를 Product Result 없이 Frontend/Closed-loop에 노출
- asset 기준 overwrite로 기존 Product Result를 갱신
- Evidence를 UI/ViewModel consumer에서 재생성

### Track C. Backend Direct Inference Baseline / Rollback

담당: Backend Diagnosis / Product Result owner

이 Track은 새 canonical upstream이 아니라 migration 안전장치다. PR #127 기반 Generator delivery와
Backend Inbox/Product Result E2E가 안정화되기 전까지 기존 Backend direct inference는 baseline 또는
rollback path로만 기록한다.

책임:

- 기존 Backend direct inference entrypoint 목록화
- feature flag 또는 운영 비활성화 조건 정의
- Generator path 장애 시 rollback 기준 정의
- 동일 observation에 대한 parity/mismatch evidence 수집
- 제거 PR의 acceptance criteria 정의

구현 우선순위:

1. Generator Prediction Result Batch -> Backend Product Result E2E를 먼저 통과시킨다.
2. 기존 Backend direct inference가 동시에 Product Result를 만들지 않게 flag를 정리한다.
3. rollback이 필요한 상태와 허용 환경을 문서화한다.
4. 제거는 별도 마지막 PR로 진행한다.

금지:

- Product Result 이중 생성
- Backend direct inference를 장기 canonical path로 재고정
- rollback path를 UI/Closed-loop 별도 소비 계약으로 노출

### Track D. Closed-loop Domain / Maintenance API

담당: Closed-loop owner

Issue #99에는 Inspection, Recommendation, Decision, WorkOrder, MaintenanceEvent의 기본
상태 전이와 이식 Gate가 완료/미완료로 나뉘어 기록되어 있다. 이 문서는 그 이슈의 완료 항목을
구현 근거로 재판정하지 않으며, PR #128 후속에서는 남은 Product API/UI lineage, runtime status,
배포형 E2E gap을 화면이 소비할 수 있는 read model과 mutation response로 연결한다.

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
Track A Generator Runtime Prediction
  -> Prediction Result Batch / Outbox

Track B Backend Prediction Inbox
  -> validation / policy / Product Result/Evidence append

Track C Backend Direct Inference
  -> baseline / rollback / removal gate

Track D Closed-loop
  -> Product Result/Evidence 기반 작업 상태 전이

Track E Frontend
  -> PR #128 live read surface API 연결
```

초기 통합 정본은 Generator Prediction Result Batch를 Backend가 승격하는 경로로 둔다.

```text
0. PR #127/#128/#129의 최신 base/head와 팀 승인 상태를 확인한다.
1. Prediction Result Batch 최소 contract를 `contracts/schemas/prediction-result-batch.schema.json`로 freeze한다.
2. Backend Prediction Inbox가 Batch를 검증하고 Product Result/Evidence로 승격한다.
3. PR #128 UI는 Backend Product API/ViewModel 변화를 refetch한다.
4. Closed-loop는 Product Result/Evidence와 persisted mutation response 기반으로 작업요청/정비/replay를 연결한다.
5. Maintenance replay -> post-maintenance Product Result E2E를 닫는다.
6. rollback 가능 상태 확인 후 기존 Backend direct inference 제거를 별도 마지막 PR로 진행한다.
```

## 7. 큰 범위 구현 순서

### Step 1. Runtime tick consume / idempotency

- live sensor 또는 simulation overlay available marker를 Generator worker가 감지한다.
- 처리 cursor, source checksum, consume status를 저장한다.
- duplicate tick은 skip/reuse하고 checksum conflict는 fail-closed로 남긴다.

완료 기준:

- 같은 marker를 두 번 처리해도 Product Result가 중복 생성되지 않는다.
- 처리 실패 상태가 runtime status로 조회된다.

### Step 2. Observation -> Diagnosis execution

- Generator가 새 observation과 same-asset history window를 구성한다.
- Generator가 `history_requirement`를 확인한다.
- 준비되면 Generator runtime inference를 실행하고 Prediction Result Batch를 만든다.
- 부족하면 Product Result를 만들지 않고 `warming_up`/`history_insufficient`를 전달한다.

완료 기준:

- current observation이 history에 섞이지 않는다.
- inference 가능한 tick에서 Generator runtime prediction이 실행된다.
- 불가능한 tick은 정상으로 보정되지 않는다.

### Step 3. Backend Prediction Inbox -> Product Result/Evidence append

- 기존 Product Result/Evidence core 계약을 유지한다.
- Backend가 Prediction Result Batch의 contract/scope/checksum/lineage/idempotency를 검증한다.
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
- Runtime Overlay observation available을 Generator Runtime Pipeline이 소비한다.
- 이력 부족이면 `warming_up`/`history_insufficient`를 표시한다.
- 첫 inference-ready observation에서 Generator가 Prediction Result Batch를 발행한다.
- Backend가 Batch를 검증한 뒤 새 Product Result/Evidence를 append한다.

완료 기준:

- PR #128 UI에서 정비 전/후 상태가 같은 asset lineage로 비교된다.

### Step 8. Generator Runtime delivery integration

- Generator score batch를 Backend Inbox에 전달한다.
- Backend는 검증 전 score/source/model lineage를 Product API/UI/Closed-loop에 노출하지 않는다.
- delivery failure와 mismatch는 runtime status로 남긴다.

완료 기준:

- delivery retry, dead-letter, mismatch 처리 규칙이 문서화된다.
- Generator 산출물 누락을 Backend가 추론 보정하지 않는다.

### Step 9. Backend direct inference 제거 여부 결정

- 팀 승인, Generator delivery, Backend Inbox, Product Result/Evidence E2E, rollback 조건이 모두 충족되면 제거한다.
- 제거 전까지 Backend direct inference는 baseline/fallback path로만 둔다.
- 제거 후에도 Product Result/Evidence core 계약은 유지한다.

완료 기준:

- Product Result 생성 source flag가 하나만 활성화된다.
- Backend direct inference 제거는 별도 후속 PR로 진행한다.

## 8. Contract Freeze

현재 freeze된 범위:

- `contracts/schemas/prediction-result-batch.schema.json`
- `contracts/examples/prediction-result-batch/*.json`
- Backend typed validator `PredictionResultBatch`
- validation receipt endpoint:
  `POST /api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance/prediction-result-batches/validate`

이 endpoint는 Product Result 생성, DB 저장, Inbox idempotency persistence, Closed-loop trigger를
수행하지 않는다. 그 구현은 다음 Backend Prediction Inbox / Product Result Gate 단계다.

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
  -> Generator consume
  -> Generator Runtime Prediction
  -> Prediction Result Batch / Outbox
  -> Backend Prediction Inbox validation
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
  -> Generator readiness / Prediction Result Batch
  -> Backend Prediction Inbox validation
  -> post-maintenance Product Result/Evidence
  -> PR #128 UI pre/post 비교
```

### E2E E. Generator delivery failure

```text
Generator score batch
  -> Backend Inbox 검증 실패
  -> runtime status failed_*
  -> 기존 Product Result는 overwrite되지 않음
```

## 10. 팀 합의가 필요한 결정

1. 큰 Integration PR의 acceptance criteria를 sensor tick -> UI live update까지로 볼지.
2. PR #127 기반 Generator Runtime을 upstream prediction producer로 freeze할지.
3. Backend direct inference를 baseline/fallback으로만 남길지.
4. `Prediction Result Batch` 최소 contract를 어디서 freeze할지.
5. 정비 후 runtime status의 public read location을 `AssetDetailViewModel` summary와 상세 Product API 중 어디까지 노출할지.
6. 기존 Backend direct inference 제거 시점을 어떤 gate 이후로 둘지.

## 11. 결론

PR #128을 기준으로 보면 후속 작업의 중심은 UI 확장이 아니라 Backend/Product/Closed-loop 데이터
연결과 runtime execution E2E다. PR #127 기반 Generator Runtime은 upstream prediction producer로
병렬 개발할 수 있지만, PR #128 UI와 Closed-loop는 계속 Backend Product Result/Evidence만 소비해야 한다.

권장 진행은 다음이다.

```text
PR #128 read surface 확정
  -> Generator Runtime Prediction / Prediction Result Batch
  -> Backend Prediction Inbox / Product Result append-only path
  -> runtime status + UI live update
  -> Closed-loop mutation/API 연결
  -> maintenance replay/post-result E2E
  -> Backend direct inference 제거 여부 결정
```

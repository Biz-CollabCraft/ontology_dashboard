# Closed-loop Runtime Overlay 통합 계약

## 1. 문서 지위와 목적

이 문서는 최종 예지보전 시연에서 정비 결과를 새로운 Observation과 Runtime
Prediction으로 연결하는 시스템 간 Target 계약이다.

기존 계약과의 책임은 다음처럼 나눈다.

| 문서 | 책임 |
|---|---|
| `closed-loop-domain-contract.md` | Recommendation, Decision, WorkOrder, MaintenanceAction, MaintenanceEvent의 상태와 불변식 |
| `closed-loop-product-consumption-contract.md` | Product API/UI의 역할, Action, 상태·오류 소비 방식 |
| 이 문서 | Closed-loop 완료 이벤트 → 대상 설비 Runtime Overlay → Backend 재추론 연결 |
| `closed-loop-implementation-plan.md` | 구현 PR 순서와 담당자별 인계 |

이 문서는 Canonical V3.1 또는 과거 Result/Evidence를 수정하는 계약이 아니다.
시스템 경계를 넘는 최종 기계 판독 계약은 팀 검토 후 `contracts/schemas/`의
versioned JSON Schema로 고정한다.

## 2. 결정 요약

- 전체 Generator를 재구축하지 않는다.
- 정비 대상 설비만 기존 Replay에서 Runtime Overlay로 분기한다.
- 정비 중 대상 설비의 정상 센서 Replay와 Runtime Prediction을 중단한다.
- 다른 설비의 Replay는 계속 진행한다.
- 정비 완료 후 Snapshot에 정비 효과를 반영한다.
- 실제 시간만큼 기다리지 않고 **대상 설비 Overlay branch의 Simulation Clock만**
  Fast-forward하여 필요한 정비 후 이력을 생성한다.
- 필요한 Observation 수는 고정값이 아니라 현재 Model Artifact의
  `history_requirement.json`에서 계산한다.
- Backend는 첫 번째 `inference-ready` Observation에서 신규 Runtime Prediction과
  Product Result/Evidence를 생성한다.
- Canonical, 정비 전 Observation, 정비 전 Product Result/Evidence는 immutable하게
  보존한다.
- 정비 완료 자체를 정상 판정으로 사용하지 않는다.

## 3. 전체 흐름

```text
Canonical V3.1 Replay
        ↓
Runtime Observation
        ↓
Backend Runtime Prediction / Product Result / Evidence
        ↓
Recommendation → Decision → WorkOrder → MaintenanceAction
        ↓
maintenance.started
        ↓
대상 설비 Replay·Prediction pause
        ↓
maintenance.completed
        ↓
정비 효과를 대상 설비 Overlay Snapshot에 적용
        ↓
maintenance.replay_requested
        ↓
대상 설비 Overlay branch clock Fast-forward
        ↓
history_requirement 충족
        ↓
Post-maintenance Overlay Observation
        ↓
Backend Runtime Prediction / 새 Product Result / Evidence
```

## 4. Canonical과 Runtime Overlay 분리

Canonical/source reference Replay는 계속 read-only다. Canonical CSV에 없는 값을
Canonical Replay가 생성한다고 표현하지 않는다.

Runtime Overlay는 Closed-loop 시연을 위한 별도의 opt-in 실행 경로다.

```text
Canonical 예정값
220 → 221 → 222 → 223 ...
            │ TOOL_REPLACEMENT
            └─ 기존 예정값 재개 금지

Runtime Overlay branch
0 → 1 → 2 → 3 ...
```

다음 데이터는 수정하지 않는다.

- Canonical source와 reference fixture
- 정비 전 Observation
- 정비 전 Product Result/Evidence
- 기존 Recommendation, Decision, WorkOrder, MaintenanceAction, MaintenanceEvent

정비 후 Runtime state, Observation과 Result/Evidence는 append-only로 추가한다.

## 5. 설비 상태와 Maintenance gap

```text
RUNNING
  │ maintenance.started
  ▼
MAINTENANCE
  │ maintenance.completed + effect 적용
  ▼
RESTARTING
  │ restart_at 도달 + history 준비
  ▼
RUNNING
```

- `maintenance.started`부터 대상 설비의 정상 센서 Observation과 Prediction을 중단한다.
- Maintenance gap을 정상값이나 센서값 `0`으로 채우지 않는다.
- 정비 상태는 센서 Observation이 아니라 운영 상태와 Activity로 표현한다.
- `maintenance_completed_at`이나 `restart_at`이 늦게 오면 pause 상태를 유지한다.
- Timeout만으로 자동 재개하지 않는다.
- 다른 설비의 Replay Clock과 데이터 생성은 영향을 받지 않는다.

## 6. 단계별 Integration 이벤트

### 6.1 `maintenance.started`

Closed-loop가 발행하고 Runtime Overlay consumer가 소비한다.

- 대상 설비를 `MAINTENANCE`로 전환
- 대상 설비 정상 Replay·Prediction pause
- 중복 수신 시 동일 결과 replay
- 완료된 MaintenanceEvent는 아직 존재하지 않으므로 `maintenance_action_id`를 lifecycle
  correlation key로 사용하고 `maintenance_event_id`를 임의 생성하지 않는다.

### 6.2 `maintenance.completed`

MaintenanceAction, WorkOrder와 MaintenanceEvent가 Domain 계약에 따라 완료된 transaction에서
Outbox에 적재한다.

- 공유 이벤트 완료 시각 필드명은 `maintenance_completed_at`을 사용한다.
- 내부 Domain/DB의 `completed_at`은 유지할 수 있으며 발행 adapter에서 매핑한다.
- `action_code`와 정비 효과를 검증한다.
- 완료만으로 Replay를 재개하거나 정상으로 판정하지 않는다.

### 6.3 `maintenance.replay_requested`

- 완료된 MaintenanceEvent가 존재해야 한다.
- `restart_at >= maintenance_completed_at >= maintenance_started_at`이어야 한다.
- `restart_at` 이후 대상 설비 Overlay branch에서만 Observation 생성을 재개한다.
- `restart_at`이 미래이면 해당 virtual time까지 대기한다.
- 이미 지난 경우 최초 가능한 Overlay tick부터 생성한다.

### 6.4 발행·소비 경계

기계 이벤트 이름은 기존 Outbox의 소문자 dot notation을 따른다.

| event type | producer | consumer | 역할 |
|---|---|---|---|
| `maintenance.started` | Closed-loop | `gen_data` Runtime Overlay adapter | 대상 설비 pause |
| `maintenance.completed` | Closed-loop | `gen_data` Runtime Overlay adapter | 완료 사실과 effect 전달 |
| `maintenance.replay_requested` | Closed-loop | `gen_data` Runtime Overlay adapter | restart/branch 생성 요청 |
| `runtime_overlay.observations.ready` | `gen_data` Runtime Overlay | Backend ingestion/diagnosis adapter | 생성된 branch와 Observation 범위 인계 |

Backend Diagnosis는 `maintenance.*` 이벤트만 보고 Prediction하지 않는다.
`runtime_overlay.observations.ready`의 branch가 append-only Overlay 저장소에 반영된 뒤
해당 Observation을 읽어 history requirement를 평가한다. 최종 transport와 payload
Schema는 구현 PR 전에 `contracts/schemas/`에서 고정한다.

## 7. 멱등성과 순서

| 필드 | 목적 |
|---|---|
| `maintenance_action_id` | 시작부터 완료까지의 lifecycle correlation |
| `maintenance_event_id` | 완료 이후 정비 전후 업무 lineage |
| `idempotency_key` | 동일 delivery의 중복 여부 |
| `state_version` | 대상 설비 Runtime state의 순서와 최신성 |

- Closed-loop event producer가 동일
  `simulation_session_id + equipment_id + maintenance_action_id` 범위에서
  `state_version`을 단조 증가시킨다.
- `maintenance.started`, `maintenance.completed`, `maintenance.replay_requested`의
  일반적인 version은 각각 `1`, `2`, `3`이지만 consumer는 event type 문자열 정렬이
  아니라 전달된 version과 Domain 선행 조건을 함께 검증한다.
- 동일 key와 동일 payload는 기존 처리 결과를 반환한다.
- 동일 key에 다른 payload는 conflict다.
- 낮은 `state_version`은 stale event로 거절하거나 명시적으로 무시한다.
- 동일 version과 동일 payload는 멱등 처리한다.
- 동일 version에 다른 payload는 conflict다.
- 완료되지 않은 Maintenance의 restart 요청은 처리하지 않는다.

## 8. 정비 효과 계약

MVP의 `TOOL_REPLACEMENT`는 다음 typed patch를 사용한다.

```json
{
  "action_code": "TOOL_REPLACEMENT",
  "state_patch": {
    "tool_wear_min": {
      "operation": "reset",
      "value": 0,
      "unit": "min"
    }
  }
}
```

- `action_code`별 허용 field, operation, value, unit을 whitelist한다.
- `TOOL_REPLACEMENT`는 승인된 공구 마모 상태만 변경한다.
- 허용되지 않은 필드나 단위는 fail-fast한다.
- patch는 Canonical이 아니라 해당 Simulation Session의 Overlay Snapshot에만 적용한다.
- 향후 범용화할 때는 versioned `maintenance_effect` 계약으로 확장할 수 있다.

## 9. 이벤트 최소 필드

```json
{
  "contract_version": "maintenance-replay-v1",
  "event_type": "maintenance.replay_requested",
  "event_id": "EVT-001",
  "idempotency_key": "MAINT-001:3",
  "state_version": 3,
  "simulation_session_id": "DEMO-001",
  "maintenance_event_id": "MAINT-001",
  "maintenance_action_id": "ACTION-001",
  "work_order_id": "WO-001",
  "equipment_id": "CNC-S02-L04-03",
  "maintenance_started_at": "...",
  "maintenance_completed_at": "...",
  "restart_at": "...",
  "action_code": "TOOL_REPLACEMENT",
  "state_patch": {
    "tool_wear_min": {
      "operation": "reset",
      "value": 0,
      "unit": "min"
    }
  },
  "caused_by": {
    "source_product_result_id": "RESULT-001",
    "source_evidence_id": "EVIDENCE-001",
    "decision_id": "DEC-001"
  }
}
```

모든 시각과 완료 ID를 최초 이벤트에 강제하지 않는다. 이벤트별 required field는
다음과 같이 구분하고 최종 JSON Schema에서 고정한다.

| event type | 추가 required field |
|---|---|
| 공통 | `contract_version`, `event_id`, `idempotency_key`, `state_version`, `simulation_session_id`, `maintenance_action_id`, `equipment_id` |
| `maintenance.started` | `work_order_id`, `maintenance_started_at`, `action_code` |
| `maintenance.completed` | `maintenance_event_id`, `maintenance_completed_at`, `action_code`, `state_patch` |
| `maintenance.replay_requested` | `maintenance_event_id`, `restart_at` |
| `runtime_overlay.observations.ready` | `maintenance_event_id`, `overlay_branch_id`, Observation 범위·개수와 저장 reference |

## 10. Overlay branch와 Simulation Clock

Fast-forward는 전체 Session Clock에 적용하지 않는다.

```text
Canonical Replay Clock
├── CNC-01 계속 진행
├── CNC-02 pause
│   └── CNC-02 Overlay branch clock만 Fast-forward
└── CNC-03 계속 진행
```

- 대상 설비 branch의 `observed_at`은 단조 증가해야 한다.
- `restart_at` 이전 Overlay Observation은 생성하지 않는다.
- `observed_at`은 virtual observation time이다.
- `generated_at`은 시스템이 실제로 레코드를 생성한 wall-clock time이다.
- 같은 Canonical version, seed, Snapshot과 정비 효과로 재실행하면 동일한 Overlay를
  재현할 수 있어야 한다.

## 11. Overlay Observation과 lineage

```json
{
  "observation_id": "OBS-POST-001",
  "equipment_id": "CNC-S02-L04-03",
  "observed_at": "...",
  "generated_at": "...",
  "source_kind": "maintenance_replay_overlay",
  "base_dataset_version": "canonical-v3.1",
  "base_source_sha256": "<sha256>",
  "observation_sha256": "<sha256>",
  "simulation_session_id": "DEMO-001",
  "overlay_branch_id": "MAINT-001:post",
  "maintenance_event_id": "MAINT-001",
  "state_version": 3,
  "history_segment_id": "MAINT-001:post"
}
```

Model Artifact의 학습 provenance와 운영 Maintenance lineage를 혼합하지 않는다.

### 11.1 저장과 조회 경계

현재 Canonical Observation 저장소는 `source_kind=canonical_observation` 의미와 Dataset
Version 기반 identity를 사용한다. Runtime Overlay 행을 Canonical 테이블에 그대로
삽입하거나 Canonical 행을 update하지 않는다.

MVP Target은 별도 append-only Runtime Overlay 저장소를 사용한다. 실제 테이블명은
migration PR에서 확정하지만 논리적으로 다음 key와 lineage를 보존해야 한다.

```text
organization_id + project_id + workspace_id
+ simulation_session_id + overlay_branch_id
+ equipment_id + observed_at
```

권장 저장소 이름은 `pm_runtime_overlay_observations`다. 동일 key에 다른 payload가 오면
conflict로 처리하고, `observation_sha256`이 같은 재전송은 멱등 처리한다.

branch-aware read model은 다음 규칙을 사용한다.

- 정비 대상이 아닌 설비: 기존 Canonical Replay를 계속 조회
- 정비 대상 설비의 `maintenance_started_at` 이전: 기존 Canonical Observation 조회
- Maintenance gap: 정상 센서 Observation 없음
- 정비 대상 설비의 `restart_at` 이후: 해당 `overlay_branch_id` Observation만 조회
- 대상 설비의 정비 전 예정 Canonical 미래 행을 Overlay 뒤에 다시 합치지 않음

단순 `UNION ALL`로 Canonical 미래 행과 Overlay 행을 함께 반환하지 않는다. Backend
Feature history와 Product Observation API는 동일 branch-aware read rule을 사용해야 한다.

기존 Backend/Frontend의 `source_kind: "canonical_observation"` literal은 구현 PR에서
`"canonical_observation" | "maintenance_replay_overlay"`로 additive 확장한다.
`base_source_sha256`은 기반 Canonical Snapshot의 checksum이고,
`observation_sha256`은 canonicalized Overlay Observation과 lineage의 무결성 값이다.

## 12. Feature history와 Prediction

- `restart_at`부터 새 `history_segment_id`를 시작한다.
- 별도 계약이 없으면 정비 전 history를 정비 후 Rolling/Lag Feature에 섞지 않는다.
- 최소 Observation 수와 lookback은 현재 Model Artifact의 `history_requirement.json`에서
  계산한다.
- 고정된 demo 숫자를 Model contract 대신 사용하지 않는다.
- 요구 이력을 충족하지 못하면 heuristic이나 silent fallback으로 Prediction하지 않는다.
- 첫 번째 `inference-ready` Observation에서 최초 Prediction을 정확히 한 번 생성한다.
- 이후에는 정상 Runtime Prediction 주기를 유지한다.

최초 Prediction 중복 방지 키는 최소 다음 식별자를 결합한다.

```text
maintenance_event_id + history_segment_id + prediction_target_time
```

## 13. API/UI 상태 의미

| 상태 | Product 의미 |
|---|---|
| `equipment_under_maintenance` | 대상 설비 정비 진행 중 |
| `warming_up` | 정비 후 요구 Observation 이력 생성 중 |
| `history_insufficient` | 요구 이력을 확보할 수 없어 Prediction 불가 |
| `ready` | 추론 가능한 이력 확보 |
| `predicted` | 신규 Runtime Prediction과 Result/Evidence 생성 완료 |

`warming_up`과 `history_insufficient`를 `NORMAL`로 표시하지 않는다. 정비 완료 역시
정상 Prediction이 아니다. 정비 후 실제 Prediction이 조치 불필요로 판정한 경우에만
정상으로 표시한다.

## 14. 역할 경계

| 담당 | 소유 책임 | 소유하지 않는 책임 |
|---|---|---|
| 광우 / Closed-loop | Maintenance 상태, transaction, 단계별 Outbox 이벤트, 운영 lineage | Overlay 생성, Feature 계산, Prediction |
| 성민 / `gen_data` Generator·Replay | 대상 설비 pause/branch, Snapshot effect, branch-local Fast-forward, Overlay Observation | Product Result/Evidence |
| 호범 / Backend Diagnosis | Overlay Observation 소비, history 경계, Runtime Prediction, Product Result/Evidence | Maintenance 상태 변경, Overlay 센서 생성 |
| 우수 / Product API·UI·E2E | 진행 상태·결과 노출, 통합 시나리오 검증 | Domain 상태·Prediction 의미 재계산 |

`ontology_dashboard/systems/generator`의 책임은 Feature/Label, training과 Model Artifact
publish이며 Runtime Overlay 실행 주체가 아니다.

## 15. 완료 조건

- [ ] 대상 설비만 기존 Replay에서 분기된다.
- [ ] Maintenance gap 동안 대상 설비 정상 Replay와 Prediction이 중단된다.
- [ ] 다른 설비의 Replay Clock과 데이터는 영향을 받지 않는다.
- [ ] 부분·지연 이벤트에도 완료 전 자동 재개하지 않는다.
- [ ] `idempotency_key`와 `state_version` 규칙이 검증된다.
- [ ] 정비 효과가 action별 whitelist를 통과한다.
- [ ] Canonical과 정비 전 Observation/Result/Evidence는 변경되지 않는다.
- [ ] Overlay Observation에 `source_kind`, branch, Maintenance lineage가 기록된다.
- [ ] Overlay Observation은 Canonical 테이블과 분리된 append-only 저장소에 기록된다.
- [ ] branch-aware read가 대상 설비의 정비 후 Canonical 미래 행을 다시 섞지 않는다.
- [ ] 필요한 이력은 `history_requirement.json`에서 계산한다.
- [ ] 정비 전후 Feature history가 암묵적으로 혼합되지 않는다.
- [ ] 첫 inference-ready Observation에서 신규 Result/Evidence가 한 번 생성된다.
- [ ] 정비 완료나 warming-up 상태가 정상 Prediction으로 표시되지 않는다.
- [ ] 정비 전 Result부터 정비 후 Result까지 `maintenance_event_id`로 추적할 수 있다.

## 16. 후속 기계 판독 계약

팀 검토 완료 후 다음 Schema와 OpenAPI를 별도 구현 PR에서 확정한다.

```text
contracts/schemas/maintenance-replay-event.schema.json
contracts/schemas/runtime-overlay-observation.schema.json
```

문서 예시만으로 producer와 consumer를 독립 구현하지 않는다. Schema 확정 전에는 이
문서를 Target 계약으로 사용하고, 계약 변경은 관련 소유자 리뷰를 거친다.

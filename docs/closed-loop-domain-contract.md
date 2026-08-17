# Closed-loop Domain 계약

이 문서는 `closed-loop-implementation-plan.md`의 PR 1 구현 기준이다. HTTP, DB,
Product Result/Evidence projection은 이 범위에 포함하지 않는다.

## 기존 Decision과 실행 권한 매핑

| 기존 Decision 값 | 운영 의미 | 점검 Work Order | 정비 Work Order |
|---|---|---:|---:|
| `continue_monitoring` | 관찰 지속 | 불가 | 불가 |
| `request_inspection` | 현장 점검 요청 | 가능 | 불가 |
| `review_shutdown` | 가동 중단 검토 및 현장 확인 요청 | 가능 | 불가 |
| `hold_for_data_check` | 데이터 확인 전 보류 | 불가 | 불가 |

기존 Decision 네 값에는 정비 승인이 없다. 따라서 `review_shutdown`을 승인으로
해석하지 않으며, 정비 Work Order는 해당 Operational RecommendedAction에 대한 별도
`RecommendationDecision(disposition=accept)`이 있고 추천 상태가 `accepted`일 때만
허용한다.

## 객체 경계

- Producer recommendation: Product Result/Evidence producer가 소유하는 원본 후보
- Operational RecommendedAction: 원본 의미를 바꾸지 않고 운영 ID와 상태만 추가한 projection
- RecommendationDecision: 사람이 추천을 승인·거절·보류한 판단
- WorkOrder: 점검 또는 정비 업무 단위
- MaintenanceAction: 승인된 정비 Work Order 안에서 수행하는 실제 행동
- MaintenanceEvent: 완료된 정비 사실을 나타내는 불변 이력

`request_inspection`과 `review_shutdown`은 기존 동작에 맞춰 inspection Work Order만
허용한다. 둘 다 정비 승인의 의미는 없다. maintenance Work Order와 MaintenanceAction은
명시적인 추천 승인 없이는 생성할 수 없다.

모든 운영 레코드는 `organization_id`, `project_id`, `workspace_id` scope를 보존한다.
RecommendedAction은 Equipment, Event, Product Result, Evidence와 producer action을
직접 참조한다. 이후 Decision, WorkOrder, MaintenanceAction, MaintenanceEvent는 직전
객체 ID와 Event/Equipment scope를 보존해 전체 흐름을 역추적할 수 있어야 한다.

MaintenanceAction은 승인된 maintenance Work Order에서만 계획할 수 있다.
MaintenanceEvent는 동일 scope와 lineage를 가진 Work Order와 MaintenanceAction이 모두
`completed`인 경우에만 생성한다.

## Identity와 멱등성

- MVP는 `equipment_id = asset_id`를 사용한다.
- stable equipment key는 `organization_id + project_id + asset_id`이며 Dataset Version을
  포함하지 않는다.
- mapping 누락, 중복, `asset_type` 불일치는 추정하지 않고 실패한다.
- Operational RecommendedAction 중복 방지 키는
  `source_product_result_id + source_action_id`다.
- Producer의 action/result/evidence/schema/policy ID와 label, kind, approval requirement,
  basis는 materialization 과정에서 변경하지 않는다.
- 동일 idempotency key와 동일 요청이 성공한 경우 기존 결과를 replay한다.
- 동일 key에 다른 요청을 사용하면 conflict, 기존 요청이 실행 중이거나 실패했다면 각각
  명시적인 `action_in_progress`, `prior_action_failed` 상태로 처리한다.

## 상태 전이

- RiskEvent: `open → acknowledged → in_progress → resolved → closed`
- RecommendedAction: `proposed → accepted | rejected | deferred | superseded`
- deferred recommendation: `deferred → accepted | rejected | superseded`
- WorkOrder: `requested → approved → in_progress → completed | blocked | failed | cancelled`
- MaintenanceAction: `planned → in_progress → completed | failed | cancelled`

완료·거절·차단 등 terminal 상태를 과거 상태로 되돌리지 않는다.

## 기존 compatibility projection 교정 범위

현재 `ontology_adapter.py`는 기존 Decision과 Note, 현장 작업 결과를 모두
`maintenance_action` 객체로 투영한다. PR 1에서는 runtime projection을 변경하지 않고
다음 Target 의미만 고정한다.

- 운영 Decision은 Decision/Activity로 유지하며 MaintenanceAction으로 승격하지 않는다.
- Note는 Note/Activity로 유지하며 MaintenanceAction으로 승격하지 않는다.
- inspection Work Order의 현장 점검 결과와 실제 정비 MaintenanceAction을 구분한다.
- 실제 projection 교정은 persistence/API 작업과 Product Result/Evidence 계약 반영 순서에
  맞춰 후속 PR에서 수행한다.

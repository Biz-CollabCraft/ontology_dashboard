# 3역할 공통 근거 조회: 구현된 백엔드 계약

이 문서는 현재 브랜치의 읽기 계약이다. 역할별 점검 요청/수행 재배정, 정비 승인·시작·완료 전이, 일정 협의 command의 변경 계약은 아니다. 축소안은 Closed-loop 담당자와 확정 전이며 기존 명시적 승인과 서버 `available_actions`를 계속 사용한다.

## 프론트 연결

| API / 필드 | 실제 의미 |
|---|---|
| `GET /api/objects/{asset_id}/operational-context` | 새 공통 사이드뷰용 읽기. `events.read` 권한과 active project/scope 검증. 역할별 command를 생성하지 않음 |
| query `project_id`, `workspace_id`, `evidence_snapshot_id`, `decision_as_of` | `snapshot_basis.artifact_id`를 snapshot ID로 전달. detail/Packet과 함께 표시할 때 그 응답의 `snapshot_basis.observed_at`을 as-of로 전달. Event 업무 ID와 Artifact ID를 혼용하지 않음 |
| `identity`, `retrieved_at`, `context_fingerprint` | 요청 tenant/asset/snapshot/as-of, 실제 조회 시각, 해당 Context 집합의 검증 결과와 원본/binding checksum fingerprint |
| `domains.{production,maintenance_readiness,quality_delivery,impact_policy,planning}.context` | 기존 동결 계약으로 검증한 data, status, source_version, source_updated_at, as_of, retrieved_at, source_refs, freshness, limitations |
| `domains.*.provenance` | 검증된 source_context_id, schema_id/version, source_classification, valid_from/to, source_sha256/binding_sha256, bound_evidence_snapshot_id. 전역 원천 binding은 null. 손상·미연결은 provenance도 null |
| `domains.*.reason_codes` | `NO_MATCHING_SCOPE_SNAPSHOT_AT_AS_OF`, `FRESHNESS_POLICY_EXCEEDED`, `STORAGE_OR_CONTRACT_VALIDATION_FAILED`. 첫 코드는 유효한 일치 자료가 없다는 뜻이며, 자료 자체의 부재/만료/다른 snapshot 중 하나로 단정하지 않음 |
| `production_impact.options[]` | 기존 deterministic `stop_now/planned_maintenance/continue_operation` 조건부 비교. state, reason_codes, 입력/중간값, nullable 수치. 실제 손실·대응 실행·생산 회복 결과가 아님 |
| `GET /api/objects/{asset_id}/detail-view` | 기존 ViewModel의 `operation_context`, `evidence_context`, `closed_loop` 유지. 새 공통 API를 병행 소비 가능 |
| `GET /api/objects/{asset_id}/agent-review-packet` | 기존 `evidence_context` 선택 근거/탈락 근거/시점과 `maintenance_history_summary` 조회 |
| `maintenance_history_summary.{work_orders,inspection_results,maintenance_actions,maintenance_events,activities}[].owner_record_provenance` | 실제 owner 응답에 존재하는 작성자·담당자·시각·참조 ID만 원래 필드명 그대로 보존. 없는 actor나 승인 시각을 생성하지 않음 |
| `GET /api/objects/{asset_id}/agent-review-summary` | 기존 저장된 요약 조회. 새 공통 Context GET은 LLM 실행이나 요약 저장을 시작하지 않음 |

새 API는 snapshot 불일치/관측 이전 as-of에 409, timezone 없는 as-of/미래 as-of에 422를 반환한다. 관측 이후의 명시적 as-of도 허용하지만 그 시점에 유효한 Context만 읽는다. 같은 화면에서 다른 as-of 결과를 결합하지 않는다. 응답의 데이터 schema는 `contracts/schemas/operational-context-read.schema.json`, FastAPI response model은 `OperationalContextRead`다. 기존 Packet에 추가된 provenance는 optional이므로 과거 gold payload도 유효하다. 프론트 파일은 수정하지 않았으며 브라우저 연결/E2E는 이 작업의 완료 증거에 포함하지 않는다.

## 미확인·계산·캐시 규칙

- 미연결/만료/실패는 data를 비우고, 영향은 미산정 및 null을 유지한다. 영향 미확인을 `none` 또는 0으로 변환하지 않는다.
- 기존 계산기는 production/maintenance_readiness/quality_delivery와 versioned impact_policy를 사용한다. 시점 불일치나 as-of 이후 원천은 모든 옵션을 미산정 처리하고 `CONTEXT_AS_OF_MISMATCH:<domain>` / `CONTEXT_SOURCE_AFTER_AS_OF:<domain>`을 반환한다. 기존 missing/quality/resource/assumption reason codes도 그대로 유지한다.
- 보전팀의 예상 정지시간은 capacity_units 정책 입력과 다른 개념이다. 이번 구현은 이 값을 기존 계산 입력에 덮어쓰거나 임의 환산하지 않는다. 환산 정책·단위·유효시점·원천 버전이 확정되어야 연결할 수 있다.
- 한 조회에서 Context를 한 번 capture해 source/binding과 fingerprint가 동일 집합을 가리킨다. 기존 brief는 Context fingerprint, scope/snapshot/as-of/role 기준으로 재사용하며 생성 중 Context 변경은 저장을 막는다.
- 기존 Summary key는 maintenance history와 evidence_context를 포함한다. 원본 기록의 actor/time/reference 변경도 해당 Packet key를 바꾼다. provider 입력에서 점검·정비 기록을 보존하도록 바꾸면서 prompt version을 `v1.4-owner-provenance`로 올려 이전 입력 계약의 저장본을 재사용하지 않는다.
- 합성 원천은 DB의 `synthetic_demo_context`를 유지한다. 표시 여부와 별개이며 실자료로 재분류하지 않는다. fixture 유효기간이나 원래 event binding은 변경하지 않았다.

## Closed-loop 담당자에게 필요한 확정 계약

현재 연결 가능한 정본은 기존 `closed_loop`의 WorkOrder, InspectionResult, MaintenanceAction, MaintenanceEvent, Activity다. 이를 Packet/AI 읽기 입력에 투영할 뿐 정본의 command/RBAC/전이 코드는 수정하지 않았다. `recorded_by`는 점검 작성자, `actor_user_id`는 기존 Activity 행의 행위자, `assigned_to`는 담당자다. 서로 대체하지 않는다. 기존 축약 `recorded_at` 외에 원래 시각 필드를 별도로 남겨 의미를 보존한다.

추가 연결 전 담당자가 확정해야 할 내용:

1. 점검 사실·예상 정지시간, 외부 합의 결과·일정, 명시적 승인, 착수 확인이 각각 어떤 실제 조회 응답과 persisted ID로 제공되는지.
2. 각 기록의 organization/project/workspace/asset/event 및 source snapshot 참조, 원작성자와 역할, 기록/발효 시각, 수정 버전 또는 불변 ID 규칙.
3. 변경 응답이 알려주는 갱신 대상 event/asset과 버전. 프론트는 해당 detail/Packet/summary 조회만 갱신하고 별도 상태 머신을 만들지 않는다. 서버 전체 캐시 삭제나 자동 LLM 재생성은 추가하지 않았다.
4. 예상 정지시간의 단위·기준·수정 이력과 기존 비용/생산 계산 입력의 환산 정책. 계약 전에는 두 값을 병렬 근거로 취급한다.

미확정 필드의 placeholder schema, 일정 왕복 상태 머신, 생산 지시·라인 재배정·납기 변경 실행·생산 회복 상태는 만들지 않았다. 일정 합의/정비 승인/작업 시작, 정비 완료/이상 해소/생산 회복은 각각 다른 의미다. 생산 영향 없음은 승인 생략 근거가 아니다.

## 적용 조건

main에는 이전 통합 기반이 없으므로 PostgreSQL 0049/0050, SQLite 0045/0046과 frozen v1 validator, source/event binding repository를 선택적으로 포함했다. 기존 데이터 복사 도구는 원본 checksum을 검증하며 기존 행을 삭제하지 않는다. 이번 검증은 일회용 로컬 DB에만 적용했다. 팀 DB·원격 앱의 현행 상태는 이 작업에서 다시 검증하거나 변경하지 않았다.

읽기 앱 배포 전에 대상 DB의 migration 및 source/binding 준비 상태를 담당자가 확인해야 한다. 미준비 DB에서는 Context 실패/미산정이 유지된다. 이전 후보의 팀 DB 적용 기록과 이번 후보의 앱 배포 여부는 별개다.

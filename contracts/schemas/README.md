# Schemas

모든 계층의 공통 계약을 JSON Schema Draft 2020-12로 관리한다.

- `input-event.schema.json`: Gold event와 runtime switches
- `evidence-package.schema.json`: 모델·정책·근거·context·lineage
- `report.schema.json`: 역할별 grounded report와 human-approved action
- `ui-block.schema.json`: 허용 블록, 순서, data field
- `ontology-core.schema.json`: domain-neutral Object, Link, Action invocation·execution result, traversal, Evidence reference
- `dashboard-platform.schema.json`: resolved Dashboard, tab, board, preference save, dependency graph와 share payload
- `role-workspaces.schema.json`: Executive·Audit·Field·FDE·Model workspace와 approval request 응답
- `ontology-planner.schema.json`: typed Object query, Board recommendation, Dashboard draft와 grounded narrative 응답
- `export.schema.json`: organization/project/workspace 범위의 export request, snapshot과 checkpoint 계약
- `dataset-manifest.schema.json`: Project별 dataset source, checksum, schema alias와 quality rule 계약
- `runtime-overlay-observation.schema.json`, `runtime-overlay-observations-available.schema.json`: 정비 후 Observation과 availability 이벤트 계약. 경로 identity와 Unicode checksum의 canonical 예시는 `contracts/test-vectors/runtime-overlay-output-v1/`을 따른다.
- `prediction-result.schema.json`: Prediction Module과 Dashboard 사이의 Evidence·Model·Action 포함 결과 계약
- `product-result-artifact.schema.json`: Diagnosis Product Result와 추천 미생성(null/empty) 정합성 계약
- `event-evidence-projection.schema.json`: Product Result에서 파생한 Event Evidence와 별도 운영 Decision field 계약
- `asset-detail-view-model.schema.json`: 설비 상세 화면용 Backend composition ViewModel 후보 계약. current/history, asset criticality, 운영/정비 context, review priority, evidence gap owner를 포함한다.
- `maintenance-replay-event.schema.json`: Closed-loop가 발행하는 정비 시작·완료·Overlay 재개 요청 이벤트 계약
- `runtime-overlay-observation.schema.json`: Generator가 발행하는 append-only 정비 후 CNC Overlay Observation 계약
- `runtime-overlay-observations-available.schema.json`: 새 Overlay Observation delta batch를 Backend에 인계하는 이벤트 계약
- `preventive-what-if.schema.json`: 합성 예방조치 Producer의 위험 상승·선행 지표·조치 전후 효과·한계 계약
- `operation-context.schema.json`: 생산관리자 화면용 synthetic 생산계획·생산영향 fixture 계약. Product Result/Evidence 산출에는 사용하지 않는다.
- `procedure-grounding.schema.json`: `procedure-grounding-v1.1` SOP 검색·절차 grounding fixture 계약. Product Evidence나 수리 지시가 아니라 점검 질문·체크리스트와 정비 판단 전 확인사항의 출처를 표시하며 비용·시점 추천을 만들지 않는다.

스키마를 변경할 때는 fixture, Pydantic model, backend tests, Gold evaluator와 TypeScript type을 함께 변경해야 한다. LLM 출력은 스키마와 grounding 검사를 모두 통과하지 못하면 폐기하고 deterministic fallback을 사용한다.

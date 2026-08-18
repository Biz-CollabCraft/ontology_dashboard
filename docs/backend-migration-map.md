# Backend Domain-First Migration Map

이 문서는 `systems/backend/ontology_dashboard`를 `systems/backend/app`으로 수렴할 때
사용하는 **처분 원장(Migration Ledger)** 이다. Source가 현재 import되거나 테스트된다는
사실만으로 제품 필수 기능 또는 자동 이관 대상으로 판단하지 않는다.

## 1. 처분 상태

| 상태 | 의미 |
|---|---|
| `MOVE` | 책임과 구현을 하나의 목표 도메인 또는 Infra로 이관 |
| `SPLIT` | 한 Source의 책임을 둘 이상의 소유자에게 분해한 뒤 레거시 삭제 |
| `REPLACE` | 새 canonical 구현 또는 명시적 bootstrap으로 대체한 뒤 레거시 삭제 |
| `REMOVE` | 승인된 제품 범위가 아니므로 API·테스트 종료 기준을 확인하고 삭제 |
| `DEFER` | 제품 범위 결정 전에는 이관하지 않음. Phase 14 전 반드시 다른 상태로 해소 |

모든 레거시 Python Source는 아래 Ledger의 패턴 하나 이상에 포함되어야 한다.
`UNDECIDED`, 미배정 Source 또는 해소되지 않은 `DEFER`가 하나라도 있으면
`systems/backend/ontology_dashboard`를 삭제할 수 없다.

## 2. 이관 판단 기준

다음 중 하나 이상의 근거가 있어야 `MOVE` 또는 `SPLIT`할 수 있다.

1. 승인된 요구사항·ADR·공유 계약에서 제품 책임으로 정의된다.
2. 최종 API/UI/worker 또는 배포 경로에 실제 consumer가 있다.
3. 보안, 데이터 무결성, 영속성, health/readiness에 필수적이다.
4. 다른 canonical owner인 Generator, `gen_data`, Project 3가 대신 소유하지 않는다.

테스트가 존재하거나 레거시 `main.py`가 Router를 등록한다는 사실만으로는 이관
근거가 되지 않는다. 제거·대체 시에는 삭제되는 API와 회귀 테스트를 같이 기록한다.

## 3. Source 처분 Ledger

| Source | 현재 책임 | 처분 | 목표/결정 | 담당 이슈 |
|---|---|---|---|---|
| `__init__.py` | 레거시 package export | `REPLACE` | `app` package export로 대체 | #64 |
| `app.py`, `application.py`, `application_runtime.py`, `bootstrap.py`, `dependencies.py`, `main.py`, `openapi_contracts.py` | FastAPI host, DI, startup, OpenAPI 조립 | `REPLACE` | `app/main.py`와 composition wiring. 업무 로직은 포함하지 않음 | #64 |
| `settings.py` | 환경·DB·proxy·runtime 설정 | `SPLIT` | 공통 runtime 설정과 Infra 설정을 분리하고 composition에서 조립 | #52, #64 |
| `migrations.py`, `postgresql.py`, `postgresql_compat.py`, `postgresql_pool.py`, `postgresql_repositories.py`, `postgresql_ontology_repository.py` | DB pool, compatibility, 다중 도메인 repository 구현 | `SPLIT` | `infra/db` 기술 구현과 각 도메인 repository adapter로 분리 | #52~#63 |
| `deployment.py`, `persistence_readiness.py`, `observability.py` | health/startup/DB/관측 readiness | `SPLIT` | 필수 probe는 `infra`와 composition으로 이관, Platform 전용 응답은 #68에서 판정 | #52, #64, #68 |
| `security.py` | rate limit과 보안 정책 | `SPLIT` | 인증·권한 정책은 `identity`, Redis 구현은 `infra` | #52, #53 |
| `outbox.py` | Integration Outbox | `SPLIT` | messaging 기술 구현은 `infra`, Maintenance event 의미는 `maintenance` | #52, #59 |
| `artifact_storage.py` | storage driver와 Artifact governance | `SPLIT` | driver는 `infra/storage`, catalog·검증 정책은 `governance` | #52, #63 |
| `connectors.py` | 외부 connector와 ingestion job | `SPLIT` | HTTP/driver는 `infra/external`, ingestion use case는 `dataset` | #52, #57, #68 |
| `llm.py` | provider, report agent, grounding fallback | `SPLIT` | provider는 `infra/llm`, report/planner use case는 각 consumer domain | #52, #61, #62 |
| `integrations/*` | Project 3 client, DTO, projection | `SPLIT` | client는 `infra/external`; projection 의미는 `ontology`/consumer port. 최종 사용 여부 확인 | #52, #55, #62, #68 |
| `identity.py`, `identity_models.py`, `identity_repository.py`, `enterprise_identity.py` | IAM과 일부 Project 책임 | `SPLIT` | IAM은 `identity`, Project lifecycle은 `project` | #53, #54 |
| `projects/*`, `project_context.py` | Project lifecycle/context | `MOVE` | `app/project` | #54 |
| `ontology.py`, `ontology_primitives.py`, `ontology_repository.py`, `ontology_instance_repository.py`, `ontology_service.py`, `ontology_adapter.py` | Ontology registry, instance, action, projection | `SPLIT` | `app/ontology`; 다른 도메인 의미는 public port로 소비 | #55 |
| `domain_packs/*` | 범용 Domain Pack registry와 PdM materialization | `SPLIT` | PdM projection은 `ontology`/`dataset`; 범용 registry 유지 여부는 별도 판정 | #55, #57, #68 |
| `datasets/*` | Dataset catalog/source/projection/materialization | `MOVE` | `app/dataset`, Generator 학습 책임은 제외 | #57 |
| `adapters/*` | Dataset ingestion, file/DB adapter, Prediction repository가 혼재 | `SPLIT` | bundle·CSV·canonical ingestion은 `dataset`, Prediction persistence는 `diagnosis`, 기술 I/O는 `infra` | #52, #57, #58 |
| `predictive_maintenance_runtime/*`, `product_result_evidence_projection.py` | Runtime result/read model/replay | `SPLIT` | inference·Result/Evidence·history readiness는 `diagnosis`; Overlay 생성은 `gen_data` | #58 |
| `modeling/*` | intake, mapping, feature, experiment, model registry/runtime DTO 혼재 | `SPLIT` | Backend runtime consumer 최소 계약만 `diagnosis`/`governance`; 학습·feature 생성은 Generator로 대체 후 Backend에서 삭제 | #58, #63, #68 |
| `analysis_models.py`, `analysis_repository.py`, `analysis_service.py` | 시각적 Analysis graph와 실행 | `DEFER` | Diagnosis로 자동 이관 금지. 유지 시 별도 capability/도메인 필요 | #68 |
| `closed_loop/*` 전체 | Recommendation, Decision, WorkOrder, MaintenanceAction/Event, persistence, integration | `MOVE` | 패키지명을 `app/maintenance`로 수렴 | #59 |
| `contracts.py` | Maintenance, Report, Dashboard, HTTP DTO 혼재 | `SPLIT` | 의미 소유 도메인별 schema로 분해, 공통 오류만 `common` | #59~#63 |
| `service.py`, `repository.py`, `context.py`, `conversation.py` | 제조 Facade, Audit, Project3 fallback, follow-up | `SPLIT` | Equipment/Maintenance/Report/Dashboard/Governance/Planner로 분해하거나 canonical 구현으로 대체 | #56, #59~#63 |
| `dashboard_catalog.py`, `dashboard_models.py`, `dashboard_repository.py`, `dashboard_service.py`, `visualizations/*` | Dashboard/read-model composition | `MOVE` | `app/dashboard`; upstream 의미를 재계산하지 않음 | #60 |
| `reports.py`, `export_models.py`, `export_repository.py`, `export_service.py` | Report와 Export | `MOVE` | `app/report` | #61 |
| `planner/*`, `ontology_planner_models.py`, `ontology_planner_service.py` | 자연어 Planner와 UI plan | `MOVE` | `app/planner`, provider는 Infra port로 소비 | #62 |
| `orchestration/*` | 범용 multi-store Agent orchestration | `DEFER` | 실제 Planner/Report consumer와 승인 계약이 있을 때만 분해 이관 | #62, #63, #68 |
| `governance/*` | Agent trace와 projection governance | `MOVE`/`SPLIT` | 승인된 governance 책임만 `app/governance` | #63, #68 |
| `role_workflow_models.py`, `role_workflow_repository.py`, `role_workflow_service.py` | Field task, 역할별 read model, template/model 승인, audit | `SPLIT` | `maintenance`, `dashboard`, `governance` | #59, #60, #63 |
| `automation_runtime.py` | Platform automation simulation | `DEFER` | Maintenance runtime으로 간주하지 않음 | #68 |
| `branching_lineage.py` | Platform change/merge/policy branch | `DEFER` | `maintenance_replay_overlay`와 다른 개념. Governance 필요성 판정 | #68 |
| `distributed_runtime.py`, `distributed_handlers.py`, `worker.py` | Analysis/Connector Durable Job | `DEFER` | Maintenance Outbox와 분리. 실제 비동기 consumer 유지 시만 Infra+owner domain으로 분해 | #68 |
| `mlops_runtime.py` | Backend Platform drift API | `DEFER` | Generator MLOps 소유권과 충돌 여부 판정 | #68 |
| `pipeline_runtime.py` | Platform sample pipeline plan | `DEFER` | Generator pipeline과 다른 기능. 실제 consumer가 없으면 제거 | #68 |
| `polyglot/*` | Python/R/Java/Node health | `DEFER` | 최종 배포 requirement가 있을 때만 Infra probe로 유지 | #68 |
| `demo_predictive_maintenance_bootstrap.py` | Render용 Canonical demo materialization | `REPLACE` | 명시적 demo seed/bootstrap으로 대체하고 Domain package에서 분리 | #57, #64, #68 |
| `routers/adapters.py`, `routers/datasets.py` | Dataset API | `SPLIT` | `dataset` Router, Prediction endpoint는 `diagnosis` | #57, #58 |
| `routers/auth.py` | IAM API | `MOVE` | `app/identity` | #53 |
| `routers/projects.py` | Project API | `MOVE` | `app/project` | #54 |
| `routers/ontology.py` | Ontology API | `MOVE` | `app/ontology` | #55 |
| `routers/predictive_maintenance_runtime.py` | Prediction read/replay API | `SPLIT` | Diagnosis read/runtime과 외부 Overlay control 계약 분리 | #58 |
| `routers/manufacturing.py` | Equipment, Event, Evidence, Report, Decision API 혼재 | `SPLIT` | `equipment`, `maintenance`, `report`, `dashboard`/composition | #56, #59~#61 |
| `routers/dashboards.py` | Dashboard API | `MOVE` | `app/dashboard` | #60 |
| `routers/exports.py` | Export API | `MOVE` | `app/report` | #61 |
| `routers/planner.py`, `routers/agent.py` | Planner와 Agent API | `SPLIT` | Planner는 이관, Agent orchestration은 #68 결정 후 처리 | #62, #68 |
| `routers/governance.py` | Governance API | `MOVE` | `app/governance` | #63 |
| `routers/admin.py`, `routers/role_workspaces.py` | Identity, Dashboard, Governance, Maintenance API 혼재 | `SPLIT` | endpoint별 의미 소유 도메인으로 분해 | #53, #59, #60, #63 |
| `routers/project3.py` | Project 3 passthrough API | `DEFER`/`SPLIT` | 유지 시 external adapter와 consumer port로 분리 | #52, #55, #62, #68 |
| `routers/platform.py` | 31개 Platform capability API 집합 | `DEFER`/`SPLIT` | endpoint별 consumer와 제품 근거를 #68에서 판정 | #52, #63, #68 |
| `routers/system.py` | health와 polyglot health | `SPLIT` | 표준 health는 composition/Infra, polyglot은 #68 판정 | #52, #64, #68 |
| `routers/analyses.py` | Analysis API | `DEFER` | `analysis_*` 결정과 함께 처리 | #68 |
| `routers/modeling.py` | Backend 학습/실험/registry API | `DEFER`/`SPLIT` | Runtime·governance 최소 기능 외에는 Generator 소유권과 비교 후 제거 | #58, #63, #68 |
| `routers/__init__.py` | 기술 중심 Router package export | `REPLACE` | 각 도메인 Router와 `app/main.py` 등록으로 대체 | #64 |

## 4. Phase별 적용 규칙

1. 각 Phase PR은 자기 Source 행의 세부 파일 목록과 최종 처분을 PR 본문에 기록한다.
2. `SPLIT`은 각 책임의 새 owner와 public port를 확인한 뒤 레거시 Source를 삭제한다.
3. `REPLACE`는 새 구현의 회귀 테스트와 deployment entrypoint가 통과한 뒤 삭제한다.
4. `REMOVE`는 삭제되는 API/테스트/문서 참조를 함께 정리한다.
5. `DEFER`는 임의 target으로 옮기지 않는다. #68 결정 전에는 Phase 이슈의 DoD를 닫을 수 없다.
6. Phase 14(#65)는 Ledger의 미배정 Source, `UNDECIDED`, `DEFER`가 모두 0건일 때만 시작한다.

## 5. Architecture CI Ratchet

- Phase 0~13: 레거시 존재 자체는 허용하되 신규 레거시 파일 및 신규 레거시 import 증가를 금지한다.
- 각 Phase: 이미 이관 완료로 선언한 Source의 재생성과 `app`에서 레거시로 향하는 신규 import를 금지한다.
- Phase 14: `systems/backend/ontology_dashboard`와 모든 import/실행 참조가 0건인지 검사한다.
- Phase 15: 최종 strict invariant를 유지하고 이후 회귀를 차단한다.

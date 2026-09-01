# Backend Runtime, Evidence, and Agent Review Boundary

상태: 팀 공유용 경계 문서
기준: PR #156 작성 시점, 2026-09-01
범위: MVP Workflow, Product Result/Evidence 소비 경계, Agent Review, Closed-loop 입력 보호

이 문서는 Predictive Maintenance MVP에서 예측 결과가 업무 화면, 리포트, AI 검토, Closed-loop 흐름으로
전달될 때 지켜야 하는 팀 기준을 정리한다. 개인 기여 증빙이 아니라 팀이 함께 유지해야 하는 제품/기술
경계 문서다.

## 1. 핵심 원칙

예측 모델의 raw output은 UI, Report, Agent Review, Closed-loop가 직접 소비하지 않는다.

```text
Generator raw output
  -> Backend Runtime Diagnosis validation / promotion
  -> Product Result Artifact / Evidence Projection
  -> AssetDetailViewModel / Report / Agent Review Packet
  -> Human review / Closed-loop RecommendationInput
```

팀 기준은 다음과 같다.

- Generator는 runtime prediction batch와 model artifact를 생산한다.
- Backend Runtime Diagnosis는 batch를 검증하고 Product Result/Evidence로 승격한다.
- UI와 Report는 raw payload를 재조합하지 않고 typed ViewModel 또는 projection을 소비한다.
- Agent Review는 검증된 Evidence Packet을 읽는 read-only 설명 계층이다.
- Closed-loop mutation은 AI Summary나 client view state가 아니라 서버가 구성한 입력 계약으로 보호한다.
- 누락, stale, lineage mismatch가 있는 근거는 정상값으로 합성하지 않고 gap, warning, limitation으로 드러낸다.

## 2. 책임 경계

| 영역 | 책임 | 금지할 혼동 |
| --- | --- | --- |
| Generator | source data에서 feature/model/runtime prediction batch를 만든다. | raw prediction을 Product Result, Evidence, Recommendation으로 직접 간주하지 않는다. |
| Backend Runtime Diagnosis | prediction batch를 검증하고 Product Result Artifact와 Evidence Projection으로 승격한다. | validation 없이 UI/Closed-loop로 전달하지 않는다. |
| AssetDetailViewModel | 화면이 소비할 read model을 구성한다. | frontend가 raw JSONL, fixture, producer payload를 직접 join하지 않는다. |
| Report | Evidence와 projection을 기반으로 사람이 읽는 문장을 만든다. | unavailable context를 정상값이나 확정 원인처럼 채우지 않는다. |
| Agent Review | Agent Review Packet을 읽고 risk, evidence, limitation, next review point를 설명한다. | WorkOrder 생성, 승인, 상태 변경 권한을 갖지 않는다. |
| Closed-loop | recommendation decision, work order, inspection, maintenance action/event, equipment state를 소유한다. | AI Summary나 오래된 화면 snapshot을 mutation 권한 근거로 사용하지 않는다. |

## 3. DB 조회와 Snapshot Guard 전략

Closed-loop mutation에 필요한 입력은 클라이언트가 들고 온 화면 상태를 그대로 신뢰하지 않는다. 서버가
현재 Event Evidence Projection을 조회해 `RecommendationInput`을 구성하고, caller가 본
`snapshot_basis`와 서버 조회 결과의 basis를 비교한다.

기본 정책은 다음과 같다.

- `snapshot_basis`가 일치하면 같은 evidence 기준으로 사용자가 판단했다고 본다.
- mismatch가 감지되면 projection이 일시적으로 stale할 가능성을 고려해 1회 재조회한다.
- 재조회 후에도 mismatch가 남으면 WorkOrder 같은 side effect 없이 요청을 거부한다.
- mutation 입력에는 asset/event/evidence/product result/source hash 같은 lineage 기준이 포함되어야 한다.
- stale 상태는 숨기지 않고 명시적 오류 또는 gap으로 드러낸다.

상세 DB 테이블 구조는 [Workflow and Closed-loop DB Diagram](../schema/db-diagram.md)을 따른다.

## 4. Agent Review 저장/재사용 전략

Agent Review Summary는 매번 UI 조회 시 생성하지 않는다. 저장본 lookup과 명시적 materialization을
분리한다.

| 전략 | 내용 |
| --- | --- |
| 저장 key | `summary_key`는 asset, event, dataset, snapshot/source hash, context hash, prompt/schema/model version을 기준으로 만든다. |
| GET lookup | GET 계열 조회는 저장본이 있으면 반환하고, 없으면 pending/null 상태를 반환한다. 조회 자체가 LLM 생성을 트리거하지 않는다. |
| POST / watcher | 명시적 생성 API 또는 watcher가 Summary materialization을 담당한다. |
| 재사용 | 같은 `summary_key`가 있으면 UI와 Report는 저장본을 재사용한다. |
| fallback | LLM provider 부재 또는 validation 실패 시 deterministic fallback도 같은 저장 계약으로 남긴다. |
| stale recovery | 오래 남은 running reservation은 bounded policy로 만료/회복시켜 같은 key의 후속 생성을 막지 않는다. |

이 전략은 LLM 비용을 줄이기 위한 단순 캐시가 아니라, 같은 evidence snapshot에 같은 설명 근거를 연결하기
위한 재현성/감사 전략이다.

## 5. 팀에서 지켜야 할 변경 규칙

| 변경 유형 | 체크 기준 |
| --- | --- |
| Product Result/Evidence schema 변경 | producer, backend, UI/report, Agent Review consumer, tests를 함께 확인한다. |
| ViewModel 필드 추가 | source reference와 unavailable/gap 표현을 같이 설계한다. |
| Agent Review prompt/schema 변경 | packet field grounding, summary validation, fallback, stored lookup 영향을 확인한다. |
| Closed-loop mutation 추가 | `RecommendationInput`, authorization, idempotency, snapshot guard, side-effect 없음 테스트를 확인한다. |
| DB table/migration 추가 | SQLite와 PostgreSQL 경로, RLS/scope, audit/read model 소비 경로를 분리해 확인한다. |
| Cache/materialization 확장 | cache hit, concurrent miss, stale recovery, invalidation 또는 outbox event 필요성을 테스트로 고정한다. |

## 6. 상세 문서 링크

| 문서 | 역할 |
| --- | --- |
| [ADR-004: Product Result / Evidence / ViewModel 신뢰 경계](../architecture-decisions/ADR-004-product-result-evidence-viewmodel-trust-boundary.md) | Product Result, Evidence, ViewModel, Agent Review, Closed-loop snapshot guard의 설계 결정과 후속 materialization 후보를 정리한다. |
| [ADR-003: Generator Runtime Prediction Result 및 Backend Decision 소유권](../architecture-decisions/ADR-003-generator-runtime-prediction-result-and-backend-decision-ownership.md) | Generator output과 Backend decision ownership의 기본 경계를 설명한다. |
| [Workflow and Closed-loop DB Diagram](../schema/db-diagram.md) | Workflow 화면과 Closed-loop가 사용하는 주요 DB 테이블, 관계, 저장 위치를 Mermaid ERD로 정리한다. |
| [AI Context Orchestration Adapter Plan](../plans/ai-workflow/2026-08-29-001-ai-context-orchestration-adapter-plan.md) | Agent Review context adapter와 evidence packet 구성 방향을 설명한다. |
| [Product Result / Evidence 신뢰 경계 구현 계획](../plans/ai-workflow/2026-08-29-002-product-result-evidence-materialization-plan.md) | Product Result/Evidence materialization 계획과 구현 전 확인 항목을 정리한다. |
| [Evidence Snapshot Consistency Guard 계획](../plans/ai-workflow/2026-08-29-003-evidence-snapshot-consistency-guard-plan.md) | UI, Agent Review, Closed-loop가 같은 Evidence basis를 공유하는 guard 전략을 정리한다. |
| [Backend Runtime / Evidence Delivery Contribution](../contributions/hb-backend-runtime-evidence.md) | Backend Runtime Diagnosis와 Evidence 전달 경계의 개인 기여 근거를 요약한다. |
| [AI Review / Evidence Boundary Contribution](../contributions/hb-ai-review-evidence.md) | Agent Review read-only 경계와 summary materialization 기여 근거를 요약한다. |

## 7. 관련 PR

| PR | 역할 |
| --- | --- |
| [#107](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/107) | `AssetDetailViewModel` API를 MVP E2E 흐름에 연결했다. |
| [#130](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/130) | SOP fixture 기반 점검 안내를 read-only grounding으로 분리했다. |
| [#133](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/133) | SOP Grounding 소비 계약과 Closed-loop 비권한 경계를 제안했다. |
| [#135](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/135) | Prediction Result Inbox 수신부를 구현했다. |
| [#140](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/140) | Prediction Batch 수신부를 Product Result 승격까지 연결했다. |
| [#150](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/150) | Agent Review Packet/Summary 기반 read-only AI 검토 워크플로우를 추가했다. |
| [#156](https://github.com/Biz-CollabCraft/ontology_dashboard/pull/156) | `RecommendationInput` snapshot guard와 Workflow/Closed-loop DB diagram을 추가했다. 2026-09-01 기준 open PR이다. |

## 8. 표현 범위

- 이 문서는 팀 기준 문서이므로 개인 성과를 강조하지 않는다.
- PR #156은 2026-09-01 기준 open 상태이므로 merged 완료로 표현하지 않는다.
- Closed-loop mutation/state-machine 전체 소유권은 Closed-loop 도메인 흐름에 두고, 이 문서는 Evidence 기반 입력 보호와 AI read-only 경계에 집중한다.
- 검색 인덱스, report cache invalidation, outbox event 같은 확장 materialization은 현재 기준 후속 후보로 분리한다.

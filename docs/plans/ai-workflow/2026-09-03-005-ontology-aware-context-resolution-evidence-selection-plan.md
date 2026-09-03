---
title: Ontology-aware Context Resolution and Evidence Selection Plan
type: feat
status: planned
date: 2026-09-03
---

# Ontology-aware Context Resolution and Evidence Selection Plan

## Summary

이 문서는 확장된 제조 운영 맥락에서 Agent Review Summary에 전달할 context를 **Ontology-aware Context Resolution**으로 먼저 구성하고, 그 결과에서 필요한 근거를 빠짐없이 유지하면서 불필요한 근거만 줄이는 **deterministic Evidence Selection** 구현 계획을 고정한다.

목표는 Evidence Selection 알고리즘을 독립 실험으로 키우는 것이 아니라, 이미 확장된 운영 도메인 관계를 AI context retrieval에 실제로 사용하는 것이다.

```text
Fixed request identity
  -> Evidence Snapshot / Product Result
  -> ontology relation traversal
  -> domain context resolver
  -> freshness / as-of eligibility
  -> evidence candidates
  -> deterministic selection
  -> Agent Review Packet
  -> LLM expression
  -> deterministic validation
  -> persisted summary / ViewModel
```

LLM은 이 흐름 이후에도 risk grading, recommendation ownership, authorization, WorkOrder/command mutation을 소유하지 않는다. Context resolution과 selection은 읽기 전용 설명 입력을 정리하는 책임만 가진다.

## Related Plan Boundary

같은 내용을 여러 문서에 반복하지 않기 위해 책임을 다음처럼 나눈다.

| 문서 | 정본 책임 | 이 문서와의 관계 |
|---|---|---|
| `2026-09-02-002-operational-domain-extension-plan.md` | Production/WIP, Maintenance, Part, Technician, Quality/Delivery domain 확장과 Relation Resolver/Impact Simulation 구현 범위 | 이 문서는 해당 확장 결과를 selection 입력으로 사용한다. 도메인 schema와 구현 상세를 중복하지 않는다. |
| `2026-09-02-001-agent-workflow-final-evaluation-plan.md` | frozen candidate의 LLM 품질, B1/B2/B3, reliability, safety 최종 평가 순서와 통합 리포트 | 이 문서는 final evaluation 전에 고정할 context/selection strategy와 최소 selection metric만 정의한다. |
| 이 문서 | 관계 기반 context resolution, freshness/as-of eligibility, deterministic evidence candidate selection, lineage trace, S0/S1 최소 비교 | assisted ranking, GraphRAG, multi-agent는 기본 구현 범위가 아니라 deferred hypothesis다. |

## Why Now

운영 도메인 확장 이후 같은 설비 사건에 연결되는 근거 후보가 늘어난다. 모든 context를 그대로 LLM에 전달하면 다음 문제가 생길 수 있다.

1. 필요한 근거가 불필요한 context 사이에 묻힌다.
2. stale, missing, not-connected context가 정상 fact처럼 보일 수 있다.
3. 역할별로 필요한 근거 차이가 Agent Review Summary에서 흐려진다.
4. prompt token, latency, cost가 증가한다.

따라서 지금 필요한 확장은 새로운 자율 agent가 아니라, **관계로 필요한 context를 찾고 시간적으로 유효한 근거만 선택하는 결정론적 입력 구성 단계**다.

## Scope Boundary

### Must

- relation-aware context resolution
- freshness / as-of / version eligibility filter
- deterministic evidence candidate projection
- deterministic S1 selection
- selected/rejected/gap reason trace
- `source_ref`, `source_version`, `as_of`, `snapshot_id` 또는 equivalent lineage 보존
- S0 Full Context baseline과 S1 Deterministic Selection의 최소 비교
- Required Evidence Recall 측정
- context/token reduction 측정

### Deferred

- semantic ranking
- LLM-assisted ranking
- vector retrieval
- GraphRAG
- multi-agent planner
- LangGraph production dependency
- autonomous tool planning 확대
- selection 결과를 근거로 한 Closed-loop mutation

S2 assisted ranking은 S1 구현과 최종 평가 gate가 끝난 뒤에만 별도 실험 가설로 검토한다.

## Design Principles

### 1. Resolver before selector

Selection은 임의의 후보 목록을 줄이는 단계가 아니다. 먼저 request identity와 ontology relation을 기준으로 필요한 domain context 후보를 resolve해야 한다.

```text
asset/event identity
  -> related product result
  -> related evidence snapshot
  -> related production order / WIP / lot
  -> related maintenance window / action / part / technician
  -> related quality hold / delivery commitment
```

이 relation traversal은 기존 Relation Resolver와 domain read-only port의 책임을 재사용한다.

### 2. Eligibility before ranking

freshness, scope, snapshot, version, as-of가 맞지 않는 context는 ranking 전에 정상 fact 후보에서 제외한다. 단, stale/missing/not-connected 상태 자체가 판단에 필요한 경우에는 limitation candidate로 보존한다.

### 3. Selection is not truth generation

원본 Evidence Snapshot, Product Result, Operational Context가 source of truth다. Selector는 이미 존재하는 후보 중 현재 Agent Review 목적에 필요한 subset을 고르는 책임만 가진다.

### 4. Lineage must survive reduction

모든 selected item과 rejected/gap reason은 원래 source로 역추적 가능해야 한다. Token을 줄였다는 이유로 `source_ref`, `version`, `as_of`, limitation을 잃으면 실패다.

## Target Pipeline

### Step 1. Relation-aware context resolution

입력 identity:

```text
organization_id
project_id
workspace_id
asset_id
evidence_snapshot_id
decision_as_of
role
summary_intent
```

Resolver는 기존 도메인 확장 계획의 read-only port와 relation resolver를 사용해 필요한 context만 가져온다.

- Product Result / Evidence Snapshot
- Production Order / WIP / Alternative Capacity
- Maintenance Window
- MaintenanceActionCandidate / PartRequirement
- Part Readiness / InventorySnapshot
- Technician / Skill Readiness
- Quality Lot / Delivery Commitment
- Impact Simulation result, if already calculable

불필요한 domain fan-out은 피한다. resolver가 context를 찾지 못한 경우 값 합성 대신 gap 또는 limitation을 남긴다.

### Step 2. Candidate projection

Resolved context를 selection/evaluation용 공통 candidate로 projection한다. 이 shape은 새로운 domain truth schema가 아니라 LLM 입력 구성과 평가를 위한 read model이다.

```text
candidate_id
source_ref
source_snapshot_id
source_version
domain
relation_path
fact_type
role_relevance
priority_hint
freshness_state
as_of
value_summary
required_for_boundary
limitation_state
```

### Step 3. Hard eligibility filter

다음은 ranking 전에 deterministic하게 처리한다.

- wrong organization/project/workspace/asset 제거
- wrong evidence snapshot 제거
- version/as-of mismatch 제거 또는 limitation candidate로 분리
- stale context를 정상 fact로 승격하지 않음
- missing/not-connected/unavailable context를 0, 정상, 가능 상태로 합성하지 않음
- malformed external context 제외
- forbidden/unsupported source 제외
- must-include boundary evidence는 selection budget과 무관하게 유지

### Step 4. S0/S1 strategies

#### S0 — Full Context baseline

eligibility filter를 통과한 모든 candidate와 필요한 limitation candidate를 Agent Review Packet에 전달한다.

목적은 도메인 확장 이후 full context의 품질, grounding, token 비용 기준선을 만드는 것이다.

#### S1 — Deterministic Selection

도메인 규칙, relation distance, role relevance, event directness, freshness, explicit priority를 사용해 정렬하고 budget 내에서 선택한다.

우선순위 예시:

```text
must_include boundary / limitation
> direct Product Result and Evidence Snapshot fact
> current event direct evidence
> top factor / sensor evidence
> Impact Simulation prerequisite or blocker
> role-relevant operational context
> recent maintenance / history
> secondary contextual evidence
```

S1이 기본 구현 대상이다. 재현 가능해야 하며 selection 자체가 새로운 LLM 불확실성을 만들지 않아야 한다.

### Deferred S2 — Assisted Ranking

S2는 이 문서의 필수 구현 범위가 아니다. S1이 required evidence recall, limitation preservation, grounding, authority boundary를 통과한 뒤에도 context reduction이 부족하거나 역할별 usefulness가 부족할 때만 별도 실험으로 검토한다.

검토하더라도 제약은 다음과 같다.

- hard eligibility filter 이후 candidate에만 적용
- 새로운 fact 생성 금지
- candidate id만 reorder/select
- bounded candidate count
- selection failure 시 S1 fallback
- selected ids와 score/reason trace 저장

S2는 S1보다 최종 품질 또는 비용 효율이 실제로 개선될 때만 채택한다.

## Minimal Evaluation

최종 평가 체계는 `2026-09-02-001-agent-workflow-final-evaluation-plan.md`가 소유한다. 이 문서는 selection strategy freeze 전에 필요한 최소 비교만 정의한다.

### Dataset

기존 8-case Agent Review gold set을 버리지 않고 annotation만 추가한다.

```text
required_evidence_ids
acceptable_optional_evidence_ids
required_limitation_ids
role_required_evidence:
  field_operator: [...]
  process_manager: [...]
```

확장 도메인 case가 부족하면 최소 fixture만 보강한다.

- 생산/WIP 영향이 핵심인 case
- spare part/technician readiness가 필요한 maintenance case
- quality/lot/delivery 영향 case
- stale 또는 not-connected context가 섞인 case

### Required metrics

#### Required Evidence Recall

```text
selected required evidence / gold required evidence
```

필요한 근거를 누락하는 selector는 실패다.

#### Required Limitation Preservation

stale/missing/not-connected/gap이 판단에 필요한 case에서 limitation candidate가 유지되는 비율이다.

#### Context Reduction

```text
1 - selected candidate count / full eligible candidate count
```

#### Prompt Token Reduction

```text
1 - S1 prompt token count / S0 prompt token count
```

token을 직접 측정하지 못하면 prompt bytes를 보조 지표로 기록하고 measurement basis를 명시한다.

### Quality guard

S1이 context를 줄이더라도 기존 Runner 1의 최종 answer quality gate는 유지한다.

- `accuracy_goldset_score`
- contract acceptance
- grounding rate
- must-not-claim / authority boundary violations
- role usefulness
- Korean field-language quality

Selection metric이 좋아도 final answer 품질이 S0 대비 하락하면 채택하지 않는다.

## Acceptance Criteria

S1 채택 기준:

- required evidence recall = 1.0
- required limitation preservation = 1.0
- snapshot/version/as-of boundary violation = 0
- lineage completeness = 1.0
- final `accuracy_goldset_score`가 S0보다 하락하지 않음
- grounding hard gate 유지
- authority/mutation boundary violation = 0
- selected candidate count 또는 prompt token이 S0 대비 감소

통과하지 못하면 selection budget이나 deterministic priority를 조정한다. S2 assisted ranking으로 즉시 건너뛰지 않는다.

## Implementation Order

### Phase 0 — Freeze input contracts

- 운영 도메인 확장 candidate와 관련 schema/version 확인
- 기존 final evaluation plan과 실행 순서 충돌 여부 확인
- selection strategy가 참조할 relation/domain/source metadata 확정

### Phase 1 — Gold evidence annotation

- 기존 gold case에 required/optional/limitation evidence annotation 추가
- role-specific required evidence 명시
- 확장 도메인 최소 fixture 보강

### Phase 2 — Resolver and candidate projection

- relation-aware context resolution entrypoint 구현
- 기존 Relation Resolver와 read-only domain port 재사용
- resolved context를 candidate projection으로 변환
- lineage, relation path, freshness/as-of metadata 보존
- gap/not-connected/stale 상태를 limitation candidate로 projection

### Phase 3 — Deterministic eligibility and selection

- hard eligibility filter 구현
- S0 Full Context baseline 구현
- S1 deterministic selector 구현
- selected/rejected/gap reason trace 기록
- unit/contract tests 추가

### Phase 4 — Minimal comparison harness

- 동일 case에서 S0/S1 실행
- required evidence recall과 limitation preservation 계산
- context/token reduction 계산
- 기존 LLM quality runner와 연결 가능한 artifact 생성

### Phase 5 — Final evaluation handoff

- S1 strategy와 measurement artifact를 final evaluation candidate metadata에 연결
- `2026-09-02-001-agent-workflow-final-evaluation-plan.md`의 frozen candidate 평가에 포함
- 확장 후 provider/model 재평가는 final evaluation plan의 순서와 기준을 따른다

## Stop Rule

다음 조건을 만족하면 더 복잡한 retrieval/agent 기술을 추가하지 않는다.

- S1 required evidence recall과 limitation preservation가 1.0
- lineage와 temporal boundary가 모두 보존됨
- final answer quality가 S0 대비 유지
- context/token 감소가 확인됨
- final evaluation gate에 selection strategy가 포함됨

이 시점에서 GraphRAG, vector retrieval, multi-agent, S2 assisted ranking은 현재 문제 해결에 필요한 기본 구조가 아니라 별도 확장 가설로 남긴다.

# Asset Criticality Modeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `AssetDetailViewModel`에서 설비 중요도를 예측 위험도와 분리된 제조 운영 맥락으로 모델링하고, 결측/출처/우선순위 의미를 schema와 composer 테스트로 고정한다.

**Architecture:** 현재 규모에서는 별도 graph DB나 full digital twin을 만들지 않는다. `asset.criticality`를 설비 마스터/프로젝션에서 온 운영 영향도 필드로 두고, `risk.status_grade`는 모델 위험도, `priority`는 risk와 criticality를 조합한 표시/정렬 파생값으로 분리한다. 온톨로지 관계는 문서와 typed reference 수준으로 고정하고, 생산 API endpoint와 frontend 전면 연결은 후속 slice로 둔다.

**Tech Stack:** Python 3, pytest, jsonschema, existing `systems/backend/app/report` composer, existing `systems/backend/app/diagnosis/recommendation_policy.py` policy contract.

---

## Final Narrative Frame

예지보전 리포트에서는 같은 시점의 같은 설비 판단을 설명하는 snapshot 정합성이 중요하다.
이번 모델링 판단의 기준점은 "데이터를 많이 보여주는가"가 아니라 "리포트가 보여주는
risk, criticality, evidence, history가 같은 판단 시점과 같은 source boundary에서 온
것이라고 말할 수 있는가"다.

### Problem Baseline

현재 `AssetDetailViewModel`은 Product Result Artifact, Evidence Payload,
Observation series, runtime prediction history, Activity/Maintenance source를 한 화면에
병합해야 한다. 이 데이터들은 owner와 freshness가 서로 다르다. 따라서 프론트엔드가 여러
API를 호출해 직접 조립하면 다음 판단이 화면별로 갈라질 수 있다.

- `risk.status_grade`는 모델/근거 기반 고장 위험도다.
- `asset.criticality`는 고장 발생 시 제조 운영 영향도다.
- `data_status.is_data_quality_hold`는 위험도가 아니라 데이터 품질 때문에 판단을 보류한 상태다.
- `risk_series`, `features[].series`, `equipment_history`는 단일 Event Evidence만으로 항상 채워지지 않는다.

### Observed Symptoms

PR100 검토에서 드러난 실제 현상은 단순 schema typo가 아니라 projection 책임이 흔들린
증상으로 본다.

- `data_quality_hold`가 risk grade처럼 취급될 수 있었다.
- `is_stale=false`가 authoritative freshness fact 없이 생성될 수 있었다.
- `top_factor.evidence_field_id`가 schema optional string인데 `null`로 방출될 수 있었다.
- `risk_prediction_results`처럼 내부 저장/조회 형태가 public contract naming으로 새어 나왔다.
- `criticality`가 없을 때 default를 만들면 추천 우선순위와 리포트 해석이 사실처럼 보일 수 있다.

### Cause Exploration

ai-dev 관점에서 원인을 여러 기준으로 다시 본 결과, 핵심 원인은 ViewModel을 단순 편의
응답 DTO로 본 데 있다. 이 객체는 화면 payload 이전에 projection contract다.

- Data modeling 기준: producer fact, asset context, derived priority, data quality state가 분리되지 않으면 위험도와 운영 영향도가 섞인다.
- Manufacturing 기준: 중요도는 설비 고장 확률이 아니라 라인 중단, 품질 손실, 안전/환경, 복구 난이도 같은 운영 영향이다.
- Ontology 기준: `Asset`, `Observation`, `ProductResultArtifact`, `EvidencePackage`, `MaintenanceRecord`의 관계는 보존되어야 하며, relation을 잃은 화면 조립값은 provenance가 약하다.
- API contract 기준: consumer가 raw source를 직접 읽거나 fallback을 합성하면 source truth가 화면 레이어로 이동한다.
- Review 기준: PR100 코멘트의 null/freshness/naming 문제는 모두 "없는 사실을 어떻게 표현할지"가 중앙에서 고정되지 않은 데서 반복된다.

### Alternative Exploration

| Alternative | Why considered | Tradeoff | Priority decision |
|---|---|---|---|
| Frontend composes multiple APIs | UI에서 빠르게 조립 가능 | snapshot 정합성, gap, freshness, criticality 해석이 화면별로 분산됨 | Lower |
| Expand generic `/objects`, `/observations`, `/maintenance` APIs first | 재사용 가능한 product API가 됨 | 리포트 전용 판단 시점과 evidence boundary를 보장하기 어려움 | Lower for this slice |
| Extend Event Evidence only | 변경량이 작음 | 시계열, runtime history, maintenance history를 단일 Evidence로 설명할 수 없음 | Lower |
| Build ontology/graph layer first | 장기적으로 관계 질의가 유리함 | 현재 규모 대비 과하고 PR95/100의 즉시 문제를 해결하지 못함 | Defer |
| Single `AssetDetailViewModel` API | snapshot, source, gap, quality state를 한 계약에서 통제 가능 | backend adapter 책임 증가 | Preferred |

### Proposed Framing

따라서 제안은 "단일 ViewModel API로 화면을 편하게 만든다"가 아니다. 제안은
"예지보전 리포트의 snapshot 정합성과 evidence boundary를 보장하기 위해 backend-owned
`AssetDetailViewModel` projection을 먼저 고정한다"다.

이 프레이밍에서 `criticality`는 다음처럼 들어간다.

```text
risk = 모델이 판단한 고장 가능성/등급
criticality = 제조 운영에서의 설비 영향도
priority = risk와 criticality를 조합한 workflow/display 파생값
```

### Action Path

1. PR100 코멘트에서 확인된 contract correctness 문제를 먼저 수정한다.
2. `asset.criticality`, `criticality_basis`, `criticality_source`를 schema/docs에 추가한다.
3. composer가 criticality를 보존하되, 결측 시 default를 만들지 않도록 한다.
4. missing criticality, freshness unknown, data-quality hold, nullable optional field를 contract test로 고정한다.
5. production endpoint와 frontend 전환은 다음 slice에서 진행한다.

### Result, Lesson, Prevention Notes

Draft to resolve:

- Result: 어떤 테스트/문서/코드 수정이 완료됐고 어떤 증거 수준까지 확보했는가?
- Lesson: 이번 건에서 "ViewModel은 DTO가 아니라 projection contract"라는 교훈을 어떻게 표현할 것인가?
- Prevention: 다음 PR에서 같은 실수를 막기 위해 PR checklist, schema assertion, naming rule 중 무엇을 추가할 것인가?
- Prevention candidate: "새 ViewModel 필드는 source, missing behavior, owner_domain, consumer fallback 금지 여부를 문서/테스트에 같이 추가한다."

---

## Scope

In scope:
- `AssetDetailViewModel` schema에 `asset.criticality` 의미와 출처를 명시한다.
- 중요도 결측을 임의 기본값으로 채우지 않고 `evidence.gaps[]` 또는 `data_status.warnings[]`로 표현한다.
- `risk`, `criticality`, `priority`의 의미를 문서에서 분리한다.
- PR100 코멘트에서 확인된 naming/null/freshness 문제와 충돌하지 않도록 계획에 반영한다.

Out of scope:
- 설비 중요도 자동 산정 모델, RPN, 비용 최적화 모델.
- graph DB, OWL/RDF 전체 온톨로지 구현.
- 실제 production endpoint, frontend ViewModel 소비, PostgreSQL E2E.

---

## Data Modeling Decisions

### D1. Criticality is asset context, not risk

`criticality`는 고장 가능성이 아니라 고장 발생 시 운영 영향도다.

- Allowed values: `low`, `medium`, `high`
- Source: asset/equipment master, fixture projection, or explicit read-port field
- Missing behavior: do not default to `medium`
- Consumer use: recommendation/priority context, not model status replacement

Directional contract:

```text
risk.status_grade = model/evidence-derived failure risk
asset.criticality = business/operations impact if the asset fails
priority = display or workflow ordering derived from risk + criticality
```

### D2. Start with manual/rule-based criticality

Current scale does not justify an automated importance model. Treat criticality as a manually curated or fixture-projected enum with reason codes.

Minimal fields:

```text
criticality: low | medium | high | null
criticality_basis: string[]
criticality_source: manual_initial_assessment | equipment_master | fixture_projection | unknown
```

`criticality_basis` examples:
- `line_stop_risk`
- `quality_sensitive`
- `safety_or_environment_risk`
- `long_repair_time`
- `spare_part_dependency`

### D3. Ontology stays as typed relationships

Represent the ontology in documentation and stable references first:

```text
Asset HAS_OBSERVATION Observation
Observation INPUT_TO ProductResultArtifact
ProductResultArtifact HAS_EVIDENCE EvidencePackage
ProductResultArtifact HAS_PRIORITY_CONTEXT AssetCriticality
EvidencePackage SUPPORTS Recommendation
Recommendation MAY_CREATE Decision
Decision MAY_CREATE FieldTask
FieldTask MAY_PRODUCE MaintenanceRecord
```

No new graph storage is required for this slice.

---

## Tradeoffs

| Choice | Pros | Cons | Decision |
|---|---|---|---|
| Manual 3-level criticality | Fast, explainable, enough for MVP | Subjective, needs later calibration | Use now |
| Numeric score/RPN | Better ranking math later | Invents precision without data today | Defer |
| Criticality required string | Simple UI and sorting | Forces fake defaults when unknown | Use nullable or gap-aware handling |
| Full ontology/graph DB | Flexible relationship traversal | Too much infra and migration cost | Defer |
| Backend-composed priority | Consistent report semantics | Backend owns more projection logic | Use for report ViewModel later |
| Frontend-derived priority | Quick display change | Duplicates policy and hides missing evidence | Avoid for contract logic |

---

## Tasks

### Task 1: Document Criticality Semantics

**Files:**
- Modify: `docs/mvp/schema-definition.md`
- Modify: `docs/mvp/api-specification.md`
- Modify: `docs/closed-loop-domain-contract.md`

- [ ] **Step 1: Update `AssetDetailViewModel` field table**

Add `asset.criticality`, `asset.criticality_basis`, and `asset.criticality_source` to the Asset summary section. State that `criticality` is operational impact, not model risk.

- [ ] **Step 2: Add missing-value rule**

Document that missing criticality must not be defaulted to `medium`. Use `null`, `evidence.gaps[]`, and/or `data_status.warnings[]`.

- [ ] **Step 3: Update closed-loop wording**

Clarify that recommendation can use criticality as context, but missing criticality blocks executable recommendation or downgrades to review/hold depending on the existing policy.

- [ ] **Step 4: Review**

Verify docs consistently distinguish:
- model risk: `risk.status_grade`
- data quality: `data_status.is_data_quality_hold`
- asset impact: `asset.criticality`
- derived workflow/display ordering: `priority`

### Task 2: Extend ViewModel Schema

**Files:**
- Modify: `contracts/schemas/asset-detail-view-model.schema.json`
- Modify: `tests/fixtures/asset_detail_view_model/current-evidence-only.json`
- Modify: `tests/fixtures/asset_detail_view_model/observation-series-present.json`
- Modify: `tests/fixtures/asset_detail_view_model/risk-timeline-present.json`
- Modify: `tests/fixtures/asset_detail_view_model/baseline-partially-missing.json`
- Test: `tests/test_asset_detail_view_model_contract.py`

- [ ] **Step 1: Add schema fields**

Extend `asset` with:
- `criticality`: `low | medium | high | null`
- `criticality_basis`: string array
- `criticality_source`: enum allowing `manual_initial_assessment`, `equipment_master`, `fixture_projection`, `unknown`

- [ ] **Step 2: Keep schema closed**

Maintain `additionalProperties: false`. New fields must be explicit and fixture-backed.

- [ ] **Step 3: Add missing criticality fixture coverage**

Add or update one fixture where `criticality` is `null`, `criticality_source` is `unknown`, and an evidence gap explains the unavailable asset-impact context.

- [ ] **Step 4: Add contract assertions**

Test scenarios:
- schema accepts `high`, `medium`, `low`
- schema accepts `criticality: null`
- schema rejects unknown criticality values such as `standard`
- missing criticality fixture still validates when the gap is present
- `risk.status_grade` still does not include `data_quality_hold`

### Task 3: Update Composer Mapping

**Files:**
- Modify: `systems/backend/app/mvp/asset_detail_view_model.py`
- Test: `tests/test_asset_detail_view_model_composer.py`

- [ ] **Step 1: Read criticality from contracted asset/equipment input**

Composer should copy explicit `criticality`, `criticality_basis`, and `criticality_source` from the read-port data when available.

- [ ] **Step 2: Do not synthesize default criticality**

If no criticality exists, output `criticality: null`, `criticality_basis: []`, `criticality_source: "unknown"`, and append a gap such as:

```text
field = asset.criticality
reason = criticality_missing_or_unresolved
owner_domain = maintenance
```

- [ ] **Step 3: Keep recommendation policy ownership intact**

Composer must not reimplement `status x criticality` recommendation rules. It only exposes the asset context needed by downstream policy/report consumers.

- [ ] **Step 4: Add composer tests**

Test scenarios:
- explicit high criticality is preserved with basis/source
- missing criticality is not defaulted
- missing criticality adds a gap and warning
- `data_quality_hold` still maps to `risk.status_grade: null` and `data_status.is_data_quality_hold: true`

### Task 4: Align Existing PR100 Review Fixes

**Files:**
- Modify: `systems/backend/app/mvp/asset_detail_view_model.py`
- Modify: `contracts/schemas/asset-detail-view-model.schema.json`
- Test: `tests/test_asset_detail_view_model_composer.py`
- Test: `tests/test_asset_detail_view_model_contract.py`

- [ ] **Step 1: Rename internal read-port method**

Replace the public contract name `risk_prediction_results` with the semantic name `runtime_prediction_history`.

- [ ] **Step 2: Fix nullable top-factor field handling**

When `evidence_field_id` is unavailable, omit the field or allow nullable schema explicitly. Prefer omission if the field is optional.

- [ ] **Step 3: Fix data-quality hold consistency**

Use one helper/policy path for `status_grade == "data_quality_hold"` and legacy status fallback so `risk` and `data_status` cannot diverge.

- [ ] **Step 4: Fix freshness unknown handling**

Do not emit `is_stale: false` when freshness is unknown. Either allow `null` in schema or require an authoritative source. For this slice, prefer `boolean | null` plus a warning/gap.

### Task 5: Validation And Boundary Report

**Files:**
- Modify: `tests/test_report_domain_migration.py`
- Modify: `contracts/schemas/README.md`

- [ ] **Step 1: Keep report-domain import guard current**

Ensure the report composer remains in the canonical `systems/backend/app/report` package and does not import generator/prototype/infra modules directly.

- [ ] **Step 2: Update schema index**

Document that the ViewModel schema includes asset-impact context and missing-value semantics.

- [ ] **Step 3: Run focused verification**

Expected verification:
- contract fixture tests pass
- composer tests pass
- report-domain migration/import guard passes
- whitespace check passes

- [ ] **Step 4: Report evidence boundary**

Final report must state:
- implemented: schema/composer/docs/tests
- not implemented: production endpoint, production read-port, frontend consumption, PostgreSQL E2E
- criticality is operational context, not failure probability or model risk

---

## Suggested Delivery Order

1. Fix PR100 contract correctness issues first: naming, nullable top factor, hold consistency, freshness unknown.
2. Add criticality schema/docs after the contract is stable.
3. Update composer mapping and missing-criticality tests.
4. Run focused tests and produce a narrow PR summary.

This keeps the modeling improvement small enough to land in the current branch while avoiding a premature ontology platform.

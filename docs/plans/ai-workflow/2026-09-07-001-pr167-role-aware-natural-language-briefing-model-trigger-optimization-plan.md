# PR #167 기반 역할별 자연어 AI 브리핑·모델 비교·선제 생성 정책 최적화 계획

- 작성일: 2026-09-07
- 기준 PR: #167 `codex/standalone-factory-main`
- 기준 HEAD: `7d6d79f6abe4525005ff722aadc7b78b94f32fb7`
- 작업 브랜치: `codex/pr167-ai-briefing-optimization-plan`
- 범위: Decision Support 읽기 경로의 AI 브리핑 생성·평가·표현, 모델 비교, 생성 트리거 정책, 발표 문서 정합성
- 비범위: Closed-loop 승인/정비 실행 상태 전이, 생산 일정 자동 변경, WorkOrder 자동 생성, RAG/GraphRAG/멀티에이전트/fine-tuning 신규 도입

## 1. 문제 정의

현재 시스템의 목표 산출물은 사람이 읽고 판단에 사용할 수 있는 **자연어 브리핑**이다. 여러 제조 운영 근거를 단순 나열하거나 JSON 필드를 사용자에게 보여주는 것이 최종 목적이 아니다.

따라서 AI 경로의 역할은 다음과 같이 정의한다.

> 구조화된 Evidence/Operational Context를 동일 snapshot 기준으로 구성하고, LLM은 그 관계와 맥락을 자연스러운 한국어 브리핑으로 표현한다. 사실·시점·권한·source reference·실행 상태는 deterministic code가 통제하고, 자연어 문장만 LLM이 생성한다.

PR #167 기준으로 다음 두 문제가 추가로 남아 있다.

1. 역할별 화면은 `process_engineer`, `maintenance_technician`, `process_manager`로 분리되지만, 저장된 Agent Review Summary의 LLM 역할별 문장은 현재 `field_operator`, `process_manager` 두 역할만 직접 지원한다. 프론트도 `process_manager`만 전용 `role_summaries` quote를 우선 사용하고 나머지는 공통 `summary`로 내려간다.
2. watcher가 새로운 snapshot/context를 만날 때마다 선제 생성하는 방식은 최신 브리핑 제공에는 유리하지만, 사소한 변화까지 LLM 호출로 이어질 수 있다. 반대로 클릭 시에만 생성하면 비용은 가장 작지만 중요한 변화가 발생해도 사용자가 먼저 알아채고 요청해야 하며 조회 시 생성 latency를 직접 기다린다.

이번 확장의 연구 질문은 두 개로 제한한다.

- **RQ1. 중요한 운영 상태 변화에 대한 브리핑 최신성을 유지하면서 불필요한 LLM 선제 호출을 얼마나 줄일 수 있는가?**
- **RQ2. 실제 생성이 필요한 경우 동일 Evidence와 동일 평가 기준에서 품질 기준을 만족하면서 가장 비용·지연 효율적인 모델은 무엇인가?**

## 2. 현재 구현 근거와 Claim 상태

### 2.1 Verified: LLM의 실제 생성 대상은 자연어 prose다

현재 `AgentReviewSummaryProvider`는 provider에 JSON 응답 형식을 요구하지만 LLM이 편집할 수 있는 값은 다음으로 제한한다.

- `title`
- `summary`
- `role_summaries[*].quote`

`asset_id`, `generated_at`, `source_refs`, `inspection_focus`, `evidence_gaps`, `confidence_label`, `limitations` 등 구조적/근거 필드는 deterministic baseline에서 유지한 뒤 `_merge_llm_editable_fields()`가 자연어 필드만 덮어쓴다.

따라서 발표/문서에서 이를 단순히 `structured AI output`이라고 표현하면 최종 산출물의 성격을 잘못 전달할 수 있다. 정확한 표현은 다음이다.

> **검증 가능한 구조적 envelope 안에서 LLM은 사용자에게 보여줄 자연어 브리핑 prose만 생성한다.**

Evidence state: **Verified**  
Architecture fit: **Pass**

### 2.2 Verified: 현재 역할별 prose 계약은 2개 역할이다

현재 backend summary contract와 provider prompt가 직접 지원하는 역할은 다음이다.

- `field_operator`
- `process_manager`

프롬프트는 `field_operator`에게 현장 위치·증상 기록·handoff를, `process_manager`에게 생산 영향·승인 검토·라인/셀 sequencing implication을 강조한다.

Evidence state: **Verified**  
Architecture fit: **Pass for current contract**

### 2.3 Partially Verified: PR #167 역할 UI와 AI 역할별 prose가 완전히 일치하지 않는다

PR #167 standalone 역할 선택은 다음 3개를 사용한다.

- `process_engineer`
- `maintenance_technician`
- `process_manager`

`presentation.js`는 `process_manager`에서만 `role_summaries[process_manager].quote`를 우선하고, 나머지는 공통 `summary`를 사용한다. 따라서 화면의 역할 분리와 AI prose 분리는 현재 완전히 정렬되지 않았다.

Evidence state: **Partially Verified**  
Architecture fit: **Risk**

### 2.4 Verified: 동일 입력에 대한 저장 결과 재사용 기반은 이미 있다

현재 summary materialization은 snapshot/context hash, prompt/model/schema version 등을 summary identity에 포함하고 동일 `summary_key`의 저장 결과 재사용을 우선한다. PR #167의 공통 context read도 context fingerprint와 snapshot/as-of 경계를 보존한다.

Evidence state: **Verified**  
Architecture fit: **Pass**

## 3. 목표 상태

최종 AI 흐름은 다음으로 정리한다.

```text
Product Result / Evidence snapshot
        ↓
bounded operational context read
        ↓
Evidence selection / compact context
        ↓
role + briefing intent
        ↓
중요 변화 판단
   ├─ no material change → 검증된 저장 브리핑 재사용
   └─ material change    → 모델 선택 정책
                              ↓
                         LLM natural-language prose
                              ↓
                    grounding / time / claim validation
                              ↓
                     persisted Agent Review Summary
                              ↓
                     role-aware UI briefing
```

핵심 원칙은 다음과 같다.

1. **Input is structured, output prose is natural language.**
2. **Facts stay deterministic.** 숫자, ID, 시점, 관계, source truth는 LLM이 만들지 않는다.
3. **Role changes emphasis, not truth.** 역할이 달라도 동일 snapshot의 사실과 관계는 바뀌지 않는다.
4. **Material change controls pre-generation, not user permission.** 사용자의 명시적 refresh는 별도 on-demand 경로로 허용한다.
5. **Cost reduction is secondary to critical-change coverage.** 비용을 줄이기 위해 중요한 브리핑 갱신을 놓치지 않는다.

## 4. 역할별 자연어 브리핑 설계

### 4.1 PR #167 대상 역할

이번 계획의 제품 역할은 PR #167에 맞춰 세 개로 고정한다.

| 역할 | 브리핑에서 먼저 답할 질문 | 포함해야 할 맥락 | 금지 경계 |
|---|---|---|---|
| `process_engineer` | 지금 어떤 이상을 어디서 왜 확인해야 하는가? | 위험 신호, 모델 근거, 점검 위치, 유사 이력, 근거 공백 | 승인/정비 실행 결정, 생산 sequencing 결정 |
| `maintenance_technician` | 실제 점검·정비 준비에서 무엇을 확인해야 하는가? | 점검 항목, 정비 이력, 작업지시 상태, 부품/인력/정비 후보 시간, 승인 필요 여부 | 승인 완료·정비 시작/완료를 임의로 주장 |
| `process_manager` | 생산 영향과 승인/일정 판단에 무엇이 중요한가? | 생산 영향, 예상 차질 조건, 계획 정비 option, 작업 상태, 승인 검토 | 실제 손실·납기 보장·자동 승인 주장 |

`quality_auditor`는 이번 PR #167 standalone 3역할 범위에 포함하지 않는다. 품질 역할 전용 자연어 브리핑은 별도 consumer와 contract가 확정될 때 후속 확장한다.

### 4.2 공통 system prompt 원칙

역할마다 완전히 다른 system prompt를 만들지 않는다. 공통 grounding 규칙을 유지하고 role context만 바꾼다.

공통 규칙:

- `summary_context`에 있는 사실만 사용
- 여러 근거를 표처럼 나열하지 말고 관계와 운영 맥락을 자연스러운 한국어 문장으로 설명
- 현재 snapshot/as-of 이전·이후 정보를 섞지 않음
- 근거 없는 root cause, repair completion, actual loss, auto approval, work execution 주장 금지
- 불확실성과 evidence gap을 필요한 경우 문장 안에서 자연스럽게 명시
- 1~2개의 짧은 문장으로 현재 판단과 다음 확인 포인트를 전달
- 숫자를 쓸 때는 context에 실제 제공된 값만 사용
- synthetic/demo/planning assumption은 관측 사실처럼 표현하지 않음

### 4.3 역할 context 예시

```text
[System]
제조 운영 Decision Support용 자연어 브리핑을 작성한다.
제공된 근거 밖의 사실을 만들지 않는다.
구조적 필드는 변경하지 않고 자연어 prose만 작성한다.

[Role Context]
role = maintenance_technician
priority = 점검 위치 → 정비 이력 → 작업지시/승인 상태 → 준비 자원
forbidden = 승인 완료/정비 착수/교체 완료 단정

[Summary Context]
동일 snapshot의 selected evidence + operational context + history

[Task]
이 역할이 다음 판단을 빠르게 할 수 있도록 자연스러운 한국어 브리핑을 1~2문장으로 작성한다.
```

### 4.4 출력 계약 방향

최종 사용자 산출물은 자연어다. 다만 기존 persistence/API contract의 구조적 envelope는 유지한다.

새 generation 경로의 LLM editable surface는 계속 prose-only로 제한한다.

```json
{
  "title": "...",
  "summary": "...",
  "role_summaries": [
    {"role": "process_engineer", "quote": "..."},
    {"role": "maintenance_technician", "quote": "..."},
    {"role": "process_manager", "quote": "..."}
  ]
}
```

여기서 JSON은 provider transport/validation 형식이며 사용자에게 보여주려는 최종 표현 목적이 아니다. 실제 화면은 role별 `quote` 또는 공통 `summary` 자연어 문장을 사용한다.

## 5. Contract migration 계획

현재 `agent-review-summary-v1.0`은 `field_operator`, `process_manager`만 허용한다. PR #167 역할과 정렬하려면 계약 변경이 필요하다.

### 5.1 권장 migration

- 새 summary schema version을 발행한다. 예: `agent-review-summary-v1.1`.
- 신규 role enum에 `process_engineer`, `maintenance_technician`, `process_manager`를 명시한다.
- 기존 persisted `v1.0` summary는 read compatibility를 유지하거나 명시적 adapter를 통해 공통 summary로 degrade한다.
- 신규 generation은 새 prompt/schema version을 summary key에 포함해 이전 결과를 자동 재사용하지 않는다.
- `field_operator`는 기존 v1.0 read compatibility에만 남기고 신규 PR #167 역할 prose에는 사용하지 않는 방향을 우선 검토한다.

### 5.2 계약 확정 전 금지

- 기존 `agent-review-summary-v1.0` enum을 버전 변경 없이 조용히 수정하지 않는다.
- `process_engineer`를 `field_operator`와 동의어로 간주해 consumer에서 몰래 치환하지 않는다.
- maintenance/manager 역할 사실을 서로 다른 snapshot에서 조합하지 않는다.

## 6. 자연어 브리핑 품질 검증

구조화 필드 정확도를 최종 품질로 주장하지 않는다. 평가 대상은 자연어 브리핑이 근거와 역할 목적을 얼마나 정확히 반영하는가다.

### 6.1 Hard Gate

다음 위반은 점수와 무관하게 reject/fallback 대상이다.

- unknown `source_ref`
- asset/snapshot/as-of mismatch
- 금지 mutation field/claim
- 근거 없는 수치 생성
- synthetic/demo planning 값을 실제 관측값처럼 표현
- data-quality hold에서 확정 위험/생산 영향 주장
- 다른 역할이 소유한 승인/실행 결정을 이미 일어난 사실처럼 표현

### 6.2 Natural-language rubric

역할별 브리핑에 대해 다음을 분리 채점한다.

1. **Required fact coverage**: 해당 역할이 반드시 알아야 하는 근거를 빠뜨리지 않았는가
2. **Groundedness**: 모든 구체 주장과 숫자가 selected context에서 추적 가능한가
3. **Role usefulness**: 해당 역할의 다음 판단에 필요한 정보 우선순위가 맞는가
4. **Cross-role truth consistency**: 역할별 문장 사이의 사실·상태·숫자가 충돌하지 않는가
5. **Naturalness / concision**: 필드 나열이 아니라 읽기 쉬운 1~2문장 브리핑인가
6. **Uncertainty preservation**: 미연결·미확인·조건부 값을 과도하게 확정하지 않는가

단일 종합점수를 새로 만들지 않는다. 발표에서 하나의 `품질 점수`가 필요하면 기존 gold score를 사용하되, report에는 구성 지표를 함께 보존한다.

## 7. 모델 비교 계획

### 7.1 비교 목표

모델 비교는 "가장 똑똑한 모델"을 찾는 실험이 아니라 다음 기준을 만족하는 운영 모델을 고르는 실험이다.

> 동일한 Evidence Packet/context와 동일한 role prompt에서 품질 hard gate를 통과하고 gold 품질 기준을 만족하는 모델 중 latency와 비용 효율이 가장 좋은 모델을 선택한다.

### 7.2 비교 조건

- 후보 모델: 현재 모델 + 저비용 후보 + 상위 품질 후보, 최대 3개
- 동일 fixture/holdout
- 동일 selected context
- 동일 role/system prompt
- 동일 editable response contract
- 동일 generation temperature/parameter
- 동일 validator/rubric
- 실행 순서는 교차 또는 무작위화해 시간대/provider 변동 편향을 줄임

### 7.3 측정 지표

| 지표 | 정의 |
|---|---|
| Gold quality | 기존/확장 gold rubric 점수 |
| Required fact coverage | role별 필수 사실 반영률 |
| Hard-gate pass rate | 자연어 candidate가 validator를 직접 통과한 비율 |
| Forbidden/unsupported claim rate | 근거 없는 주장·금지 주장 비율 |
| p50 / p95 latency | provider generation latency |
| input/output tokens | provider reported usage 기준 |
| estimated cost | 실행 당시 모델 단가와 usage를 근거로 별도 산정 |

### 7.4 발표 시각화

발표에서는 모델 3개 × 3개 축의 grouped horizontal bar chart를 사용한다.

세 축은 모두 **높을수록 좋음**으로 방향을 통일한다.

- 품질: 기존 gold quality score 또는 0~100 환산
- 속도 효율: `min_latency / model_latency × 100`
- 비용 효율: `min_cost / model_cost × 100`

실제 원값은 각 막대 옆에 작게 병기한다.

예:

```text
Model A   품질       ██████████ 98.5   | 98.5
          속도       ██████     61     | 1.8s
          비용효율   ████       42     | 1.00x

Model B   품질       █████████  98.1   | 98.1   ✓ 선택
          속도       ██████████ 100    | 1.1s
          비용효율   ██████████ 100    | 0.42x

Model C   품질       ██████████ 99.0   | 99.0
          속도       ████       41     | 2.7s
          비용효율   █          15     | 2.80x
```

주의: 위 숫자는 레이아웃 예시이며 실제 결과가 아니다.

## 8. AI 생성 트리거 정책

### 8.1 비교 대상

생성 정책은 세 전략을 비교한다.

#### T0. Click / On-demand only

```text
사용자 refresh 클릭
→ 최신 snapshot/context 조회
→ LLM 생성
→ validate
→ 제공
```

- 장점: background 비용 최소
- 단점: 중요한 변화가 있어도 사전 브리핑 없음, 사용자가 생성 latency를 기다림

#### T1. Always pre-generate

```text
watcher가 새로운 snapshot/context 감지
→ 항상 LLM 생성
```

- 장점: 조회 시 최신 브리핑 준비 가능
- 단점: 사소한 변화에도 비용 발생

#### T2. Hybrid material-change pre-generation

```text
watcher
→ current vs previous evidence/context 비교
→ material change ?
   ├─ yes → pre-generate
   └─ no  → stored summary reuse

사용자가 명시적으로 refresh
→ 최신 snapshot/context로 on-demand generate
```

이번 구현 목표는 T2다.

### 8.2 Material Change 정의

`material change`는 "hash가 달라졌는가"가 아니라 다음 의미로 정의한다.

> 사용자가 별도 refresh를 누르지 않아도 새로운 브리핑을 미리 준비할 가치가 있는 운영 상태 변화인가?

선제 재생성 후보:

- 위험 등급 또는 review priority 변경
- anomaly/model factor의 중요한 변화
- 신규/변경 inspection result
- 신규/변경 WorkOrder 상태
- 신규/변경 MaintenanceAction/MaintenanceEvent
- 생산 영향 option의 상태 또는 핵심 수치 변경
- 정비 readiness의 blocker/후보 시간/자원 상태 변경
- evidence gap 해소 또는 새 critical gap 발생
- operational context version/fingerprint 변경 중 role decision에 영향을 주는 항목

기본 reuse 후보:

- timestamp/retrieval time만 변경
- 정렬 순서만 변경
- display metadata 변경
- role decision을 바꾸지 않는 미세 numeric 변화
- summary 생성 입력에 포함되지 않는 필드 변경

### 8.3 Evidence fingerprint + semantic change

두 단계로 판단한다.

1. **Exact fingerprint check**: 동일하면 즉시 reuse
2. **Material change policy**: fingerprint가 달라도 의미 있는 변화가 아니면 reuse

fingerprint 입력에는 최소 다음 version을 포함한다.

- evidence snapshot identity
- selected context hash/fingerprint
- prompt version
- summary schema version
- role policy version
- model policy version

### 8.4 저장 trace

최소 다음 필드를 workflow/eval trace에 기록한다.

```text
generation_trigger:
  INITIAL
  AUTO_MATERIAL_CHANGE
  USER_REFRESH
  RETRY
  FALLBACK

generation_decision:
  PREGENERATE
  REUSE
  ON_DEMAND

decision_reason
previous_fingerprint
current_fingerprint
role_policy_version
model_id
input_tokens
output_tokens
latency_ms
estimated_cost
```

## 9. 생성 트리거 평가

### 9.1 Temporal fixture

기존 8개 대표 scenario를 기반으로 시간축을 추가한다.

- 기본 목표: `8 scenarios × 10 snapshots = 80 snapshots`
- 시간 여유 시: 120 snapshots

각 snapshot에 다음 gold label을 부여한다.

- `PREGENERATE`
- `REUSE`
- `ON_DEMAND_OK`

예:

| 시점 | 변화 | Gold |
|---|---|---|
| T0 | 최초 상태 | PREGENERATE |
| T1 | sensor 미세 변화 | REUSE |
| T2 | retrieval timestamp만 변경 | REUSE |
| T3 | 위험 등급 상승 | PREGENERATE |
| T4 | 동일 상태 | REUSE |
| T5 | WorkOrder 생성 | PREGENERATE |
| T6 | display metadata 변경 | REUSE |
| T7 | 정비 이벤트 추가 | PREGENERATE |
| T8 | 생산 영향 option 변경 | PREGENERATE |
| T9 | 사용자가 명시적 refresh | ON_DEMAND_OK |

### 9.2 핵심 지표

#### Critical Change Coverage

```text
정답 PREGENERATE 중 실제 PREGENERATE / 정답 PREGENERATE
```

성공 기준: **100%**

#### False Reuse Rate

```text
중요 변화인데 REUSE한 건수 / 정답 PREGENERATE
```

성공 기준: **0%**

#### Unnecessary Pre-generation Rate

```text
정답 REUSE인데 PREGENERATE한 건수 / 정답 REUSE
```

비용 최적화 지표로 사용한다.

#### Background Call Reduction

Always pre-generate(T1) 대비 Hybrid(T2)의 background LLM call 감소율을 계산한다.

```text
1 - hybrid_background_calls / always_background_calls
```

Click-only와 비교해 background call reduction을 주장하지 않는다. Click-only는 애초에 background call이 0이므로 비교 목적이 다르다.

#### Briefing Availability

중요 변화 발생 후 사용자가 조회했을 때 최신 role briefing이 이미 준비되어 있는 비율을 측정한다.

이 지표가 Click-only 대비 Hybrid의 제품 가치를 설명한다.

#### User-perceived latency

- pre-generated hit: 저장 summary 조회 latency
- on-demand miss/refresh: evidence read + provider generation + validation latency

둘을 분리 보고한다.

## 10. 통합 평가

최종 비교는 다음 두 시스템으로 단순화한다.

### Baseline

- 현재 모델
- Always pre-generate 또는 현행 watcher 기준
- 현행 2-role/generic prose 소비

### Optimized

- 평가로 선정한 모델
- 3-role role-aware prompt/consumer
- Hybrid material-change pre-generation
- 기존 grounding/claim/snapshot/fallback guard 유지

최종 report에 다음 표를 남긴다.

| 지표 | Baseline | Optimized |
|---|---:|---:|
| Gold quality | 측정 | 측정 |
| 3-role required fact coverage | 측정 | 측정 |
| Cross-role truth consistency | 측정 | 측정 |
| Critical change coverage | 측정 | 측정 |
| False reuse | 측정 | 측정 |
| Background LLM calls | 측정 | 측정 |
| Input/output tokens | 측정 | 측정 |
| p50/p95 generation latency | 측정 | 측정 |
| User-perceived briefing latency | 측정 | 측정 |
| Estimated cost | 측정 | 측정 |

## 11. 기존 안정성 regression

이번 확장으로 기존 AI 안정성 계약을 약화시키지 않는다.

반드시 재검증할 항목:

- same summary key reuse
- provider timeout / malformed response
- invalid natural-language claim reject
- deterministic fallback containment
- stale running recovery
- concurrent materialization guard
- snapshot/context mismatch reject
- context changed during generation → persist 차단
- unknown source refs reject
- data-quality hold 표현 경계
- Closed-loop side effect 0건

기존 historical 평가값은 참고 evidence로만 사용한다. prompt/schema/model/role policy가 바뀌므로 새 구현 결과를 과거 120-run 결과로 대체하지 않는다.

## 12. 테스트 계획

### 12.1 Contract / unit

예상 변경 영역:

- `contracts/schemas/agent-review-summary*.schema.json`
- `systems/backend/app/operations/agent_review_summary.py`
- `systems/backend/app/operations/agent_review_summary_provider.py`
- `systems/backend/app/operations/agent_review_summary_materialization.py`
- `tests/test_agent_review_summary_contract.py`

추가 검증:

- 세 역할 quote 존재
- role enum/label 일치
- LLM은 prose editable field 외 구조 변경 불가
- 역할별 forbidden claim 검증
- v1.0 persisted summary compatibility 또는 명시적 degrade path

### 12.2 Consumer

예상 변경 영역:

- `systems/frontend/src/standalone/aiBrief.js`
- `systems/frontend/src/standalone/presentation.js`
- 관련 test

검증:

- `process_engineer` → engineer quote
- `maintenance_technician` → maintenance quote
- `process_manager` → manager quote
- 전용 quote가 없는 legacy summary는 공통 `summary`로 명시적 fallback
- 다른 role quote를 잘못 재사용하지 않음

### 12.3 Evaluation harness

기존 evaluator를 확장하고 임시 평가 스크립트는 최종 Git 산출물에서 제거하거나 기존 공식 harness에 흡수한다.

예상 변경:

- `scripts/evaluate_agent_review_summary_llm.py`
- `tests/eval/test_agent_decision_support_briefing_eval.py`
- temporal fixture / gold labels
- model comparison runner
- trigger policy evaluator

## 13. 발표 자료 수정 계획

### 13.1 표현 오류 수정

기존 presentation production spec의 `structured AI output` 표현은 다음으로 변경한다.

기존:

> 역할별 AI 요약 = structured AI output

수정:

> **구조화된 근거를 바탕으로 역할별 자연어 브리핑 생성**

발표에서 JSON 자체를 핵심 output처럼 설명하지 않는다.

### 13.2 핵심 흐름 문구

기존:

```text
근거 구성·선별 → AI 요약 생성·검증 → 저장
```

수정:

```text
근거 구성·선별
→ 역할/중요 변화 판단
→ 필요한 경우 자연어 브리핑 생성
→ 근거·시점 검증
→ 저장·재사용
```

### 13.3 역할별 브리핑 시각화

동일 Evidence에서 역할별 강조점이 달라지는 예시를 한 화면에 둔다.

```text
동일 Evidence Snapshot
        ↓
┌ process_engineer ──────┐
│ 이상 위치·원인 근거·점검 포인트 │
└──────────────────────┘
┌ maintenance_technician ┐
│ 정비 이력·작업 상태·준비 조건   │
└──────────────────────┘
┌ process_manager ───────┐
│ 생산 영향·승인/일정 판단       │
└──────────────────────┘
```

메시지:

> **같은 근거를 사용하되 역할에 따라 판단에 필요한 정보의 우선순위와 표현을 다르게 했다.**

### 13.4 모델 비교 시각화

모델 A/B/C 각각에 품질·속도·비용효율 3개 막대를 둔다. 세 축은 모두 높을수록 좋게 정규화한다. 실제 원값을 병기하고 선택 모델에만 체크 표시한다.

### 13.5 생성 정책 시각화

한 장에 복잡한 아키텍처를 추가하지 않는다. 다음 두 요소만 사용한다.

1. **Click / Always / Hybrid 비교 미니 표**
2. **snapshot timeline**: `● pre-generate`, `○ reuse`

실험 후 노출할 핵심 숫자는 최대 3개로 제한한다.

- 중요 변화 선제 생성 `N/N`
- False reuse `0`
- Always 대비 LLM background call `-X%`

## 14. 발표 대본 수정 기준

### 14.1 AI output 설명

> "저희가 최종적으로 원하는 결과는 구조화된 값 자체가 아니라, 여러 운영 데이터를 같은 시점의 맥락으로 묶어 사용자가 바로 읽을 수 있는 자연어 브리핑으로 만드는 것이었습니다. 입력은 근거 패킷으로 구조화하고, LLM은 그 근거들의 관계를 역할에 맞는 문장으로 표현하게 했습니다. 사실·시점·금지 주장은 별도 검증 계층에서 통제했습니다."

### 14.2 역할별 브리핑 설명

> "같은 근거를 보더라도 엔지니어는 이상 위치와 확인 근거가 먼저 필요하고, 보전 담당자는 정비 이력과 작업 준비 조건이, 생산 관리자는 생산 영향과 승인·일정 판단이 먼저 필요합니다. 그래서 사실은 동일하게 유지하고 정보의 우선순위와 표현만 역할별로 달리했습니다."

### 14.3 Click-only 반론 방어

> "사용자 클릭 시에만 생성하는 방식도 비교 대상입니다. 비용은 가장 작지만 중요한 변화가 발생해도 브리핑이 미리 준비되지 않고 요청 시 생성 지연이 생깁니다. 반대로 모든 변화마다 생성하면 비용이 커집니다. 그래서 중요한 운영 변화만 선제 생성하고 일반 변화는 저장 결과를 재사용하며, 사용자가 원하면 최신 근거로 직접 refresh할 수 있는 hybrid 정책을 선택했습니다."

### 14.4 모델 비교 설명

> "동일한 Evidence와 평가 기준으로 세 모델을 비교했습니다. 품질만 가장 높은 모델을 고른 것이 아니라, 요구 품질을 만족하는 모델 중 응답시간과 비용 효율이 가장 좋은 모델을 선택했습니다."

## 15. 구현 순서

### Phase 0 — 기준 고정

1. PR #167 HEAD와 현재 summary/prompt/schema/consumer 동작을 baseline으로 기록
2. 기존 evaluator와 holdout fixture 재현
3. 현재 2-role/generic 소비 결과 저장

### Phase 1 — 자연어 output 계약 정리

1. presentation/docs에서 `structured AI output` 오해 표현 수정
2. prose-only editable boundary를 문서와 테스트로 명시
3. role contract migration 결정

### Phase 2 — 3-role 브리핑

1. role definitions/prompt 추가
2. summary contract/version migration
3. deterministic fallback role quote 추가
4. frontend role-specific quote selection
5. role truth consistency test

### Phase 3 — 모델 비교

1. 2~3개 모델 동일 조건 실행
2. quality/latency/token/cost 집계
3. 품질 gate 통과 모델 중 운영 모델 선택
4. 3×3×3 발표 차트 데이터 생성

### Phase 4 — Hybrid generation policy

1. exact fingerprint reuse
2. material-change rule 구현
3. user refresh path 분리
4. trigger reason/trace 기록
5. temporal fixture 80개 평가

### Phase 5 — Regression / final report

1. 전체 unit/contract/integration/eval 재실행
2. 기존 stability/fault-injection regression
3. 모델·trigger 통합 비교
4. 최종 공식 Markdown report 작성
5. 발표 spec/script/5min script 반영

## 16. 성공 기준

### 필수 gate

- 세 PR #167 역할의 전용 자연어 브리핑 consumer 연결
- role 간 숫자/상태/근거 truth 충돌 0건
- Critical Change Coverage = **100%**
- False Reuse Rate = **0%**
- 금지/unsupported claim hard-gate 위반 candidate가 정상 저장되는 사례 0건
- snapshot/context 변경 중 stale summary 저장 0건
- Closed-loop mutation side effect 0건
- 기존 fallback/retry/concurrency regression 통과

### 최적화 지표

다음은 사전 목표값을 억지로 정하지 않고 실제 측정 결과를 보고한다.

- Always 대비 background LLM call reduction
- token/cost reduction
- p50/p95 latency
- user-perceived latency
- model별 quality/cost trade-off

## 17. 공식 산출물

최종 Git에는 발표/평가에 필요한 공식 산출물만 남긴다.

### 유지

- 이 구현·평가 계획서
- 공식 model/trigger 최종 평가 report
- 필요한 contract/schema 변경
- product/eval regression tests
- 작은 gold/temporal fixture
- 발표 production spec / 최종 대본 수정

### 제거 또는 `.gitignore`

- raw 반복 provider JSON
- 대량 token dump
- PNG chart 반복 산출물
- 임시 threshold sweep 로그
- 일회용 검증 스크립트
- 개인 메모/중간 분석 문서

## 18. 최종 발표 Claim 경계

실제 구현·평가가 완료되기 전에는 다음을 주장하지 않는다.

- "3역할 AI 브리핑 구현 완료"
- "AI 호출 비용 X% 절감"
- "모델 B가 최적"
- "중요 변화 100% 탐지"

구현과 평가 후에만 실제 수치로 교체한다.

현재 PR #167 기준으로 안전하게 말할 수 있는 것은 다음이다.

> **구조화된 운영 근거를 바탕으로 LLM이 자연어 요약 prose를 생성하고, deterministic contract가 근거·금지 주장·시점·source reference를 검증하는 경로가 존재한다. PR #167의 3역할 화면과 AI 역할별 prose 계약은 아직 완전히 정렬되지 않아 이번 계획에서 확장 대상으로 둔다.**

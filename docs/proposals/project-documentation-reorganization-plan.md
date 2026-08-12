# 프로젝트 문서 정리 계획안

- 문서 상태: `Proposal — 팀 검토 필요`
- 작성일: `2026-08-12`
- 대상 저장소: `Biz-CollabCraft/ontology_dashboard`
- 작업 범위: 프로젝트 전체 문서 구조, 기준 문서, 제안서, 이력·보존 자료
- 실행 조건: 팀 합의 후 별도 문서 정리 PR로 진행

## 1. 목적

현재 저장소에는 현재 구현과 확정 계약, 미채택 Target, 개인 프로토타입 원문,
PR 통합 이력, 진행 중인 Evidence·What-if 계획과 과거 UI 자료가 함께 있다.

이번 정리의 목적은 문서를 일괄 삭제하는 것이 아니라 각 문서의 권위와 상태를
명확히 구분하는 것이다. 정리 후에는 다음 질문에 바로 답할 수 있어야 한다.

1. 현재 `main` 구현의 기준 문서는 무엇인가?
2. 확정된 계약과 아직 논의 중인 제안은 무엇인가?
3. 과거 기록과 참고 자료는 어디에 있는가?
4. 요구사항은 실제 코드와 테스트에 연결되어 있는가?

## 2. 정리 원칙

### 2.1 문서 상태

| 상태 | 의미 |
|---|---|
| `Current` | 현재 `main` 구현과 일치하는 기준 문서 |
| `Accepted` | 팀이 채택했으나 일부 구현이 남은 계약 |
| `Proposal` | 팀 결정 전 제안 |
| `In Progress` | 구현 또는 검증 진행 중 |
| `Historical` | 과거 결정·이관 기록 |
| `Archived` | 현재 계약으로 사용하지 않는 보존 자료 |
| `Superseded` | 다른 문서로 대체된 자료 |

주요 문서는 가능하면 다음 메타데이터를 갖는다.

```markdown
- 문서 상태:
- 기준 브랜치:
- 기준 커밋:
- 마지막 검증일:
- 담당 영역:
- 상위 또는 대체 문서:
```

### 2.2 관리 원칙

- `Current` 문서는 실제 `main` 코드와 테스트로 검증한다.
- 현재 계약과 Target 제안을 같은 계약처럼 섞지 않는다.
- PR 번호만으로 상태를 설명하지 않고 기준 커밋과 검증일을 기록한다.
- 개인 프로토타입 원문은 현재 계약의 근거로 사용하지 않는다.
- 제안이 채택되면 확정된 내용만 기준 문서로 승격한다.
- 코드 경로가 바뀌면 추적성 매트릭스도 함께 갱신한다.

## 3. 목표 구조

아래 구조는 방향 제안이며 팀 합의 전에는 파일을 이동하지 않는다.

```text
docs/
├─ README.md
├─ architecture.md
├─ ai-code-review-context.md
├─ product/
│  ├─ requirements.md
│  ├─ functional-specification.md
│  └─ role-and-screen-policy.md
├─ contracts/
│  ├─ api-contract.md
│  ├─ schema-contract.md
│  ├─ report-contract.md
│  └─ feature-contract.md
├─ traceability/
│  └─ implementation-matrix.md
├─ proposals/
├─ analysis/
├─ decisions/
├─ deployment/
└─ archive/
   ├─ prototype-source-2026-08/
   ├─ integration-history/
   └─ ui-reference/
```

## 4. 문서별 처리 제안

### 4.1 우선 갱신할 현재 기준 문서

| 문서 | 확인된 문제 | 제안 |
|---|---|---|
| `docs/architecture.md` | 완료된 PR #9 이관을 후속 작업처럼 설명 | 완료 이력으로 전환하고 현재 시스템 경계를 재검증 |
| `current-mvp-implementation-baseline.md` | PR #9/#10 시점 설명이 중심 | 현재 `main` 커밋 기준 역할·API·화면·fallback 재검증 |
| `week2-mvp-design-specification.md` | 개인 프로토타입 브랜치를 현행 실행 코드로 설명 | 팀 저장소의 `systems/*` 구조를 실행 기준으로 수정 |
| `week2-traceability-matrix.md` | 존재하지 않는 `web/`, `api/` 구현 경로 포함 | `systems/frontend`, `systems/backend` 실제 경로와 테스트로 갱신 |

`week2-traceability-matrix.md`는 잘못된 경로가 구현 탐색을 직접 방해하므로 가장 먼저
수정한다.

### 4.2 Current와 Target을 분리할 문서

대상:

- `week2-requirements-specification.md`
- `week2-functional-specification.md`
- `week2-api-specification.md`
- `week2-report-specification.md`
- `week2-schema-definition.md`

현재 `main`에 존재하는 요구사항·API·Schema·Report 계약은 `Current`로 관리한다.
기간 기반 Executive Report, 신규 필터, `/overview`, `/objects`,
`/reports/executive` 등 미채택 내용은 `Proposal` 또는 `Backlog`로 분리한다.

### 4.3 결정·통합 이력으로 보존할 문서

다음 문서는 현재 계약 자체보다 결정과 이관 과정을 설명한다.

- `week2-contract-review-checklist.md`
- `prototype-mvp-gap-analysis.md`
- `week2-prototype-doc-migration-map.md`
- `week2-frontend-implementation-import.md`
- `week2-runtime-ownership-integration.md`

아직 유효한 규칙을 현재 요구사항 또는 `architecture.md`로 옮긴 뒤
`docs/decisions/` 또는 `docs/archive/integration-history/`로 이동하는 방안을 검토한다.

### 4.4 개인 프로토타입 원문

`docs/mentoring-mvp-2026-08/prototype-source/`는 원문 보존 가치가 있지만 현재 API와
역할, 화면 및 코드 경로로 오인될 수 있다.

권장 조치는 다음과 같다.

1. `docs/archive/prototype-source-2026-08/`로 이동한다.
2. 각 문서에 `Archived — 현재 계약으로 사용 금지` 경고를 추가한다.
3. 기본 읽는 순서에서 제거한다.
4. 현재 문서가 원문을 계약 근거로 인용하면 유효한 내용을 먼저 현재 문서로 승격한다.

### 4.5 Evidence와 What-if 문서

| 문서 | 제안 상태 | 처리 방향 |
|---|---|---|
| `pdm-evidence-report-ui-integration-plan.md` | `In Progress` | 완료 계약과 후속 구현을 구분하고 기준 커밋 기록 |
| `preventive-what-if-development-plan.md` | `In Progress` | PR #20 완료 범위와 PR #21~#24 의존성 유지 |
| `preventive-risk-rise-analysis.md` | `Current Analysis` | 운영 판단·인과·조치 효과의 비권위 경계 유지 |

완료된 계약은 계획서에만 남기지 않고 Architecture, API 또는 Schema 기준 문서로
승격한다.

### 4.6 PR #21~#24 처리 제안서

외부 검토 문서 `pr21-24-proposal.md`는 다음 경로의 별도 `Proposal`로 추가하는 것을
검토한다.

```text
docs/proposals/pr21-24-feature-contract-and-merge-plan.md
```

추가 전 다음 사항을 보완한다.

- 각 PR의 검증 대상 head SHA를 기록한다.
- PR #17 번호와 설명을 재검증한다.
- 저장소에 존재하지 않는 `docs/adr/004-dataset-switch-to-pdm.md` 참조를 수정한다.
- 보존용 `prototype-source` 문서를 현재 MVP 범위의 상위 근거로 사용하지 않는다.
- 물리 Feature와 시계열 Feature를 합치는 C안은 확정 계약이 아닌 권장안으로 표시한다.
- `history` 활용에 필요한 window·정렬·결측·최소 길이 규칙을 계약 변경으로 다룬다.
- stacked PR을 rebase, cherry-pick 또는 통합 브랜치 중 어떤 방식으로 재구성할지 명시한다.
- Model Score와 Product Result Artifact의 책임을 분리한다.

### 4.7 UI 이미지

현재 문서에서 직접 참조되지 않는 이미지가 다수 존재한다. 다음 묶음은 현재 화면,
과거 디자인, 참고 이미지를 구분하기 어렵다.

- `docs/00-team-onboarding/assets/screenshots/`
- `docs/ui/palantir-overhaul/`
- `docs/ui/palantir-integration/`

현재 발표·제품 기준 화면을 선정하고 나머지는 `docs/archive/ui-reference/`로 이동한다.
각 이미지 묶음에는 상태와 용도를 설명하는 `README.md`를 둔다. 설명도 참조도 없는
이미지는 팀 확인 후 삭제 여부를 결정한다.

## 5. 팀 결정 항목

| ID | 결정 항목 | 권장안 |
|---|---|---|
| `DEC-DOC-01` | 현재 제품 기준 문서 | 요구사항·Architecture·API·Schema·Traceability 5개 축으로 단순화 |
| `DEC-DOC-02` | Week 2 문서 유지 방식 | 유효 내용은 장기 기준 문서로 승격하고 Week 2 문서는 이력화 |
| `DEC-DOC-03` | PR #21~#24 Feature C안 | Feature schema와 훈련·추론 parity 검증 후 채택 여부 결정 |
| `DEC-DOC-04` | Generator daemon | 배포 위치·운영 책임·MVP 범위를 정하기 전 Architecture에 반영하지 않음 |
| `DEC-DOC-05` | 과거 자료 삭제 | 원문은 Archive, 설명 없는 대형 UI 이미지는 별도 삭제 검토 |

## 6. 실행 순서

### 1단계 — 기준선 고정

- 최신 `main`과 기준 커밋을 기록한다.
- 현재 API, 화면, Schema와 시스템 경로를 검증한다.
- PR #21~#24의 검증 대상 head SHA를 기록한다.

### 2단계 — 명백한 오류 수정

- 추적성 매트릭스의 제거된 경로를 수정한다.
- 설계 명세의 개인 프로토타입 실행 기준을 제거한다.
- Architecture의 완료된 후속 작업 표현을 수정한다.
- 존재하지 않는 ADR과 잘못된 PR 참조를 수정한다.

### 3단계 — Current와 Proposal 분리

- 요구사항
- 기능
- API
- Report
- Schema

### 4단계 — 제안과 결정 관리

- PR #21~#24 제안서를 검증 후 저장한다.
- Evidence와 What-if 계획의 의존성을 연결한다.
- 팀 결정이 필요한 내용을 ADR 후보로 분리한다.

### 5단계 — 과거 자료 격리

- 개인 프로토타입 원문
- 통합 이력
- 과거 UI 참고 자료

### 6단계 — 인덱스와 검증

- `docs/README.md`를 현재 계약 → 구현 추적 → 제안 → 결정 → Archive 순으로 고친다.
- Markdown 링크와 문서 내 실제 파일 경로를 검사한다.
- Current API와 실제 라우트, Schema와 코드 모델, 추적성 테스트를 대조한다.
- `git diff --check`를 통과시킨다.

## 7. 완료 기준

- [ ] 현재 기준 문서와 제안 문서가 구분된다.
- [ ] 개인 프로토타입 원문을 현재 계약으로 오인할 수 없다.
- [ ] 모든 현행 코드 경로가 실제 저장소 구조와 일치한다.
- [ ] 현행 API와 Target API가 분리되어 있다.
- [ ] 요구사항이 코드와 테스트에 연결된다.
- [ ] PR #21~#24 제안의 검증 사실과 결정안이 구분된다.
- [ ] 존재하지 않는 ADR과 잘못된 PR 참조가 없다.
- [ ] UI 이미지마다 현재·과거·참고 상태가 구분된다.
- [ ] `docs/README.md`에서 올바른 문서 탐색 순서를 확인할 수 있다.
- [ ] Markdown 링크와 문서 내 파일 경로 검사가 통과한다.

## 8. PR 분리 원칙

이번 1차 PR은 이 계획안과 문서 인덱스 링크만 추가한다. 실제 파일 이동, 삭제,
Current 계약 수정은 포함하지 않는다.

팀 합의 후 2차 PR에서 승인된 범위만 실행한다. 대규모 이동이 필요하면 기준 문서
수정, Archive 이동, UI 자료 정리를 다시 작은 PR로 분리한다.

# 프로젝트 문서 정리 계획안

- 문서 상태: `검토 중`
- 작성일: `2026-08-12`
- 대상 저장소: `Biz-CollabCraft/ontology_dashboard`
- 실행 조건: 팀 공유와 합의 후 별도 정리 PR로 진행

## 1. 목적

현재 저장소에는 현재 구현 기준, 미확정 제안, 개인 프로토타입 원문, PR 통합 이력과
과거 UI 자료가 함께 있다. 이 때문에 팀원이 어떤 문서를 현재 기준으로 사용해야
하는지 혼동할 수 있다.

이번 작업은 복잡한 문서 관리 체계를 새로 만드는 것이 아니라 프로젝트 전체 문서를
한 번 정리하고, 현재 읽어야 할 문서와 참고용 과거 자료를 구분하는 것을 목적으로
한다.

## 2. 문서 구분

문서는 다음 세 가지로만 구분한다.

| 구분 | 의미 |
|---|---|
| `현재 기준` | 현재 `main` 코드와 팀 합의에 사용하는 문서 |
| `검토 중` | 아직 확정되지 않은 계획과 변경 제안 |
| `보관` | 현재 계약으로 사용하지 않는 프로토타입·이관 기록·과거 자료 |

별도의 문서 관리 가이드는 만들지 않는다. 정리 후 `docs/README.md`에 위 구분과
현재 문서를 읽는 순서만 간단히 기록한다.

## 3. 우선 수정할 문서

| 문서 | 확인된 문제 | 처리 방향 |
|---|---|---|
| `docs/architecture.md` | 완료된 PR #9 이관을 후속 작업처럼 설명 | 완료 이력으로 수정하고 현재 시스템 경계 재확인 |
| `current-mvp-implementation-baseline.md` | PR #9/#10 시점 설명이 중심 | 현재 `main` 기준 역할·API·화면·fallback 재검증 |
| `week2-mvp-design-specification.md` | 개인 프로토타입 브랜치를 현행 실행 코드로 설명 | 팀 저장소의 `systems/*` 구조를 실행 기준으로 수정 |
| `week2-traceability-matrix.md` | 존재하지 않는 `web/`, `api/` 경로가 현행 위치로 기록됨 | 실제 `systems/frontend`, `systems/backend` 경로와 테스트로 갱신 |

잘못된 코드 경로가 구현 탐색을 직접 방해하므로 추적성 매트릭스를 가장 먼저
수정한다.

## 4. 현재 기준과 검토 중 제안 분리

다음 문서에는 현재 구현과 V2 Target이 함께 들어 있다.

- `week2-requirements-specification.md`
- `week2-functional-specification.md`
- `week2-api-specification.md`
- `week2-report-specification.md`
- `week2-schema-definition.md`

현재 `main`에 존재하는 요구사항·API·Schema·Report 계약은 `현재 기준`으로 표시한다.
기간 기반 Executive Report, 신규 필터, `/overview`, `/objects`,
`/reports/executive` 등 미채택 내용은 `검토 중` 또는 후속 범위로 분리한다.

파일을 반드시 모두 나누지는 않는다. 한 파일 안에서도 현재 기준과 제안이 명확히
구분되면 유지할 수 있다. 반복 설명이 많거나 오인 가능성이 큰 경우에만 별도 파일로
분리한다.

## 5. 보관할 문서

### 5.1 개인 프로토타입 원문

`docs/mentoring-mvp-2026-08/prototype-source/`는 원문 보존 가치는 있지만 현재 API,
화면과 코드 경로로 오인될 수 있다.

권장 처리:

- `docs/archive/prototype-source-2026-08/`로 이동
- 현재 계약으로 사용하지 않는 보관 자료라는 경고 추가
- 기본 읽는 순서에서 제외
- 현재 문서가 이 원문을 계약 근거로 사용하면 유효한 내용을 먼저 현재 문서로 이동

### 5.2 통합·이관 기록

다음 문서는 현재 사용법보다 과거 통합 과정을 설명한다.

- `week2-prototype-doc-migration-map.md`
- `week2-frontend-implementation-import.md`
- `week2-runtime-ownership-integration.md`
- `week2-contract-review-checklist.md`
- `prototype-mvp-gap-analysis.md`

아직 유효한 규칙은 현재 Architecture나 요구사항 문서에 반영한 뒤
`docs/archive/integration-history/`로 이동하는 방안을 검토한다.

## 6. 진행 중인 개발 문서

| 문서 | 구분 | 처리 방향 |
|---|---|---|
| `pdm-evidence-report-ui-integration-plan.md` | `검토 중/진행 중` | 완료된 계약과 남은 구현을 구분 |
| `preventive-what-if-development-plan.md` | `검토 중/진행 중` | PR #20 완료 범위와 PR #21~#24 의존성 유지 |
| `preventive-risk-rise-analysis.md` | `현재 기준 분석` | 운영 판단·인과·조치 효과의 비권위 경계 유지 |

계획에서 확정되어 구현된 계약은 계획서에만 남기지 않고 실제 Architecture, API 또는
Schema 문서에도 반영한다.

## 7. PR #21~#24 제안서

외부 검토 문서 `pr21-24-proposal.md`는 검증 후 다음 위치에 `검토 중` 문서로 추가하는
방안을 검토한다.

```text
docs/proposals/pr21-24-feature-contract-and-merge-plan.md
```

추가 전 확인할 사항:

- 각 PR의 검증 대상 head SHA 기록
- PR #17 번호와 설명 재확인
- 저장소에 존재하지 않는 `docs/adr/004-dataset-switch-to-pdm.md` 참조 수정
- 보관용 프로토타입 문서를 현재 MVP 범위의 상위 근거로 사용하지 않도록 수정
- 물리 Feature와 시계열 Feature를 합치는 C안을 확정 계약이 아닌 제안으로 표시
- `history`의 window·정렬·결측·최소 길이 규칙 명시
- stacked PR의 실제 재구성 및 머지 방법 명시
- Model Score와 Product Result Artifact의 책임 분리

## 8. UI 이미지

다음 위치에는 문서에서 참조되지 않거나 현재 상태를 알기 어려운 이미지가 다수 있다.

- `docs/00-team-onboarding/assets/screenshots/`
- `docs/ui/palantir-overhaul/`
- `docs/ui/palantir-integration/`

현재 발표·제품 기준 화면만 명확히 표시하고 과거 디자인은
`docs/archive/ui-reference/`로 이동한다. 설명도 참조도 없고 다시 사용할 계획도 없는
이미지는 팀 확인 후 삭제를 검토한다.

## 9. 팀에서 확인할 사항

1. 현재 기준으로 유지할 핵심 문서
2. Week 2 문서를 그대로 유지할지, 유효 내용만 현재 기준 문서로 옮길지
3. 개인 프로토타입과 통합 기록의 보관 위치
4. PR #21~#24 제안서를 저장소에 추가할지
5. 유지할 UI 이미지와 삭제 가능한 이미지 범위

Feature C안이나 Generator daemon 같은 기술 결정은 이번 문서 정리 PR에서 확정하지
않고 관련 개발 PR에서 별도로 논의한다.

## 10. 실행 순서

### 1단계 — 현재 상태 확인

- 최신 `main` 기준 커밋 기록
- 실제 API, 화면, Schema와 시스템 경로 확인
- PR #21~#24의 최신 상태와 head SHA 확인

### 2단계 — 명백한 오류 수정

- 존재하지 않는 코드 경로 수정
- 개인 프로토타입을 현행 실행 기준으로 설명하는 내용 수정
- 이미 완료된 작업을 후속으로 표현한 내용 수정
- 존재하지 않는 ADR과 잘못된 PR 참조 수정

### 3단계 — 문서 구분

- 현재 기준과 미채택 제안을 명확히 표시
- 프로토타입 원문과 이관 기록을 보관 영역으로 이동
- 진행 중 계획 문서의 완료·대기 범위 갱신

### 4단계 — 이미지와 인덱스 정리

- 현재 UI와 과거 참고 이미지 구분
- 필요 없는 이미지 삭제 여부 확인
- `docs/README.md`에 현재 기준 → 검토 중 → 보관 순서로 링크 정리

### 5단계 — 검증

- Markdown 내부 링크 확인
- 문서에 작성된 코드 경로의 실제 존재 여부 확인
- 현재 API와 실제 라우트 비교
- 추적성 매트릭스의 코드와 테스트 연결 확인
- `git diff --check`

## 11. 완료 기준

- [ ] 현재 기준, 검토 중, 보관 문서가 구분된다.
- [ ] 개인 프로토타입 원문을 현재 계약으로 오인할 수 없다.
- [ ] 현행 코드 경로가 실제 저장소 구조와 일치한다.
- [ ] 현행 API와 미채택 Target API가 구분된다.
- [ ] PR #21~#24 제안의 검증 사실과 제안이 구분된다.
- [ ] 존재하지 않는 ADR과 잘못된 PR 참조가 없다.
- [ ] 현재 UI와 과거 참고 이미지가 구분된다.
- [ ] `docs/README.md`에서 현재 읽어야 할 문서를 확인할 수 있다.
- [ ] Markdown 링크와 문서 내 파일 경로 검사가 통과한다.

## 12. PR 범위

이번 1차 PR에는 이 계획안과 `docs/README.md`의 계획안 링크만 포함한다. 기존 문서의
이동·삭제·내용 수정은 하지 않는다.

팀 합의 후 별도 PR에서 승인된 범위만 실제로 정리한다.

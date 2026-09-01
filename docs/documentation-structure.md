# Documentation Structure

상태: 팀 문서 정리 기준
기준: 2026-09-01
범위: `docs/` 문서 위치, 네이밍, 읽는 순서, 개인 기여 문서와 팀 공유 문서의 분리

이 문서는 문서를 새로 만들거나 이동할 때의 기준을 정리한다. 목적은 모든 문서를 한 번에
리네이밍하는 것이 아니라, 팀원이 현재 계약과 배경 문서를 빠르게 구분하게 만드는 것이다.

## 1. 폴더 역할

| 위치 | 역할 | 예시 |
| --- | --- | --- |
| `docs/mvp/` | 현재 MVP 제품/계약/운영 기준. 팀원이 먼저 읽는 canonical namespace다. | 요구사항, 기능 명세, API 명세, Runtime/Evidence 경계 |
| `docs/architecture-decisions/` | 아키텍처 결정 기록. 상태가 Proposed/Accepted인지 명시한다. | ADR-003, ADR-004 |
| `docs/plans/` | 아직 구현 전이거나 PR 단위로 실행할 계획. 완료 구현 근거처럼 말하지 않는다. | AssetDetailViewModel 계획, Runtime/Closed-loop 계획 |
| `docs/plans/ai-workflow/` | AI/LLM/Agent Review와 인접한 Evidence, Summary, Snapshot 계획. AI 전용 폴더가 아니라 신뢰 경계 계획도 포함한다. | AI context plan, Product Result/Evidence materialization, Snapshot guard |
| `docs/schema/` | 사람이 읽는 DB/관계/구조 다이어그램. 기계 판독 JSON Schema 정본은 `contracts/schemas/`다. | Workflow and Closed-loop DB Diagram |
| `docs/contributions/` | 개인 또는 역할별 기여 근거. 팀 canonical 계약이 아니라 증빙/요약 문서다. | Backend Runtime/Evidence contribution, AI Review contribution |
| `docs/operations/` | 운영 환경, 배포, 모델 품질, Mac mini 같은 실행/운영 문서. | Mac mini production, model quality roadmap |
| `docs/deployment/` | 배포 스택과 데모 배포 기준. | free demo stack |
| `docs/mvp/history/` | 과거 주차/이관/비교 자료. 현재 계약처럼 소비하지 않는다. | 2026-08 Week 2 history |

## 2. 읽는 순서

새 팀원이 현재 MVP 경계를 보려면 다음 순서로 읽는다.

1. [MVP / Product Documentation](./mvp/README.md)
2. [Backend Runtime, Evidence, and Agent Review Boundary](./mvp/backend-runtime-evidence-agent-review-boundary.md)
3. [ADR-003: Generator Runtime Prediction Result 및 Backend Decision 소유권](./architecture-decisions/ADR-003-generator-runtime-prediction-result-and-backend-decision-ownership.md)
4. [ADR-004: Product Result / Evidence / ViewModel 신뢰 경계](./architecture-decisions/ADR-004-product-result-evidence-viewmodel-trust-boundary.md)
5. [Workflow and Closed-loop DB Diagram](./schema/db-diagram.md)
6. [Closed-loop Domain 계약](./closed-loop-domain-contract.md)
7. [Closed-loop Product/API/UI 소비 계약](./closed-loop-product-consumption-contract.md)

개인 기여 근거가 필요할 때만 [Backend Runtime / Evidence Delivery Contribution](./contributions/hb-backend-runtime-evidence.md)과
[AI Review / Evidence Boundary Contribution](./contributions/hb-ai-review-evidence.md)를 읽는다.

## 3. 네이밍 기준

| 문서 종류 | 파일명 기준 | 제목 기준 |
| --- | --- | --- |
| 현재 팀 계약 | 대상과 경계를 그대로 쓴 kebab-case | 제품/기술 경계를 설명하는 명사형 제목 |
| ADR | `ADR-NNN-short-topic.md` | 결정 주제와 상태를 함께 드러낸다. |
| 계획 문서 | `YYYY-MM-DD-NNN-short-topic-plan.md` | 구현 계획, 제안, follow-up임을 제목이나 상태에 표시한다. |
| 개인 기여 문서 | `hb-topic-evidence.md` 또는 `hb-topic-contribution.md` | 개인 기여 근거임을 명시한다. |
| 다이어그램 | `topic-diagram.md` 또는 `topic-erd.md` | source of truth와 포함/제외 범위를 첫 단락에 적는다. |

## 4. 표현 기준

- `docs/mvp/` 문서는 현재 팀 기준처럼 읽히므로 개인 성과 중심 표현을 피한다.
- `docs/contributions/` 문서는 개인 기여를 설명할 수 있지만, merged/open/closed 상태를 구분한다.
- `docs/plans/` 문서는 구현 완료가 아니라 실행 계획 또는 설계 제안으로 표현한다.
- `docs/schema/`의 DB 다이어그램은 사람이 읽는 구조 문서다. API/schema 검증 정본은 `contracts/schemas/`를 참조한다.
- 외부 링크보다 저장소 내부 상대 링크를 우선한다.
- 로컬 절대경로는 팀 공유 문서에 넣지 않는다.

## 5. 변경 규칙

| 변경하려는 것 | 이번 PR에서 허용 | 별도 PR 권장 |
| --- | --- | --- |
| README 링크/읽는 순서 정리 | 허용 | - |
| 새 경계 요약 문서 추가 | 허용 | - |
| 문서 첫 문단의 목적/상태 보강 | 허용 | - |
| 대량 파일명 변경 | - | 권장 |
| history 문서 이동 | - | 권장 |
| 팀원 소유 문서 의미 변경 | - | 권장 |
| 코드, DB migration, JSON Schema 변경 | - | 권장 |

## 6. 현재 기준점

PR #156은 `RecommendationInput` snapshot guard와 Workflow/Closed-loop DB diagram을 추가한 상태다.
PR #157 문서 정리는 그 구현을 바꾸지 않고, 팀원이 관련 문서의 위치와 책임 경계를 찾을 수 있게 하는
follow-up으로 제한한다.

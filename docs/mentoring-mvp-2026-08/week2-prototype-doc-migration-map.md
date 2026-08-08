# Week 2 개인 프로토타입 문서 이관 매핑

- 상태: `migration record`
- 작성일: `2026-08-08`
- 개인 프로토타입: `oosuhada/agentic-ontology-dashboard`
- 팀 제품·계약 저장소: `Biz-CollabCraft/ontology_dashboard`

## 1. 목적

개인 프로토타입에서 먼저 작성된 상세 Week 2 문서를 팀 저장소로 승격하는 과정에서
동일한 내용을 여러 파일에 복제하거나 이미 팀 PR로 확정된 계약을 덮어쓰지 않도록
출처와 최종 팀 문서의 대응 관계를 기록한다.

팀 저장소의 문서가 공식 기준이며, 개인 프로토타입 문서는 상세 구현 참고 자료다.

## 2. 원본 문서와 팀 기준 문서 매핑

| 개인 프로토타입 문서 | 팀 저장소에서의 처리 | 팀 기준 문서 |
|---|---|---|
| `week2-team-role-and-deliverables.md` | 팀 저장소에 역할 실행 기준으로 재정리하여 승격 | `week2-team-role-and-deliverables.md` |
| `mvp-scope-and-screen-specification.md` | 화면·범위·완료조건을 기존 팀 문서와 수렴 | `week2-requirements-specification.md`, `week2-functional-specification.md`, `week2-mvp-design-specification.md` |
| `mvp-api-specification.md` | 현행 구현 세부 내용은 baseline, 목표 계약은 API 문서에서 관리 | `current-mvp-implementation-baseline.md`, `week2-api-specification.md` |
| `mvp-data-contract.md` | 공통 필드·enum·provenance를 팀 스키마 단일 기준으로 수렴 | `week2-schema-definition.md`, `v3.1-field-validation.md` |

## 3. 개인 프로토타입 원본 위치

원본은 다음 브랜치의 `docs/10-product/mentoring-mvp-2026-08/`에 보존한다.

```text
repository: oosuhada/agentic-ontology-dashboard
branch: feature/predictive-maintenance-adaptive-modeling
```

원본 문서:

- `week2-team-role-and-deliverables.md`
- `mvp-scope-and-screen-specification.md`
- `mvp-api-specification.md`
- `mvp-data-contract.md`

개인 레포의 문서를 삭제하지 않는다. 팀 문서와 구현 사이에 차이가 생겼을 때 상세
근거 또는 프로토타입 구현 확인용으로 사용할 수 있다.

## 4. 이관 원칙

1. 팀 저장소의 이미 merge된 결정사항을 개인 문서로 덮어쓰지 않는다.
2. 동일 계약의 복사본을 `ontology_dashboard`와 `gen_data`에 각각 만들지 않는다.
3. 공통 필드명과 enum의 단일 기준은 `week2-schema-definition.md`다.
4. 현행 코드 사실은 `current-mvp-implementation-baseline.md`를 우선한다.
5. 화면·API·리포트 계약의 변경은 해당 팀 문서와 체크리스트를 함께 갱신한다.
6. 개인 프로토타입의 더 상세한 항목은 필요할 때 팀 공식 문서로 선택적으로 승격한다.

## 5. 현재 이관 결과

이번 이관에서는 중복 문서 세 벌을 새로 만들지 않고 다음을 수행한다.

- 팀원별 역할·완료조건·병렬 작업 원칙을 팀 저장소에 추가
- 기존 팀 요구사항/기능/API/스키마/MVP 설계 문서를 공식 기준으로 유지
- 개인 프로토타입 상세 명세가 어느 팀 문서로 수렴했는지 매핑 기록
- 데이터 생성 코드는 `Biz-CollabCraft/gen_data`가 담당하되 계약 원본은 이 저장소에 유지


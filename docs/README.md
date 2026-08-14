# 프로젝트 문서

이 디렉터리는 `Biz-CollabCraft/ontology_dashboard`의 제품 요구사항, 데이터 계약,
API 계약과 팀 공유 문서를 관리한다.

## 문서 묶음

- [최종 역할 분배 및 Step별 실행 계획](./final_team_role_and_step_plan.md)
- [아키텍처](./architecture.md)
- [Architecture Decision Records](./architecture-decisions/README.md)
- [2026년 8월 멘토링 MVP](./mentoring-mvp-2026-08/README.md)
  - [Generator Feature/Label 계약](./mentoring-mvp-2026-08/week2-generator-feature-label-contract.md)
  - [Model Artifact Publish 계약](./mentoring-mvp-2026-08/week2-model-artifact-publish-contract.md)
  - [Runtime Ownership](./mentoring-mvp-2026-08/week2-runtime-ownership-integration.md)
  - [스키마 정의서](./mentoring-mvp-2026-08/week2-schema-definition.md)
  - [추적성 매트릭스](./mentoring-mvp-2026-08/week2-traceability-matrix.md)
- [AI 코드 리뷰 컨텍스트](./ai-code-review-context.md)

## 공유 계약 (Shared Contracts)

향후 시스템 간 공유 계약은 저장소 최상위 `contracts/`에서 관리할 예정이다.
현재는 디렉터리 골격과 관리 원칙만 마련된 상태이며, 기존 Schema와 실행 코드의
참조 경로는 아직 변경되지 않았다.
자세한 내용은 [`contracts/README.md`](../contracts/README.md)를 참고한다.

## 관리 원칙

- 문서 묶음은 목적이나 마일스톤을 나타내는 이름으로 `docs/` 바로 아래에 둔다.
- 다른 저장소의 번호형 디렉터리 체계를 그대로 복사하지 않는다.
- 데이터 원본과 대용량 결과 파일은 문서 디렉터리에 중복 저장하지 않는다.
- 검증된 사실, 요구사항 초안, 팀 합의가 필요한 항목을 문서 상태로 구분한다.
- 공통 필드명의 최종 기준은 해당 문서 묶음의 스키마 정의서로 관리한다.


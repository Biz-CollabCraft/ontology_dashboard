# 팀 공유 문서 — Mentoring MVP 2026-08

이 폴더는 팀원2가 관리하는 제품·데이터·화면·API·LLM 계약의 공유 위치다.
문서는 검증된 사실, 제안, 미결 결정을 구분한다.

## 읽는 순서

1. [Week 2 역할 분담 및 산출물 정의](./week2-team-role-and-deliverables.md)
2. [Canonical V3.1 필드 검증표](./v3.1-field-validation.md)
3. [프로토타입과 멘토링 MVP 차이 분석](./prototype-mvp-gap-analysis.md)
4. [Week 2 요구사항 명세 초안](./week2-requirements-specification.md)
5. [Week 2 공통 스키마 정의서](./week2-schema-definition.md)
6. [Week 2 계약 검토 체크리스트](./week2-contract-review-checklist.md)
7. [현행 MVP 구현 계약 기준선](./current-mvp-implementation-baseline.md)
8. [Week 2 리포트 정의서](./week2-report-specification.md)
9. [Week 2 기능 명세서](./week2-functional-specification.md)
10. [Week 2 API 명세서](./week2-api-specification.md)
11. [Week 2 MVP 설계 명세서](./week2-mvp-design-specification.md)
12. [Week 2 추적성 매트릭스](./week2-traceability-matrix.md)
13. [개인 프로토타입 문서 이관 매핑](./week2-prototype-doc-migration-map.md)
14. [개인 프로토타입 원문 보존본](./prototype-source/)

## 문서 상태

| 문서 | 상태 | 용도 |
|---|---|---|
| `week2-team-role-and-deliverables.md` | 실행 기준 | 팀원별 책임·완료조건·병렬 작업 원칙 |
| `v3.1-field-validation.md` | 검증 완료 | 공식 V3.1과 기존 V1.1/V1.3 초안의 필드 차이 근거 |
| `prototype-mvp-gap-analysis.md` | Current/Target 정리 | 현행·목표·Gap과 Week 2 반영 여부 판단 |
| `week2-requirements-specification.md` | 초안 | 검증된 범위로 작성한 MVP 요구사항 |
| `week2-schema-definition.md` | 일부 확정·일부 제안 | 화면·API·LLM 공통 필드명의 단일 기준 |
| `week2-contract-review-checklist.md` | 결정 반영 | Week 2 결정과 후속 Target 기록 |
| `current-mvp-implementation-baseline.md` | 코드 확인 | 현행 실행 코드의 역할·API·화면·fallback 기준선 |
| `week2-report-specification.md` | 초안 | LLM 보고서 입력·출력·근거·문장·fallback 계약 |
| `week2-functional-specification.md` | 초안 | 화면별 기능·처리·오류·완료 조건 |
| `week2-api-specification.md` | 초안 | 팀원3 조회·집계 API와 팀원4 리포트 API 계약 |
| `week2-mvp-design-specification.md` | 초안 | 시스템·데이터·화면·역할·구현 흐름 |
| `week2-traceability-matrix.md` | 초안 | 요구사항부터 테스트까지 연결 |
| `week2-prototype-doc-migration-map.md` | 이관 기록 | 개인 프로토타입 상세 문서와 팀 기준 문서의 대응 관계 |
| `prototype-source/` | 원문 보존 | 개인 레포의 Week 2 상세 문서 4종을 내용 변경 없이 보존 |

## 기준 자료

- Dataset: `canonical-ai4i-physics-v3.1`
- Model: `independent-logreg-v3.1`
- Result Artifact: `result-artifact-v1.0`
- 제품 문서 저장소: `Biz-CollabCraft/ontology_dashboard`
- 비교 프로토타입: `oosuhada/agentic-ontology-dashboard`

비교 프로토타입은 기능과 계약의 참고 구현이며 이 저장소의 확정 요구사항 또는
Git 기준 브랜치가 아니다.

## 공유하지 않는 자료

- V1.1/V1.3 기반 기존 샘플과 스키마를 확정 계약으로 공유하지 않는다.
- Canonical ZIP과 대용량 CSV/JSONL은 이 문서 폴더에 복사하지 않는다.
- evaluation truth는 제품 화면·일반 API 자료로 공유하지 않는다.
- `.env`, API key, credential, 로그, cache, 가상환경을 포함하지 않는다.

## 다음 산출물

필수 Week 2 문서와 현행 구현 기준선은 작성됐고 제품·리포트 계약 결정을 반영했다.
남은 저장소 통합 방식과 실제 구현 결과는 후속 결정 및 테스트 이름과 함께 기록한다.

공통 필드명의 최종 단일 기준은 `week2-schema-definition.md`로 한다.

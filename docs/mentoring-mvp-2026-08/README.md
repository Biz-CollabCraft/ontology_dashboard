# 팀 공유 문서 — Mentoring MVP 2026-08

이 폴더는 팀원2가 관리하는 제품·데이터·화면·API·LLM 계약의 공유 위치다.
문서는 검증된 사실, 제안, 미결 결정을 구분한다.

## 읽는 순서

1. [Canonical V3.1 필드 검증표](./v3.1-field-validation.md)
2. [프로토타입과 멘토링 MVP 차이 분석](./prototype-mvp-gap-analysis.md)
3. [Week 2 요구사항 명세 초안](./week2-requirements-specification.md)
4. [Week 2 공통 스키마 정의서](./week2-schema-definition.md)
5. [Week 2 계약 검토 체크리스트](./week2-contract-review-checklist.md)
6. [Week 2 리포트 정의서](./week2-report-specification.md)
7. [Week 2 기능 명세서](./week2-functional-specification.md)
8. [Week 2 API 명세서](./week2-api-specification.md)
9. [Week 2 MVP 설계 명세서](./week2-mvp-design-specification.md)
10. [Week 2 추적성 매트릭스](./week2-traceability-matrix.md)

## 문서 상태

| 문서 | 상태 | 용도 |
|---|---|---|
| `v3.1-field-validation.md` | 검증 완료 | 공식 V3.1과 기존 V1.1/V1.3 초안의 필드 차이 근거 |
| `prototype-mvp-gap-analysis.md` | 팀 합의 필요 | 프로토타입을 유지·수정·제외할 항목 결정 |
| `week2-requirements-specification.md` | 초안 | 검증된 범위로 작성한 MVP 요구사항 |
| `week2-schema-definition.md` | 일부 확정·일부 제안 | 화면·API·LLM 공통 필드명의 단일 기준 |
| `week2-contract-review-checklist.md` | 팀 답변 필요 | 담당자별 선택안·결정·근거 기록 |
| `week2-report-specification.md` | 초안 | LLM 보고서 입력·출력·근거·문장·fallback 계약 |
| `week2-functional-specification.md` | 초안 | 화면별 기능·처리·오류·완료 조건 |
| `week2-api-specification.md` | 초안 | 조회·보고서 API 요청·응답·오류 계약 |
| `week2-mvp-design-specification.md` | 초안 | 시스템·데이터·화면·역할·구현 흐름 |
| `week2-traceability-matrix.md` | 초안 | 요구사항부터 테스트까지 연결 |

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

필수 Week 2 문서 초안은 모두 작성됐다. 팀 합의 후 각 문서의 `제안`과
`확인 필요` 항목을 확정하고 실제 API 경로·테스트 이름으로 교체한다.

공통 필드명의 최종 단일 기준은 `week2-schema-definition.md`로 한다.

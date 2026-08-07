# 팀 공유 문서 — Mentoring MVP 2026-08

이 폴더는 팀원2가 관리하는 제품·데이터·화면·API·LLM 계약의 공유 위치다.
문서는 검증된 사실, 제안, 미결 결정을 구분한다.

## 읽는 순서

1. [Canonical V3.1 필드 검증표](./v3.1-field-validation.md)
2. [프로토타입과 멘토링 MVP 차이 분석](./prototype-mvp-gap-analysis.md)
3. [Week 2 요구사항 명세 초안](./week2-requirements-specification.md)

## 문서 상태

| 문서 | 상태 | 용도 |
|---|---|---|
| `v3.1-field-validation.md` | 검증 완료 | 공식 V3.1과 기존 V1.1/V1.3 초안의 필드 차이 근거 |
| `prototype-mvp-gap-analysis.md` | 팀 합의 필요 | 프로토타입을 유지·수정·제외할 항목 결정 |
| `week2-requirements-specification.md` | 초안 | 검증된 범위로 작성한 MVP 요구사항 |

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

팀 합의 후 이 폴더에 다음 문서를 추가한다.

- `week2-schema-definition.md`
- `week2-functional-specification.md`
- `week2-api-specification.md`
- `week2-report-specification.md`
- `week2-mvp-design-specification.md`
- `week2-traceability-matrix.md`

공통 필드명의 최종 단일 기준은 `week2-schema-definition.md`로 한다.

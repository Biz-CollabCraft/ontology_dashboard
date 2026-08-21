# Shared Contracts

이 디렉터리는 Generator, Backend, Frontend 등 둘 이상의 시스템이 공유하는
기계 판독 계약을 관리하기 위한 저장소 최상위 위치다.

현재 공유 JSON Schema는 `contracts/schemas/`로 물리 이동이 완료되었으며,
관련 코드·스크립트·테스트·CI·Docker·문서 참조가 모두 이 디렉터리를 정본으로 바라보도록 설정되어 있다.

## Directory layout

### `schemas/`
여러 시스템이 공유하는 JSON Schema를 보관한다.
기존 최상위 `schemas/` 위치의 17개 공유 JSON Schema는 `contracts/schemas/`로 물리 이전을 완료하였다.

### `openapi/`
시스템 경계를 통과하는 공유 API 계약을 보관한다.
Generator 내부 API나 Backend 공개 API가 실제 OpenAPI 계약으로 확정된 경우에만
파일을 추가한다. 미결정 API를 placeholder 계약으로 만들지 않는다.

### `examples/`
공유 Schema 또는 API 계약을 만족하는 대표 payload 예시를 보관한다.
예시는 반드시 해당 계약의 검증을 통과해야 하며, `"..."` 같은 실행 불가능한
placeholder 값을 사용하지 않는다.

### `test-vectors/`
Producer와 Consumer 사이의 계약 호환성을 검증하는 고정 입력과 기대 결과를 보관한다.
Schema validation, Publisher/Loader round-trip, Feature parity, Label boundary 등
실제 자동 검증에서 사용하는 자료만 추가한다.

## Current status

현재 `contracts/`의 관리 상태는 다음과 같다.

- `contracts/schemas/`: 17개 공유 JSON Schema 물리 이동 및 정본 관리 완료
- `project_root()` 마커, `Dockerfile`, `render.yaml`, CI(`architecture.yml`, `backend-contract-ci.yml`), `scripts/`, `tests/` 참조 전환 완료
- Schema 내용 및 `$id` 식별자 무변경 보존
- `openapi/`, `examples/`, `test-vectors/`: 향후 구체적 요구사항 확정 시 순차적으로 이식 예정

## Generator 파이프라인 후속 Target 계약 후보 및 계획

Generator 구조 개편 및 파일 가공 파이프라인(Observation/Feature Series 생산자 확립 및 Layer 2 프로토콜 정규화 작업)을 위한 후속 Target Schema 목록과 상태는 다음과 같습니다.

```text
contracts/schemas/ (후속 Target 계약 후보 목록)
├─ generator-observation.schema.json
├─ generator-failure-event.schema.json
├─ generator-extraction-result.schema.json
├─ generator-preprocessing-plan.schema.json
└─ generator-feature-series.schema.json
```

### Target 계약 상태 표

| 계약 | 현재 상태 | 설명 |
|---|---|---|
| Observation Reference Fixture | 참고 fixture 존재 | `tests/fixtures/gen_data_layer2_observation/` (참고용) |
| Generator Observation Schema | **Target — 미작성** | 후속 Extraction 구현 작업에서 작성 예정 |
| Generator Failure Event Schema | **Target — 미작성** | 후속 Extraction 구현 작업에서 작성 예정 |
| Generator Extraction Result Schema | **Target — 미작성** | 후속 Extraction 구현 작업에서 작성 예정 |
| Generator Preprocessing Plan Schema | **Target — 기존 Extraction Plan 검토 후 이전** | 기존 Extraction Plan 스키마 검토 후 migration 예정 |
| Generator Feature Series Schema | **Target — 미작성** | 후속 Feature 구현 작업에서 작성 예정 |
| Feature Dataset Bundle | **Target — 기존 Schema 재사용·확장 여부 검토 필요** | 기존 `dataset-bundle-manifest.schema.json`의 재사용 가능성을 우선 검토 |

### Target 계약 관리 원칙

- **문서 전용 브랜치 원칙**: 본 브랜치에서는 빈 파일이나 placeholder Schema를 일체 생성하지 않으며, 실제 스키마 생성은 별도 계약·구현 작업에서 수행합니다.
- **기존 계약 재사용 우선**: 기존 계약으로 표현 가능한 경우 새 스키마를 중복 생성하지 않습니다.
- **Feature Dataset Bundle 재사용 검토**: Feature Dataset Bundle의 경우 신규 스키마를 추가하기 전에 기존 `dataset-bundle-manifest.schema.json`의 재사용 및 확장 가능성을 먼저 검토합니다.

### 스키마 이관 브랜치 rebase 후 수행할 정합성 검증 항목

별도 스키마 물리 이관 작업이 완료되고 본 브랜치가 rebase된 후에는 다음 검증을 순차적으로 수행합니다:
1. 실제 `contracts/schemas/` 목록과 문서 목록 1:1 비교
2. 문서 내 `미작성`, `이전 예정` 상태 태그 갱신
3. `$id`와 `$ref` 검증
4. 스키마 경로 참조 검증
5. 예시 JSON과 JSON Schema 정합성 검증 (Draft 2020-12)
6. API 모델과 Schema 필드 정합성 검증
7. 기존 스키마와 신규 스키마의 역할 중복 검사

## Migration principle

향후 추가 Migration에서는 실제로 존재하고 시스템이 사용하는 계약만 이전한다.
존재하지 않는 Schema를 목표 구조를 채우기 위해 새로 만들지 않는다.
사용 여부가 불명확한 파일은 삭제하지 않으며 먼저 생산자·소비자·테스트 참조를 확인한다.

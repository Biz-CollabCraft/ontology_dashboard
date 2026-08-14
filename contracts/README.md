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

## Migration principle

향후 추가 Migration에서는 실제로 존재하고 시스템이 사용하는 계약만 이전한다.
존재하지 않는 Schema를 목표 구조를 채우기 위해 새로 만들지 않는다.
사용 여부가 불명확한 파일은 삭제하지 않으며 먼저 생산자·소비자·테스트 참조를 확인한다.

# Shared Contracts

이 디렉터리는 Generator, Backend, Frontend 등 둘 이상의 시스템이 공유하는
기계 판독 계약을 관리하기 위한 저장소 최상위 위치다.

현재 단계에서는 향후 계약 이전을 위한 디렉터리 골격만 구성한다.
기존 `schemas/` 파일과 코드·테스트·문서 참조는 아직 변경하지 않는다.

## Directory layout

### `schemas/`
여러 시스템이 공유하는 JSON Schema를 보관한다.
현재 기존 Schema는 저장소 최상위 `schemas/`에 유지한다.
실제 Schema 이전과 참조 경로 갱신은 별도 Migration PR에서 수행한다.

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

현재 `contracts/`는 디렉터리 구조와 관리 목적만 정의한다.

- 기존 `schemas/` 파일 이동 없음
- Schema 파일명 변경 없음
- Schema 내용 및 version 변경 없음
- 코드·테스트·CI·Docker 경로 변경 없음
- OpenAPI·Example·Test Vector 신규 생성 없음
- 기존 `schemas/` 삭제 없음

실제 Migration은 활성 Schema, 생산자, 소비자, 테스트 및 Docker 경로를 확인한 뒤
별도 PR에서 수행한다.

## Migration principle

향후 Migration에서는 실제로 존재하고 시스템이 사용하는 계약만 이전한다.
존재하지 않는 Schema를 목표 구조를 채우기 위해 새로 만들지 않는다.
사용 여부가 불명확한 파일은 삭제하지 않으며 먼저 생산자·소비자·테스트 참조를 확인한다.

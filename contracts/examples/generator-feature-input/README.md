# Generator Feature Input Contract Examples

본 디렉터리는 Generator `POST /feature` 엔드포인트의 입력 계약 및 Versioned Dataset Manifest 예제를 제공합니다.

## 구성 파일

- `observation-dataset-manifest.json`: Versioned Observation Dataset Manifest 예시 (`generator-dataset-input-manifest.schema.json` 검증 대상)
- `failure-dataset-manifest.json`: Versioned Failure Dataset Manifest 예시 (`generator-dataset-input-manifest.schema.json` 검증 대상)
- `feature-request.external.json`: 외부 Failure Dataset을 참조하는 `FeatureRequest` 예시
- `feature-request.embedded.json`: Observation 내부 indicator를 참조하는 `FeatureRequest` 예시

모든 예제 파일은 자동 JSON Schema 및 Pydantic 유효성 검사 테스트 대상입니다.

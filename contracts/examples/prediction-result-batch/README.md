# Prediction Result Batch Contract Examples

본 디렉터리는 Generator Runtime이 Backend Prediction Inbox로 전달하는
`prediction-result-batch-v1` 예제를 보관한다.

이 계약은 Product Result Artifact나 Event Evidence가 아니다. Backend가 batch의
contract, scope, checksum, lineage, idempotency를 검증하고 product policy를 적용한 뒤에만
Product Result/Evidence로 승격할 수 있다.

## 구성 파일

- `live-predicted.json`: live sensor observation에서 정상 raw score가 생성된 예시
- `maintenance-history-insufficient.json`: maintenance replay source에서 이력 부족으로 Product Result를 만들 수 없는 예시

두 예제 모두 `contracts/schemas/prediction-result-batch.schema.json` 검증 대상이다.

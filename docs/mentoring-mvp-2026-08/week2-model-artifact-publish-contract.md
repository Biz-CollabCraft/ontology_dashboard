# Week 2 Model Artifact Publish 계약 명세서

- **문서 상태**: `목표 계약 (Target Specification)` — PR #22 구현 예정
- **관련 저장소**: `Biz-CollabCraft/ontology_dashboard`
- **대상 파이프라인**: `systems/generator/model` (`model_registry.py`, `model_store`) & `systems/backend/app/diagnosis`

---

## 1. Model Artifact 개념 및 책임 경계

- **Model Artifact**: `systems/generator`가 학습/평가를 완료한 후 발행하는 불변(Immutable) 산출물 패키지.
- **주입 방식**: 환경 변수 `MODEL_ARTIFACT_URI` 또는 Provider 서비스 인터페이스를 통해 `systems/backend`로 주입된다.
- **Backend 탐색 금지**: `systems/backend`는 sibling 경로 (`../generator/...`)나 물리 디렉터리를 정적으로 탐색하는 것을 엄격히 금지한다.

---

## 2. Model Artifact 필수 구성 요소 (PR #22 구현 예정)

발행된 Model Artifact 패키지에는 다음 파일들이 포함되어야 한다.

| 파일명 | 역할 및 내용 |
|---|---|
| `manifest.json` | artifact_type, model_id, model_version, dataset_version, schema versions, checksum 메타데이터 |
| `model.joblib` | 학습 완료된 추론 모델 객체 |
| `feature_schema.json` | 입력 피처 계약 버전 및 피처 이름/타입/파라미터 명세 |
| `label_schema.json` | 타겟 라벨 호라이즌 및 구간 정의 계약 명세 |
| `history_requirement.json` | Backend 추론 시 필요한 과거 관측 시계열 조건 (`minimum_history_rows`, `maximum_lookback_hours` 등) |
| `metrics.json` | 오프라인 모델 평가 지표 요약 |

---

## 3. History Requirement 및 Backend Runtime Feature Execution (ADR-002 연동)

rolling mean/std, lag, EMA 등의 시계열 피처는 단일 Current Observation만으로 계산할 수 없으므로 `history_requirement.json` 계약에 따라 Backend가 자산별 관측 이력을 로드하여 피처를 재현한다.

```json
{
  "partition_by": "asset_id",
  "order_by": "observed_at",
  "minimum_history_rows": 10,
  "maximum_lookback_hours": 24,
  "duplicate_policy": "error",
  "missing_history_policy": "fail"
}
```

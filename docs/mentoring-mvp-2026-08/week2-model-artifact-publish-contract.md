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

---

## 4. Run Registry와 Model Artifact의 책임 분리

| 구분 | Run registry | Model Artifact |
|---|---|---|
| 목적 | 내부 운영 메타데이터 (어떤 run이 언제 실행됐는지) | Backend가 신뢰하고 로드하는 제품 계약 |
| 불변성 | 매 run마다 갱신됨 | `model_version` 단위로 immutable |
| 소비자 | 팀 내부 | `systems/backend/app/diagnosis` |

두 책임을 분리한다. run registry(`models_store/registry.json`)만 구현하고
Model Artifact publish API를 생략하지 않는다. run registry에만 기록하고
publish를 생략하면 Backend가 새 모델을 영구히 로드할 수 없다.

---

## 5. Immutable publish 규칙

- `model_version`은 `model_id`별로 독립적으로 증가한다. 한 run에서 일부 모델만
  성공해도 성공한 모델만 새 version을 받는다.
- 동일 `model_version`으로 재publish를 시도하면 명시적으로 실패시킨다
  (`FileExistsError` 또는 동등한 예외). 기존 파일을 덮어쓰지 않는다.

---

## 6. Atomic publish

- publish는 임시 디렉터리에 전체 파일 집합(`manifest.json`, `model.*`,
  `feature_schema.json`, `label_schema.json`, `history_requirement.json`,
  `metrics.json`)을 먼저 완성한 뒤, 최종 위치로 원자적 연산(`os.replace()`
  또는 동등한 방식)으로 이동한다.
- publish 도중 예외가 발생하면 목적지에 부분 결과가 남지 않는다.
- publish 실패 시 run registry도 갱신하지 않는다 — registry에 기록된 version은
  항상 실제로 publish가 완료된 version이어야 한다.

---

## 7. Checksum 검증

- `manifest.json`의 `checksum`은 `model.*` 파일에 대해 계산한 SHA-256 값이다.
- consumer(Backend `artifact_provider.py`)는 로드 전 이 checksum을 실제 파일과
  대조해 검증한다. 불일치 시 명시적으로 실패시키고 임의의 sibling 파일로
  대체하지 않는다.

---

## 8. 공개 API 유지

- 기존 `publish_model_artifact()`, `validate_manifest()`, `ModelRegistry` 공개
  API를 삭제하지 않고 유지한다.
- `train_and_publish_model` 심볼은 `ml/src/factory_signal_ml/cli.py`,
  `tests/test_system_ownership.py`가 이미 import하고 있으므로 이름을 바꾸지
  않는다.

---

## 9. 완료 조건 (§4~§8 보강분)

- [ ] `publish_model_artifact()`, `validate_manifest()`, `ModelRegistry`가 존재한다.
- [ ] 동일 `model_version` 재publish가 명시적으로 실패한다.
- [ ] publish 도중 예외 발생 시 목적지에 부분 결과가 남지 않는다 (atomic).
- [ ] publish 실패 시 run registry가 갱신되지 않는다.
- [ ] Backend `artifact_provider.py`가 checksum 불일치 시 명시적으로 실패한다.
- [ ] 기존 공개 파사드 심볼이 유지되어 기존 import가 깨지지 않는다.

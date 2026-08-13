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
  "expected_sampling_interval_seconds": 3600,
  "minimum_history_rows": 10,
  "maximum_lookback_hours": 24,
  "history_sufficiency_policy": "decision-required",
  "missing_history_policy": "fail"
}
```

> 아래 값은 설명용 예시이며 전역 고정값이 아니다.
> `expected_sampling_interval_seconds`, `minimum_history_rows`,
> `maximum_lookback_hours`는 학습 데이터 프로파일과 Feature Schema에 따라
> Artifact publish 시 결정한다.

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

## 7. Manifest `checksum`과 `artifact_files`의 관계

Backend `artifact_provider.py`의 `REQUIRED_MANIFEST_FIELDS`는 최상위
`checksum`과 `artifact_files`를 **둘 다** 필수 필드로 요구한다. 두 필드의
역할을 아래처럼 명확히 구분한다.

| 필드 | 상태 | 역할 |
|---|---|---|
| `checksum` (최상위) | **deprecated, 존재만 요구** | 값은 로더에서 직접 검증되지 않으나 하위 호환을 위해 유지한다 (`manifest.checksum = artifact_files에서 role="model"인 파일의 SHA-256`으로 고정) |
| `artifact_files[*].sha256` | **canonical, 실제 검증 대상** | consumer가 로드 전 개별 파일의 실제 SHA-256과 대조 검증 |

**결정**: 최상위 `checksum`은 canonical 무결성 계약에서 제외하고
deprecated 필드로 유지하되, publish 시 값은 항상 `artifact_files`에서 `role="model"`인 파일의 SHA-256으로 통일하여 명시한다 (임의의 플레이스홀더 허용 안 함).

**후속 결정 필요**: 다음 `artifact_schema_version`(`model-artifact-v1.1`
이상)에서 최상위 `checksum`을 `REQUIRED_MANIFEST_FIELDS`에서 완전히
제거할지는 Backend 담당자와 별도로 결정한다. 이번 문서 보강 범위에는
포함하지 않는다.

---

## 8. Manifest `artifact_files`와 파일별 Checksum 검증

`artifact_files`는 파일별 checksum을 갖는 객체 배열이다. 단일 `checksum`
필드가 아니다 — 이는 이미 Backend `artifact_provider.py`가 요구하는 형식이다.

```json
{
  "artifact_files": [
    { "role": "model", "path": "model.joblib", "sha256": "..." },
    { "role": "feature_schema", "path": "feature_schema.json", "sha256": "..." },
    { "role": "label_schema", "path": "label_schema.json", "sha256": "..." },
    { "role": "history_requirement", "path": "history_requirement.json", "sha256": "..." },
    { "role": "metrics", "path": "metrics.json", "sha256": "..." }
  ]
}
```

- `role: "model"`, `role: "feature_schema"`는 Backend가 이미 필수로 요구한다
  (`artifact_provider.py`의 `required_role` 검사).
- `label_schema`, `history_requirement`, `metrics`도 이번 계약으로 필수
  `artifact_files` 항목에 추가한다. Backend의 필수 role 목록도 함께 갱신한다
  (PR #22와 Backend 측 변경을 함께 진행).
- consumer는 `artifact_files`에 선언된 **모든 파일**에 대해 개별 SHA-256을
  검증한다. 하나라도 불일치하면 명시적으로 실패시키고 임의의 sibling 파일로
  대체하지 않는다.

> `label_schema`, `history_requirement`, `metrics`를 필수 role로 승격하면
> 기존 `model-artifact-v1.0`과 호환되지 않는 breaking change가 된다.
> Artifact schema version, v1.0 호환 정책 및 Backend 배포 순서는 팀 결정
> 전까지 `Proposed / 결정 대기` 상태로 유지한다.

---

## 9. 공개 API 유지

- 기존 `publish_model_artifact()`, `validate_manifest()`, `ModelRegistry` 공개
  API를 삭제하지 않고 유지한다.
- `train_and_publish_model` 심볼은 `ml/src/factory_signal_ml/cli.py`,
  `tests/test_system_ownership.py`가 이미 import하고 있으므로 이름을 바꾸지
  않는다.

---

## 10. 완료 조건

- [ ] `publish_model_artifact()`, `validate_manifest()`, `ModelRegistry`가 존재한다.
- [ ] 동일 `model_version` 재publish가 명시적으로 실패한다.
- [ ] publish 도중 예외 발생 시 목적지에 부분 결과가 남지 않는다 (atomic).
- [ ] publish 실패 시 run registry가 갱신되지 않는다.
- [ ] `artifact_files`의 모든 항목이 개별 SHA-256으로 검증된다.
- [ ] 최상위 `checksum` 필드가 deprecated로 명시되며 `manifest.checksum = artifact_files[role="model"].sha256`으로 값이 통일된다.
- [ ] deprecated 최상위 `checksum`에 대한 계약 테스트가 추가된다: `manifest["checksum"] == next(item["sha256"] for item in manifest["artifact_files"] if item["role"] == "model")`
- [ ] Backend `artifact_provider.py`의 필수 role 목록이 `label_schema`, `history_requirement`를 포함하도록 갱신된다.
- [ ] 기존 공개 파사드 심볼이 유지되어 기존 import가 깨지지 않는다.

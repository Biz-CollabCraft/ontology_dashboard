# Week 2 Generator Feature & Label 계약 명세서

- **문서 상태**: `목표 계약 (Target Specification)` — 부분 구현 완료, 피처 네이밍/스키마 발행 후속 수용 예정
- **관련 저장소**: `Biz-CollabCraft/ontology_dashboard`
- **대상 파이프라인**: `systems/generator/feature` (`feature_builder.py`, `feature_label_service.py`)

---

## 1. Extraction Plan 및 데이터 분기 계약

`systems/generator/extraction` 파이프라인은 원본 DataFrame에서 다음 메타데이터를 추출한다.

| 메타데이터 | 역할 | 현행 상태 |
|---|---|---|
| `id_column` | 설비 식별자 (Asset Partition Key) | PR #21 구현 완료 |
| `time_column` | 관측 시각 (Canonical Time Ordering Key) | PR #21 구현 완료 |
| `duplicate_policy` | 중복 타임스탬프 처리 정책 (`aggregate`, `first`, `error`) | PR #21 구현 완료 |

### single_asset 및 Heuristic Fallback 정책
- 명시적으로 `single_asset=true`로 설정되거나 단일 설비 데이터셋임이 확인된 경우 단일 시계열 연산을 수행한다.
- `id_column` 식별 실패 시:
  - `production`, `staging` 환경: **Fail-Fast** 예외 발생.
  - `local`, `demo`, `test` 환경: 경고 로그(Warning) 출력 후 단일 시계열 분기로 수용.

---

## 2. Feature 격리 및 결정론적 계산 계약 (Invariants 15~17)

### 2.1 설비별 시계열 연산 격리 (Invariant 15)
- `rolling_mean`, `rolling_std`, `moving_average`, `diff` (gradient), `shift` (lag), `ema` 연산은 복수 설비 데이터 수용 시 **반드시 `df.groupby(id_col)` 내부에서 수행**한다.
- 설비 경계를 넘어 롤링 윈도우나 시프트 값이 누설(Leakage)되는 것을 금지한다.
- **상태**: `결정 완료 / PR #21 구현 완료`

### 2.2 결정론적 타임스탬프 정렬 (Invariant 16)
- 입력 DataFrame의 행 순서 셔플에 영향을 받지 않도록 `canonicalize_timestamp_series`를 적용하고 `[id_col, time_col]` (또는 `[time_col]`) 기준 명시적 정렬(`sort_values().reset_index(drop=True)`)을 수행한다.
- **상태**: `결정 완료 / PR #21 구현 완료`

### 2.3 Feature Naming 및 Naming Collision 방지 (Invariant 17)
- **현행 (PR #21 초기)**: `{ontology_node}_{operation}` (예: `Vibration_rolling_mean`)
  - *문제점*: 동일 온톨로지 노드(`Vibration`)로 매핑된 복수 source column(`vibration_sensor_1`, `vibration_sensor_2`) 존재 시 덮어쓰기 충돌 발생.
- **목표 계약 (Target Specification)**:
  - 명시적 구분자 적용: `<source_field>__<ontology_node>__<operation>__<parameters>`
  - 예: `vibration_raw__Vibration__rolling_mean__window_5`
- **상태**: `목표 계약 / 구현 필요 (Target Contract)`

---

## 3. Label Horizon 및 구간 라벨링 계약 (Invariants 18~19)

### 3.1 예측 타스크 계약 (Invariant 18)
- `prediction_task`: `"binary_failure_within_horizon"`
- `prediction_horizon_hours`: 기본값 24시간

### 3.2 Label 구간 매칭 및 Active Failure 정책
- **구간 매칭 (Interval Metadata 존재 시)**:
  - `degradation start` ~ `failure point` 구간을 `label = 1`로 지정.
- **Lead Window 매칭 (단일 고장 시점 존재 시)**:
  - 고장발생 시점($T_{fail}$) 기준 사전 예측 호라이즌 구간 `[T_fail - horizon, T_fail)`을 `label = 1`로 지정.
  - 고장발생 당해 시점(anchor) 이후 active failure interval은 예측 입력/학습 피처에서 제외(Excluded)한다.
- **상태**: `목표 계약 / 구현 진행 중 (Target Contract)`

---

## 4. Feature / Label Schema 버전 관리

- **`feature_schema_version`**: `"pdm-feature-v2"`
- **`label_schema_version`**: `"pdm-label-v2"`
- 학습 실행 및 Model Artifact Publish 시 `feature_schema.json`과 `label_schema.json`이 함께 패키징되어 저장되어야 한다.
- **상태**: `목표 계약 / PR #22 구현 필요 (Target Contract)`

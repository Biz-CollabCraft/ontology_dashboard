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

failure metadata의 `time_columns`는 서로 다른 의미를 갖는 최소 2개의 역할로
**반드시 분리해서 받는다.** 하나의 `end_col`로 뭉뚱그려 선택하지 않는다.

| 역할 | semantic 태그 | 의미 |
|---|---|---|
| anchor | `failure_point` | 고장이 실제로 발생한 시점. positive 구간의 끝(제외) |
| exclusion_end | `period_end`, `maintenance_end` | 다운타임/정비 완료 시점. 이 시점까지는 학습에서 제외 |

**anchor(`failure_point`)가 metadata에 없으면 `period_end`나 `maintenance_end`를
anchor로 대신 쓰지 않는다.** 이 경우 §3.2가 아니라 §1의 fallback 정책(anchor 불명확
시 해당 이벤트 제외 또는 fail-fast)을 따른다.

**구간 매칭 (anchor 존재 시)**
- Positive 구간: `[degradation_start, failure_point)` — `failure_point` 자체는
  포함하지 않는다.
- 제외 구간: `[failure_point, exclusion_end]` (exclusion_end가 있는 경우) —
  이 구간은 정상도 예측 대상도 아니므로 최종 라벨 DataFrame에서 행 자체를
  제거한다. `label=0`으로 채우지 않는다.
- `exclusion_end`가 metadata에 없으면 제외 구간을 만들 수 없으므로, 최소한
  `failure_point` 자체 시점의 관측 행은 positive에서 제외한다 (경계 값 포함 금지).

**Lead Window 매칭 (구간 metadata 없이 단일 고장 시점만 존재 시)**
- 기존과 동일: `[T_fail - horizon, T_fail)`을 `label=1`로 지정.

**구현 요구사항 (PR #21)**
- `build_labels()`는 `start_col`(degradation_start), `anchor_col`
  (`failure_point`), `exclusion_end_col`(`period_end`/`maintenance_end`)를
  **서로 다른 변수로 분리**해서 받는다. 지금처럼 `end_col` 하나로 합쳐서 받지
  않는다.
- `anchor_col`을 찾지 못하면 `exclusion_end_col`로 대체하지 않는다 (§1 fallback
  정책 적용).
- 회귀 테스트: metadata가 `maintenance_end`만 갖고 `failure_point`가 없는
  케이스를 넣었을 때, 그 이벤트가 anchor 없이 임의로 positive/exclusion 처리되지
  않고 §1 fallback 정책대로 처리되는지 검증한다.

---

## 4. Feature / Label Schema 버전 관리

- **`feature_schema_version`**: `"pdm-feature-v2"`
- **`label_schema_version`**: `"pdm-label-v2"`
- 학습 실행 및 Model Artifact Publish 시 `feature_schema.json`과 `label_schema.json`이 함께 패키징되어 저장되어야 한다.
- **상태**: `목표 계약 / PR #22 구현 필요 (Target Contract)`

---

## 5. 완료 조건 (§3.2 보강분)

- [ ] `build_labels()`가 anchor(`failure_point`)와 exclusion_end (`period_end`/`maintenance_end`)를 별도 변수로 받는다.
- [ ] anchor 없이 exclusion_end만 있는 경우 anchor로 대체되지 않는다.
- [ ] 제외 구간(`[failure_point, exclusion_end]`)이 label=0이 아니라 행 자체 제거로 처리된다.
- [ ] anchor 부재 케이스에 대한 회귀 테스트가 존재한다.

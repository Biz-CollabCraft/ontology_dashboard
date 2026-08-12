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

- 현행: `id_column` 식별 실패 시 환경과 관계없이 경고 로그(Warning) 출력 후
  단일 시계열 분기로 처리한다. `single_asset` 필드는 아직 없다.
- 목표: 명시적 `single_asset` 플래그를 도입하고, `id_column` 식별 실패 시
  `production`/`staging` 환경에서는 Fail-Fast, `local`/`demo`/`test`
  환경에서는 경고 후 단일 시계열 분기로 분리한다.
- 상태: `목표 계약 / PR #21~#22 구현 필요 (Target Contract)`

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

**Positive interval은 metadata 형태와 무관하게 항상 다음 한 가지 의미로 통일한다.**

```text
[max(degradation_start, failure_point - prediction_horizon), failure_point)
```

- `degradation_start`(interval metadata의 `period_start`)가 없으면
  `failure_point - prediction_horizon`을 그대로 사용한다 (Lead Window 매칭과
  동일한 계산).
- `degradation_start`가 있고 `failure_point - prediction_horizon`보다 늦은
  시점이면(즉 열화가 horizon보다 짧게 시작됐으면) `degradation_start`부터
  positive로 잡는다 — 이 경우 실제 positive 구간이 `prediction_horizon`보다
  짧아질 수 있다. 이는 허용한다 (실제로 열화가 늦게 시작된 것이므로).
- `degradation_start`가 `failure_point - prediction_horizon`보다 이르면(열화가
  horizon보다 먼저 시작됐으면) `failure_point - prediction_horizon`으로 clip한다
  — positive 구간이 `prediction_horizon`을 절대 넘지 않는다.
- `degradation_start`는 이 clip 계산 외의 용도(데이터 품질 검증, 별도 열화 단계
  분석)로 별도 활용할 수 있으나, 그 경우 이 라벨 계약과는 별개의 산출물로
  취급한다.

**anchor(`failure_point`)를 metadata에서 찾을 수 없는 경우**

이 정책은 §1의 `id_column` fail-fast 정책과는 별개의 관심사이며, 환경
(`production`/`local`/`demo` 등)에 따라 분기하지 않는다.

- `degradation_start`는 있지만 anchor가 없으면: 해당 이벤트는 라벨링에서
  제외하고 warning을 남긴다. `period_end`/`maintenance_end`를 anchor로 대신
  쓰지 않는다.
- `degradation_start`도 anchor도 없으면: 해당 failure 소스 전체를 label 생성
  대상에서 제외하고 warning을 남긴다.

**제외 구간**
- `[failure_point, exclusion_end]` (exclusion_end가 있는 경우)는 정상도 예측
  대상도 아니므로 최종 라벨 DataFrame에서 행 자체를 제거한다. `label=0`으로
  채우지 않는다.
- `exclusion_end`가 없으면 최소한 `failure_point` 자체 시점의 관측 행은
  positive에서 제외한다 (경계 값 포함 금지).

**구현 요구사항 (PR #21)**
- `build_labels()`는 `start_col`(degradation_start), `anchor_col`
  (`failure_point`), `exclusion_end_col`(`period_end`/`maintenance_end`)를
  서로 다른 변수로 분리해서 받는다.
- 두 분기(interval metadata 있음/없음)가 최종적으로 동일한
  `max(degradation_start, anchor - horizon)` 계산 로직을 공유한다 — 별도
  마스킹 코드로 중복 구현하지 않는다.
- 회귀 테스트:
  - `degradation_start`가 `anchor - horizon`보다 이른 경우 positive 구간이
    `horizon`으로 clip되는지
  - `degradation_start`가 `anchor - horizon`보다 늦은 경우 `degradation_start`
    그대로 사용되는지
  - anchor 없이 exclusion_end만 있는 경우 anchor로 대체되지 않고 이벤트가
    제외되는지

---

## 4. Feature / Label Schema 버전 관리

- **`feature_schema_version`**: `"pdm-feature-v2"`
- **`label_schema_version`**: `"pdm-label-v2"`
- 학습 실행 및 Model Artifact Publish 시 `feature_schema.json`과 `label_schema.json`이 함께 패키징되어 저장되어야 한다.
- **상태**: `목표 계약 / PR #22 구현 필요 (Target Contract)`

---

## 5. 완료 조건 (§3.2 보강분)

- [ ] `build_labels()`가 anchor(`failure_point`)와 exclusion_end
      (`period_end`/`maintenance_end`)를 별도 변수로 받는다.
- [ ] interval metadata 있음/없음 두 분기가 동일한
      `max(degradation_start, anchor-horizon)` 계산을 공유한다.
- [ ] positive 구간이 `prediction_horizon`을 절대 넘지 않는다 (clip 검증).
- [ ] anchor 없이 exclusion_end만 있는 경우 anchor로 대체되지 않는다.
- [ ] 제외 구간이 label=0이 아니라 행 자체 제거로 처리된다.
- [ ] anchor 부재 케이스(§3.2 자체 정의, §1 참조 아님)에 대한 회귀 테스트가
      존재한다.

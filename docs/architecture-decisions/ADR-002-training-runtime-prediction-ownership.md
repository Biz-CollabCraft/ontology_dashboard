# ADR-002: Training과 Runtime Prediction 소유권 분리 및 Feature History Execution

- **상태**: Proposed (제안 — 목표 계약)
- **날짜**: 2026-08-12
- **결정자**: 팀 공통 (검토 진행 중)

---

## 1. 맥락 (Context)

- `systems/generator`는 학습과 Model Artifact publish까지만 소유하며, 사용자 요청 기반 추론(Runtime Inference) 및 Product Result Artifact 생성은 `systems/backend/app/diagnosis`가 소유한다.
- 그러나 rolling, lag, EMA 등 시계열 피처는 단일 Current Observation만으로 계산할 수 없으므로, Backend가 추론 시 피처를 재현하는 방식에 대한 명확한 결정이 필요하다.

---

## 2. 의사결정 (Decision)

1. **Model Artifact에 History Requirement 명시**:
   Model Artifact 패키지 내 `history_requirement.json`을 포함하여 추론에 필요한 과거 시계열 조건(`minimum_history_rows`, `maximum_lookback_hours`)을 명시한다.
2. **Backend Feature Executor 적용**:
   `systems/backend`는 `history_requirement.json`에 따라 자산별 시계열 history를 조회한 후 `feature_schema.json` 기반으로 피처를 재현한다.
3. **책임 경계 완전 격리**:
   `systems/backend`는 `systems/generator` 코드를 static/direct import 하지 않고 versioned Model Artifact만 소비한다.

---

## 3. 결과 및 영향 (Consequences)

- `history_requirement.json`은 Feature Parity에 필요한 **입력 이력 조건**
  (partition, order, minimum rows, lookback)을 정의한다. 실제 수치 재현
  parity는 이것만으로 보장되지 않는다.
- 완전한 parity는 다음이 추가로 확정되어야 보장된다: rolling `min_periods`,
  std `ddof`, EMA `adjust`, NaN/drop 정책, timestamp 중복 순서, dtype 변환,
  categorical preprocessing, transform executor 버전. 이 파라미터 집합은
  `feature_schema.json`의 각 feature 항목에 포함시키거나(권장), 별도
  versioned transform specification 문서로 분리한다.
- parity 보장 여부는 선언이 아니라 **golden-vector contract test**(고정된
  입력 → generator 산출 feature 벡터와 Backend 재현 feature 벡터가 완전
  일치하는지 비교하는 테스트)로 검증한다. 이 테스트가 없으면 parity가
  "보장"되었다고 표기하지 않는다.

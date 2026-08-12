# ADR-002: Training과 Runtime Prediction 소유권 분리 및 Feature History Execution

- **상태**: Accepted (의사결정 완료)
- **날짜**: 2026-08-12
- **결정자**: 팀 공통

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

- Training과 Runtime Inference 간 Feature Parity가 보장된다.
- Backend artifact validator 및 observation 조회 범위에 `history_requirement.json` 로직이 반영되어야 한다.

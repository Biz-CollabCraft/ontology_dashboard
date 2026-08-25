# ADR-003: Generator Runtime Prediction 및 Anomaly Signal 소유권 결정

- **상태**: Accepted (확정)
- **날짜**: 2026-08-25
- **결정자**: 팀 공통
- **선행/대체 문서**: [`ADR-002-training-runtime-prediction-ownership.md`](./ADR-002-training-runtime-prediction-ownership.md) (Superseded)

---

## 1. 맥락 (Context)

기존 ADR-002에서는 Generator가 학습과 Model Artifact 발행까지만 담당하고, Backend Diagnosis가 Model Artifact를 직접 로드하여 런타임 피처 계산과 추론을 수행하도록 제안되었다.

그러나 실제 운영 흐름에서 다음과 같은 문제점이 확인되었다:
1. **피처 엔지니어링 패리티 및 중복 구현**: Generator에서 학습 시 적용한 Feature Schema 및 시계열 변환(lag, rolling, diff, ewm 등) 로직을 Backend에서 완전히 동일하게 재현해야 하는 이중 유지보수 부담이 발생한다.
2. **시스템 역할과 책임의 단방향 흐름**: 관측 데이터는 `gen_data` → `Generator`로 전달되며, Generator가 이미 전처리(Preprocessing)와 피처(Feature) 생성 능력을 소유하고 있으므로, Generator가 런타임 추론과 모델 결과 취합까지 수행하고 이상 발생 시 Backend로 신호를 발행하는 구조가 파이프라인의 응집도를 극대화한다.
3. **Backend의 핵심 비즈니스 책임 집중**: Backend는 원시 센서값의 ML 연산 대신 이상 신호 수신, 센서 근거 조회, 설비 메타데이터 결합, 최종 Evidence 및 Report 생성, Dashboard 서빙에 집중하는 것이 도메인 경계상 명확하다.

---

## 2. 의사결정 (Decision)

1. **Generator의 런타임 예측 및 신호 발행 소유권**:
   - `systems/generator`가 관측 데이터의 전처리(Preprocessing), 설비별 시계열 피처 추출(Runtime Feature), 활성 Model Artifact 로드 및 다중 모델 추론(Runtime Prediction), 설비별 결과 취합(Aggregation)을 전담한다.
   - 하나 이상의 모델이 설비에 대해 이상으로 판정할 경우, Generator가 `AnomalySignal`을 발행한다.

2. **Backend의 이상 신호 소비 및 근거/리포트 생성 소유권**:
   - `systems/backend`는 Generator가 발행한 `AnomalySignal`을 수신(소비)한다.
   - 수신된 신호의 source lineage를 검증하고, 관련 센서 데이터와 설비 메타데이터를 조회하여 최종 Product Result Artifact, Evidence 및 Report를 생성하고 Dashboard API로 전달한다.

3. **시스템 간 엄격한 결합 분리**:
   - Generator와 Backend는 상호 Python 코드를 직접 import하지 않는다.
   - 오직 공식화된 `AnomalySignal Contract` (`contracts/schemas/generator-anomaly-signal.schema.json`) 및 불변 파일 참조(URI, SHA-256 Checksum)만을 유일한 경계로 사용한다.

4. **금지 범위 (Boundary Invariants)**:
   - Generator는 Product Result Artifact, Evidence, Report를 생성하지 않는다.
   - Frontend는 Generator API를 직접 호출하지 않으며 오직 Backend API만 소비한다.
   - 기존 Backend Diagnosis 코드는 이번 PR에서 삭제하지 않고, 새로운 신호 기반 흐름과의 통합은 별도 Backend 작업으로 추적한다.

---

## 3. 결과 및 영향 (Consequences)

- Generator는 학습(Training)뿐만 아니라 런타임 파이프라인(Runtime Pipeline) 워커와 Notification 워커를 소유한다.
- Backend는 ML 추론 엔진 의존성을 제거하고 도메인/온톨로지/리포트 비즈니스 로직에 집중할 수 있다.
- 이상 신호 전송 실패 시 Notification Outbox 패턴을 통해 동일 `event_id`로 안전하게 재시도되며, 파이프라인 전체를 불필요하게 재실행하지 않는다.

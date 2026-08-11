# 고장 전조 분석 및 예방조치 What-if 개발 계획

- 문서 상태: `실행 계획 · 팀 검토 필요`
- 기준일: `2026-08-11`
- 개발 브랜치: `feat/preventive-what-if-foundation`
- 발표일: `2026-09-11`
- 기준 데이터: `canonical-ai4i-physics-v3.1`
- 기준 모델: 기존 Prediction/Feature Engineering 계약 재사용

## 1. 문서 목적

이 문서는 Week 2 공통 결과 연결 이후 추가하는 **합성 반사실 예방조치 실험**의
개발 범위, 책임 경계, 데이터 계약, 일정과 완료 조건을 관리한다.

기존 Week 2 필수 MVP 계약을 변경하지 않고 별도 실험 계층으로 개발한다. 현재
Canonical V3.1, Prediction Timeline과 Result Artifact는 읽기 전용 기준으로
취급하며 What-if 결과를 기존 결과에 덮어쓰지 않는다.

## 2. 해결하려는 문제

현재 제품은 설비별 고장확률과 주요 요인을 제공한다. What-if 기능은 다음 질문에
답할 수 있는 구조화된 분석 결과를 추가한다.

1. 고장확률이 언제부터 상승했는가?
2. 상승 전후에 어떤 센서값이 달라졌는가?
3. 여러 상승 사례에서 반복되는 선행 지표는 무엇인가?
4. 예방조치를 적용하지 않은 경우와 적용한 경우의 예상 확률은 어떻게 달라지는가?
5. 예방조치 비용과 예상 고장 손실은 어떤 차이가 있는가?

결과는 실제 현장 효과가 아니라 Canonical V3.1과 기존 모델을 이용한
`synthetic_counterfactual_simulation`으로 표시한다.

## 3. 책임 경계

### 3.1 What-if Producer

What-if 모듈은 다음 값만 구조화해 생성한다.

- 위험 상승 시작·최고점·상승폭·지속시간
- 상승 전후 센서 통계
- 반복 선행 지표와 모델 기여도
- 조치 코드와 파라미터
- Baseline/Intervention 예상 확률과 감소량
- 예상 정지시간과 경제성 계산값
- Evidence reference, provenance, effect scope, limitation code

### 3.2 Producer에서 제외하는 것

- 관리자·현장 담당자용 최종 문장
- ReportOutput block과 LLM 호출
- 역할별 강조 순서
- UI 색상·아이콘·표시 문구
- 고장 원인 또는 예방 효과의 확정 표현
- 자동 정지·자동 정비 명령

### 3.3 Consumer

| 영역 | 소비 책임 |
|---|---|
| `final/map-report` | What-if Result를 역할별 ReportOutput과 자연어 문장으로 변환 |
| Dashboard | 확률·센서 차트, 상태 문구, 툴팁과 사용자 상호작용 |
| API | 분석 함수 호출, 결과 전달, 실행 상태와 오류 처리 |

## 4. 전체 처리 흐름

```text
Canonical V3.1 / Prediction Timeline
→ 고장확률 상승 사건 탐지
→ 상승 전후 센서 구간 비교
→ 반복 선행 지표 통계
→ 예방조치 후보 코드 선택
→ 조치 없음 Baseline 생성
→ 예방조치 Intervention 생성
→ 관련 시계열과 6시간 특징 재계산
→ 동일한 기존 모델로 재평가
→ 위험도·상태등급·비용 비교
→ 구조화된 What-if Result 생성
→ API / Dashboard / map-report가 소비
```

## 5. 입력 데이터

다음 Canonical V3.1 파일을 읽기 전용으로 사용한다.

- `prediction_timeline.jsonl`
- `cnc_sensor_observation.csv`
- `compressor_sensor_observation.csv`
- `cnc_production_cycle.csv`
- `maintenance_event.csv`
- `asset_master.csv`
- `asset_relation.csv`

Evaluation truth는 탐지율·선행시간 평가에만 사용하고 제품 API, Dashboard,
ReportInput과 ReportOutput에는 노출하지 않는다.

## 6. 별도 실험 데이터

기존 Canonical 파일을 변경하지 않고 다음 구조의 별도 파생 실험으로 관리한다.

```text
experiments/preventive_intervention/
├─ dataset/
├─ policies/
├─ simulator/
├─ schemas/
├─ generated/
├─ evaluation/
└─ tests/
```

### 6.1 고장 발생 이력

`failure_event_history.csv`

- `failure_event_id`, `asset_id`
- `detected_at`, `occurred_at`, `reported_at`
- `failure_mode`, `component_code`, `symptom_code`
- `severity`, `operating_impact`, `shutdown_required`
- `related_prediction_id`, `related_rise_event_id`
- `root_cause_status`, `confirmed_root_cause_code`
- `source_type`, `recorded_at`

Evaluation truth에서 변환할 경우 `occurred_at`이 지난 이벤트만 운영 이력으로 공개한다.

### 6.2 수리 작업·부품·비용·결과 이력

| 파일 | 역할 |
|---|---|
| `repair_work_order_history.csv` | 작업 유형, 조치 코드, 시작·완료·재가동 시각과 정지시간 |
| `repair_part_history.csv` | 교체 부품, 수량, 단가, 제거 상태와 설치 시각 |
| `repair_cost_history.csv` | 부품비·인건비·외주비·물류비·재가동 비용 |
| `repair_outcome_history.csv` | 수리 전후 위험도, 정상화 여부, 24시간·7일·30일 재발 |

고장, 수리 작업, 비용과 결과를 한 테이블에 합치지 않고
`failure_event_id → work_order_id → cost_id/outcome_id`로 연결한다.

### 6.3 예방조치 결정·실행 이력

| 파일 | 역할 |
|---|---|
| `intervention_decision.csv` | 추천 조치, 수락·거절·보류, 선택 조치와 정책 버전 |
| `intervention_outcome.csv` | 실제 실행 여부, 전후 위험도, 고장·정지시간·비용 결과 |

추천, 실행과 결과를 구분해야 향후 실제 treatment-effect 학습 데이터를 구성할 수 있다.

## 7. 경제성 데이터

### 7.1 설비 경제 기준

`asset_economic_master.csv`

- 취득·교체·설치 비용
- 기대 사용연수와 잔존가치
- 설비 중요도
- 통화, 유효기간, 가격 버전
- `source_type`, `source_reference`

설비 가격 전체는 전손 또는 교체 시나리오에서만 사용한다.

### 7.2 제품 경제 기준

`product_economic_master.csv`

- L/M/H 제품 유형
- 단위 판매가격과 변동비
- 단위 공헌이익
- 폐기·재작업 비용
- 통화, 유효기간과 가격 버전

생산중단 손실은 판매가격 전체가 아니라 단위 공헌이익으로 계산한다.

### 7.3 예방조치 기준

`maintenance_action_catalog.csv`

- `action_code`, 적용 설비와 고장 모드
- 기본 정지시간과 작업시간
- 부품비·인건비·외주비
- shutdown 필요 여부와 정책 버전
- 실제·견적·합성 가격 구분

실제 가격이 없으면 임의의 `0`이 아니라 `null`과 `source_type=missing`을 사용한다.

## 8. 위험 상승과 선행 지표 분석

설비별 Prediction Timeline에서 상승 시작·최고점·종료점, 확률 상승폭과 지속시간을
계산한다. 초기 임계값을 코드에 고정하지 않고 데이터 분포 분석 후 버전 있는 정책으로
관리한다.

센서별 정상 기준 구간과 위험 구간의 평균, 중앙값, 표준편차, 변화율, Z-score와
모델 contribution을 계산한다.

- CNC: 공기·공정 온도, 온도 차, RPM, Torque, Power, Tool wear, 제품 유형
- Compressor: 전압, 회전, 압력, 진동, 상대 진동 Z-score

최종 통계는 선행 지표별 동반 사건 수·비율·평균 변화량·평균 선행시간을 제공한다.
문서에 사용하는 숫자는 계약 설명용 예시와 실제 분석 결과를 명확히 구분한다.

## 9. 예방조치 시뮬레이션

### 9.1 Baseline

```text
현재 상태 유지
→ 예방조치 없음
→ 이후 시계열 생성
→ 시간창 Feature 재계산
→ 기존 모델 재평가
```

### 9.2 Intervention

```text
동일 초기 상태
→ 예방조치 적용
→ 연결된 물리값과 이후 시계열 재계산
→ 동일 Feature Engineering
→ 동일 모델 재평가
```

### 9.3 구현 순서

| 순서 | `action_code` | 내용 | 대상 |
|---:|---|---|---|
| 1 | `TOOL_REPLACEMENT` | Tool wear 초기화와 이후 마모 재계산 | TWF·OSF |
| 2 | `CUTTING_LOAD_REDUCTION` | Torque와 제품 부하 조정 | OSF·PWF |
| 3 | `COOLING_SYSTEM_RESTORE` | 공정·공기 온도 차 정상화 | HDF |

RNF는 센서 조건과 무관하므로 예방조치 효과 비교 대상에서 제외한다.

## 10. 모델 범위

초기 단계에서는 새로운 머신러닝 모델을 만들지 않는다.

```text
기존 모델
+ 기존 Feature Engineering
+ 새 예방조치 시뮬레이터
```

기존 모델의 특징, 가중치와 임계값을 변경하지 않는다. 조치/미조치 시계열에 동일한
특징 계산과 추론을 적용한다. 합성 조치 쌍이 충분히 축적된 후에만 별도
treatment-effect 모델을 후속 검토한다.

## 11. 경제성 계산

```text
고장 발생 손실
= 직접 수리비
+ 생산중단 손실
+ 폐기·재작업 비용
+ 재가동 비용
```

```text
생산중단 손실
= 미생산 예상 수량 × 제품 유형별 단위 공헌이익
```

```text
Baseline 기대손실
= baseline_probability × 고장 발생 시 예상 손실
```

```text
Intervention 기대비용
= 예방조치 직접비
+ 예방조치 정지손실
+ intervention_probability × 고장 발생 시 예상 손실
```

```text
예상 순편익
= Baseline 기대손실 - Intervention 기대비용
```

모든 경제 결과는 `synthetic_scenario_estimate`로 표시하고 실제 절감액처럼 표현하지 않는다.

## 12. 구현 기준 경로

| 경로 | 역할 | 현재 상태 |
|---|---|---|
| `experiments/preventive_intervention/contracts.py` | Pydantic 입출력 계약과 검증 규칙 | 구현 완료 |
| `experiments/preventive_intervention/policies.py` | 비파괴 예방조치 변환 | 공구 교체 구현 완료 |
| `experiments/preventive_intervention/policies/tool-replacement-v1.json` | 공구 교체 정책 | 구현 완료 |
| `schemas/preventive-what-if.schema.json` | Producer JSON Schema | 구현 완료 |
| `data/fixtures/what_if/` | 계약 fixture | 1건 작성 완료 |
| `tests/test_preventive_what_if_foundation.py` | 계약·정책 불변성 테스트 | 작성 완료 |
| `experiments/preventive_intervention/` | 비배포 계약·정책 producer 및 향후 시계열 실험 | 기반 구현 완료, 실제 시계열 출력 미구현 |

## 13. 현재 구현 상태

### 완료

- [O] `main` 기준 독립 브랜치 생성
- [O] What-if Result Pydantic 계약
- [O] Draft 2020-12 JSON Schema
- [O] `TOOL_REPLACEMENT` 정책 계약
- [O] 원본 관측을 변경하지 않는 공구 교체 변환
- [O] 계약 fixture와 검증 테스트
- [O] Producer 결과에서 역할별 Report 필드 제외
- [O] What-if를 비배포 Experiment 계층으로 명문화
- [O] 공구 교체 typed parameter와 cross-field 의미 검증
- [O] 상승 시작부터 peak까지의 시간을 `time_to_peak_hours`로 명확화

### 다음 작업

- [ ] Canonical V3.1 공구 마모 위험 사례 선정
- [ ] 상승 사건 탐지 기준의 데이터 분포 분석
- [ ] Baseline/Intervention 시간창 생성
- [ ] 조치 후 공구 마모 누적과 생산·정비 상태 재계산
- [ ] 기존 Feature Engineering 재사용
- [ ] 동일 모델로 확률 재평가
- [ ] 실제 실행 결과 fixture로 계약 예시 교체
- [ ] 고장·수리·경제 확장 데이터 Schema 구현

현재 `82% → 21%` 같은 값은 계약 구조 설명용 fixture이며 실제 시뮬레이션 성능
결과가 아니다.

## 14. 주차별 계획

### Week 2 — 2026-08-10~08-16

- Producer/Consumer 책임과 입력·출력 계약 확정
- 공구 교체 정책과 계약 fixture
- 고장·수리·예방조치·경제 데이터 Schema 설계
- 기존 Feature Engineering·추론 인터페이스 확인

### Week 3 — 2026-08-17~08-23

- Prediction Timeline 기반 위험 상승 탐지
- 센서 시간 정렬과 구간 비교
- 선행 지표 통계와 사전 탐지시간 평가
- `risk-rise-events.jsonl` 생성

### Week 4 — 2026-08-24~08-30

- 공구 교체 Baseline/Intervention 시계열 생성
- 6시간 Feature 재계산
- 동일 모델 재평가와 위험 감소량 계산
- 재현성·물리 규칙·Canonical 불변 검증

### Week 5 — 2026-08-31~09-06

- 가공 부하 완화·냉각 복원 확장
- 고장·수리 이력과 경제성 계산 연결
- API·Dashboard·`map-report` 통합

### 발표 주 — 2026-09-07~09-11

- 테스트와 데모 시나리오 고정
- 수치·단위·시간대·truth 비노출 검증
- 합성 효과와 실제 효과의 한계 표시
- 발표 자료와 백업 시연 준비

## 15. 팀 합의 필요 사항

| ID | 결정 사항 | 영향 |
|---|---|---|
| `WIF-DEC-01` | 기존 Feature Engineering과 추론 함수 재사용 인터페이스 | Week 4 모델 재평가 |
| `WIF-DEC-02` | **결정 완료:** `experiments/preventive_intervention` 비배포 계층 | 제품 system과 분리하고 Artifact/API 계약으로만 연결 |
| `WIF-DEC-03` | What-if Result의 ReportInput 연결 방식 | `map-report` 통합 |
| `WIF-DEC-04` | `action_code`, limitation code, Evidence reference 목록 | Producer/Consumer 계약 |
| `WIF-DEC-05` | API 동기 실행 또는 사전 생성 결과 조회 | 실행 시간·오류 계약 |
| `WIF-DEC-06` | 실제·견적·합성 가격 구분과 가정 승인 방식 | 경제성 결과 신뢰도 |
| `WIF-DEC-07` | Evaluation truth를 운영 고장 이력으로 공개하는 시점 규칙 | 누수 방지 |

## 16. 검증 기준

- 동일 입력·seed·정책은 동일 결과를 생성한다.
- Baseline과 Intervention은 같은 초기 상태에서 시작한다.
- Intervention 이외의 조건은 임의로 바꾸지 않는다.
- 공구 교체 시 `tool_wear_min=0`, `is_operating=0`, `operating_state=maintenance`다.
- 조치 이후 시간창 Feature를 다시 계산한다.
- 두 시나리오는 동일 모델·버전·임계값을 사용한다.
- `estimated_probability_reduction = baseline - intervention`을 만족한다.
- 모든 선행 지표에 source reference가 존재한다.
- 모든 선행 지표의 `source_reference.asset_id`는 결과의 `asset_id`와 같다.
- `intervention.policy_version`과 `provenance.simulation_policy_version`은 같다.
- `TOOL_REPLACEMENT`는 0 이상의 `tool_wear_after`를 필수로 가진다.
- `time_to_peak_hours`는 `rise_event.started_at`부터 `peak_at`까지의 시간과 일치한다.
- 모든 결과에 effect scope와 필수 limitation code가 있다.
- Canonical 원본·Prediction Timeline·Result Artifact checksum을 변경하지 않는다.
- Evaluation truth가 제품 응답에 포함되지 않는다.
- Producer는 역할별 문장과 UI 표현을 생성하지 않는다.

## 17. 최소 완료 기준

> 설비 한 대의 고장확률 상승을 탐지하고 선행 센서 지표와 근거를 구조화해 제공하며,
> 동일 초기 상태에서 공구 교체를 적용한 경우와 적용하지 않은 경우를 기존 모델로
> 비교해 예상 위험 감소량을 생성한다. 결과에는 합성 시뮬레이션 범위와 한계가
> 명시되고 역할별 자연어 문장은 `final/map-report`가 생성한다.

## 18. 후속 범위

- 실제 예방조치 이력 축적 후 treatment-effect 모델
- 고장 유형별 다중 분류 모델
- 실제 비용·생산계획 기반 경제성 보정
- 부품 재고와 조달 기간
- 현장 전문가의 조치 정책 검증

## 19. 변경 이력

| 날짜 | 변경 |
|---|---|
| 2026-08-11 | 실행 계획 최초 작성, 현재 구현 상태와 기준 경로 반영 |
| 2026-08-11 | What-if Producer와 `final/map-report` Consumer 경계 반영 |
| 2026-08-11 | 고장·수리·예방조치·경제 데이터 계획 반영 |

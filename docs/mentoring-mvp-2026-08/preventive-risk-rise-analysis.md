# Canonical V3.1 위험 상승 탐지 기준

## 1. 목적과 범위

이 문서는 예방조치 What-if의 입력 사례를 선정하기 위한 첫 분석 단계다. 역할별 문장,
API와 UI를 만들지 않고 Canonical V3.1 Prediction Timeline에서 재현 가능한 위험 상승
사건만 구조화한다.

대표 설비 한 대의 상세 분석은 프로젝트 범위를 한 대로 제한하는 것이 아니라,
전체 CNC에 적용할 탐지·What-if 파이프라인을 먼저 검증하는 vertical slice다. 검증된
파이프라인은 적용 가능한 전체 CNC 공구 마모 사건으로 배치 확장한다.

Canonical V3.1 원본과 Result Artifact는 읽기 전용이다. 탐지 결과는 별도 derived
output으로 생성하며 원본 파일을 덮어쓰지 않는다.

## 2. 입력 매핑

| 분석 필드 | 원본 | 역할 |
|---|---|---|
| `prediction_id` | `prediction_timeline.jsonl` | source row 식별 |
| `asset_id`, `asset_type` | `prediction_timeline.jsonl` | 설비별 그룹화와 CNC 한정 |
| `observed_at` | `prediction_timeline.jsonl` | 시간순 정렬과 구간 계산 |
| `failure_probability` | `prediction_timeline.jsonl` | 상승 시작·peak 탐지 |
| `model_version` | `prediction_timeline.jsonl` | 동일 모델 결과 비교 검증 |
| 센서 관측값 | `cnc_sensor_observation.csv` | 후속 선행 지표 통계 입력 |

## 3. 분포 분석 결과

분석 기준은 `canonical-ai4i-physics-v3.1`의
`independent-logreg-v3.1` Prediction Timeline이다.

| 항목 | 값 |
|---|---:|
| 전체 Timeline row | 68,208 |
| CNC Timeline row | 54,567 |
| CNC 설비 | 80 |
| CNC의 양의 인접 확률 변화 표본 | 27,750 |
| 양의 변화량 중앙값 | 0.066465 |
| 75백분위 | 0.122707 |
| 90백분위 | 0.191046 |
| 95백분위 | 0.238315 |
| 99백분위 | 0.335215 |

초기 탐지 정책은 CNC 양의 인접 확률 변화량 90백분위인 `0.191046`을 시작 기준으로
사용한다. 이 값은 도메인의 영구 임계값이 아니라 데이터·모델 버전에 귀속된
`risk-rise-detection-v1` 실험 정책이다.

## 4. 탐지 규칙

1. `asset_id`별로 `observed_at`을 정렬한다.
2. 인접 확률 증가가 `0.191046` 이상이면 최초 threshold 통과 step의 직전 관측을
   상승 시작점으로 선택한다. 이는 전체 구간의 국소 최솟값을 찾는 정의가 아니다.
3. 확률이 계속 증가하고 관측 간격이 1시간 이내인 동안 같은 사건으로 확장한다.
4. 첫 비증가 관측을 종료점으로 기록하고 직전 최고 확률 관측을 peak로 기록한다.
5. 관측 간격이 정책의 1시간을 초과하면 peak에서 종료하고 gap 이후 관측은 사건
   근거에 포함하지 않는다.
6. 종료 사유는 `non_increase`, `gap`, `end_of_timeline`으로 기록한다.
7. 전체 상승폭이 최소 상승폭 기준 이상인 사건만 출력한다.
8. 중복 timestamp와 인접 row의 model version 변경은 오류로 처리한다.

`time_to_peak_hours`는 시작부터 peak까지, `duration_hours`는 시작부터 종료까지다.

전체 Canonical V3.1 Timeline에 V1 정책을 적용한 smoke 결과는 CNC 80개 설비에서
2,606개 후보 사건이다. 이는 확정 고장 사건 수가 아니라 후속 선행 지표 분석과 대표
사례 선정을 위한 candidate set이다.

## 5. 공구 마모 대표 사례

peak의 `top_factors`에 `tool_wear_min*`가 `risk_up`으로 포함된 후보는 1,027건이다.
확률 상승폭과 공구 마모 contribution을 순서대로 적용한 deterministic ranking의 첫
사례는 다음과 같다.

| 항목 | 값 |
|---|---|
| 설비 | `CNC-S02-L04-03` |
| 상승 시작 | `2026-08-14T03:00:00+09:00` |
| peak | `2026-08-14T07:00:00+09:00` |
| 종료 | `2026-08-14T08:00:00+09:00` |
| 고장확률 | `0.041154 → 0.977720` |
| 확률 상승폭 | `0.936566` |
| peak 공구 마모 요인 | `tool_wear_min_6h_change`, `tool_wear_min_6h_std` |

모델의 6시간 Feature Engineering과 동일하게 상승 시작 직전 6시간을 baseline으로
사용하고, 상승 시작부터 peak까지를 risk window로 사용했다.

| 센서 | Baseline 평균 | Risk 평균 | 변화율 | Baseline σ 이동량 |
|---|---:|---:|---:|---:|
| 공기 온도(K) | 299.339114 | 300.843820 | 0.502676% | 0.693462 |
| 공정 온도(K) | 309.702592 | 310.762532 | 0.342245% | 0.677714 |
| 회전속도(rpm) | 1549.544894 | 1611.541208 | 4.000937% | 0.449436 |
| Torque(N·m) | 39.405200 | 40.234200 | 2.103783% | 0.090893 |
| 공구 마모(min) | 27.680314 | 153.593572 | 454.883780% | 25.376931 |

이 통계는 공구 마모가 위험 상승과 함께 크게 변했다는 선행 지표 근거이며 실제
인과관계를 확정하지 않는다.

`baseline_sigma_shift = (risk_mean - baseline_mean) / baseline_stddev`이며 Risk 평균이
Baseline 분포의 표준편차 단위로 얼마나 이동했는지를 나타낸다. 표본 평균의 통계적
유의성 검정이나 인과 효과의 Z-score가 아니다.

## 6. 구현과 실행

- 정책: `experiments/preventive_intervention/policies/risk-rise-detection-v1.json`
- 탐지기: `experiments/preventive_intervention/risk_rise.py`
- 센서 통계: `experiments/preventive_intervention/sensor_analysis.py`
- 실행기: `experiments/preventive_intervention/cli.py`
- 테스트: `tests/test_preventive_risk_rise.py`

```shell
python -m experiments.preventive_intervention.cli detect \
  --timeline <canonical-root>/canonical/model_outputs/prediction_timeline.jsonl \
  --output <derived-root>/risk-rise-events.jsonl

python -m experiments.preventive_intervention.cli analyze \
  --timeline <canonical-root>/canonical/model_outputs/prediction_timeline.jsonl \
  --sensors <canonical-root>/canonical/dataset/cnc_sensor_observation.csv \
  --output <derived-root>/tool-wear-analysis.json
```

`detect`는 전체 위험 상승 후보를, `analyze`는 공구 마모 후보 수·대표 사건·센서 통계를
생성한다. 따라서 이 문서의 후보 수와 대표 사례 표는 저장소 안의 실행 경로로
재생성할 수 있다.

`DetectedRiskRiseEvent`와 `SensorFeatureStatistic`은 비배포 experiment 내부의 derived
contract다. 공개 `schemas/preventive-what-if.schema.json`은 downstream consumer에
전달하는 최종 `WhatIfResult`만 정의하며 내부 탐지·통계 중간 산출물을 포함하지 않는다.

## 7. 다음 단계

선정한 사건을 기준으로 Baseline/Intervention 시계열을 만들고 공구 교체 이후의
`tool_wear_min`, 생산·정비 상태를 재계산한다. 이후 기존 Feature Engineering과 동일
모델을 사용해 예방조치 전후 고장확률을 비교한다.

대표 사례에서 End-to-End 결과가 검증되면 동일 파이프라인을 적용 가능한 전체 CNC
사건에 실행하고, 사건별 결과뿐 아니라 적용 성공·실패 수와 위험 감소량 분포를 함께
집계한다.

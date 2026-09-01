# TOOL_REPLACEMENT 비용 기준정보

## 1. 적용 범위

이 문서는 `TOOL_REPLACEMENT`를 **카바이드 절삭 인서트 1개 교체**로 한정한
MVP 비용 분석 기준을 설명한다. 정본 데이터는
`data/fixtures/maintenance_cost/tool-insert-cost-basis-v1.json`이며, 이 문서는
값의 의미와 채택 이유를 사람이 검토하기 쉽게 정리한다.

아래 값을 실제 사업장 견적, 급여, MES/ERP 실적 또는 보장된 절감액으로 표현하지
않는다. 공개자료는 참고값이고, 공개자료로 확정할 수 없는 값은
`synthetic_scenario_estimate` 또는 명시적 데모 정책으로 구분한다.

## 2. 기준값 요약

| 항목 | Low | Base | High | 분류 |
|---|---:|---:|---:|---|
| 인서트 1개 | 12,251원 | 12,251원 | 12,251원 | 공개 카탈로그 참고 |
| 주간 정비 노무단가 | 292원/분 | 292원/분 | 292원/분 | 공식 임금조사 참고 |
| 야간 정비 노무단가 | 438원/분 | 438원/분 | 438원/분 | 조사노임 × 단일 50% 야간 가산 데모 |
| 직접 작업시간 | 5분 | 10분 | 15분 | 명시적 데모 가정 |
| 외부 서비스 비용 | 0원 | 0원 | 0원 | 조건부 사내작업 정책 |
| 예방 정지시간 | 15분 | 30분 | 45분 | 합성 정책 |
| 생산손실률 | 846원/분 | 1,058원/분 | 1,269원/분 | 합성 시나리오 계산 |
| 고장 결과비용 | 67,391원 | 147,971원 | 334,331원 | 합성 시나리오 계산 |

`expected_failure_loss`는 기준정보가 아니라 다음 식의 계산 결과다.

```text
expected_failure_loss
= failure_probability × failure_consequence_cost
```

## 3. 항목별 산정 근거

### 3.1 서버 시각과 주간·야간 노무단가

Backend가 비용 분석 요청을 받은 `calculated_at`을 UTC로 기록한다. 즉시 정비는 그
시각을, 계획 정비 창은 정확히 12시간 뒤를 실행 시각으로 사용한다. 실행 시각을
`Asia/Seoul`로 변환한 뒤 다음 데모 정책으로 노무단가를 고른다.

```text
06:00 이상 22:00 미만 = 292원/분
22:00 이상 또는 06:00 미만 = 438원/분
```

292원/분은 기계장치정비원 조사노임 139,942원/일을 8시간으로 나눈 공개 참고값이다.
438원/분은 `292 × 1.5`로 산출하며 근로기준법 제56조의 22:00~06:00 야간근로 50%
가산을 한 번만 적용한 데모 값이다. 실제 사업장의 통상임금, 근무표, 연장·휴일근로와
중복 가산을 계산하지 않으므로 급여나 실제 외주비로 표현하지 않는다.

- 임금조사: fixture의 `kbiz-2026-first-half-manufacturing-wage-survey` source
- 법령: https://law.go.kr/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1012828203

### 3.2 직접 작업시간: 5 / 10 / 15분

Sandvik Coromant의 Productivity Analyzer 교육 예시는 직접 인서트 인덱싱 시간으로
1분과 2분을 사용한다. 그러나 제품 비용 분석의 작업시간에는 직접 교체뿐 아니라
안전 확인, 접근, 체결 확인과 작업 완료 확인도 포함된다.

동료평가 연구인 *The Human-Centric SMED*의 장비 교체 사례는 준비·분해·조립·조정·
검사를 포함해 개선 후 9분 10초, 개선 전 13분 4초를 기록한다. 따라서 10분을
제조사 표준시간이 아닌 데모 기준값으로 사용하고 5~15분을 민감도 범위로 둔다.

- Sandvik Coromant: https://videos.sandvik.coromant.com/creating-a-testturningmp4
- Fonda and Meneghetti, *The Human-Centric SMED*: https://doi.org/10.3390/su14010514

### 3.3 외부 서비스 비용: 0원

0원은 미확인 외주 견적을 대체한 값이 아니다. 다음 조건을 모두 만족하는 데모
시나리오에서 외부 서비스가 발생하지 않는다는 정책값이다.

```text
execution_mode = in_house
spare_part_available = true
vendor_dispatch_required = false
```

대표 GS-002 fixture는 `spare_part_available=true`를 제공한다. 외주 출동이 필요한
경우에는 이 값을 재사용하지 않고 실제 견적을 받거나 `insufficient`를 반환해야 한다.

- 내부 근거: `data/fixtures/GS-002-tool-wear-warning.json`

### 3.4 예방 정지시간: 15 / 30 / 45분

기존 `TOOL_REPLACEMENT` What-if 계약은 예방조치 정지시간을 30분으로 사용한다.
이를 기준값으로 유지하고, 안전 정지·접근·교체·검증·시험 가동·재시작의 변동성을
15~45분으로 표현한다.

GS-002의 120분은 고장/비계획 정지에 따른 생산 노출 기준이므로 예방 교체시간으로
재사용하지 않는다.

- 내부 근거: `data/fixtures/what_if/tool-replacement-contract-fixture.json`
- 내부 근거: `data/fixtures/GS-002-tool-wear-warning.json`

### 3.5 생산손실률: 846 / 1,058 / 1,269원/분

NIST의 cost-breakdown 접근처럼 시간과 단가를 분리하여 계산한다.

```text
effective_units_per_minute = OEE / cycle_minutes
production_loss_rate = effective_units_per_minute × unit_contribution_margin

0.846 / 4.0 = 0.2115 units/minute
0.2115 × (4,000 / 5,000 / 6,000 KRW)
= 846 / 1,058 / 1,269 KRW/minute
```

OEE 0.846과 4분 cycle은 저장소의 합성 생산계획 context를 사용한다. 단위 공헌이익
4,000/5,000/6,000원은 AI4I나 실제 ERP에서 제공된 값이 아닌 명시적 데모 가정이다.
AI4I 공식 변수에는 센서·공구 마모·고장 정보는 있지만 가격, 공헌이익, MES takt,
ERP 경제정보가 없다.

- 내부 근거: `data/fixtures/operation_context/production-planning-context-v1.json`
- OEE 참고: https://www.oee.com/world-class-oee/
- AI4I 공식 설명: https://archive.ics.uci.edu/dataset/601/ai4i
- NIST cost-breakdown: https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=928028

### 3.6 고장 결과비용: 67,391 / 147,971 / 334,331원

현재 근거가 있는 항목만 더한다.

```text
failure_consequence_cost
= insert_cost
+ emergency_labor_duration × labor_rate
+ unplanned_downtime × production_loss_rate
```

| 구분 | 긴급 작업시간 | 비계획 정지 | 계산 결과 |
|---|---:|---:|---:|
| Low | 15분 | 60분 | 12,251 + 15×292 + 60×846 = 67,391원 |
| Base | 30분 | 120분 | 12,251 + 30×292 + 120×1,058 = 147,971원 |
| High | 60분 | 240분 | 12,251 + 60×292 + 240×1,269 = 334,331원 |

60/120/240분은 저장소의 합성 event-impact 범위를 사용하며 GS-002의 120분을
기준점으로 삼는다. 폐기·재작업, 재가동 소모품, 2차 손상, 납기 위약금은 공식 값이
없으므로 제외하고 limitation에 남긴다.

## 4. 기대 고장손실 적용 규칙

기존 What-if 계약에서 이미 제공하는 확률만 사용한다.

| 시나리오 | 확률 | 기대 고장손실 Low/Base/High | 상태 |
|---|---:|---:|---|
| 즉시 교체 | 0.21 | 14,152 / 31,074 / 70,210원 | 계산 가능 |
| 계획 정비 | 없음 | 없음 | `insufficient` |
| 재점검 | 없음 | 없음 | `insufficient` |
| 미조치 | 0.82 | 55,261 / 121,336 / 274,151원 | 계산 가능 |

계획 정비와 재점검의 미래 위험확률을 Cost What-if가 추정·보간하지 않는다. 향후
Diagnosis가 해당 horizon의 공식 Prediction을 제공하거나 팀이 별도의 governed
sensitivity contract를 승인한 뒤에만 계산 가능 상태로 전환한다.

## 5. 결과 해석 경계

- 결과는 비용 의사결정 참고값이다.
- 최저 계산 비용은 Recommendation, 승인 또는 WorkOrder 명령이 아니다.
- 현재 합성값은 실제 절감액을 보장하지 않는다.
- 실제 운영 전 가격은 구매/ERP, 노무는 급여·외주계약, 생산손실은 MES/ERP,
  고장 결과는 정비이력의 버전 데이터로 교체해야 한다.

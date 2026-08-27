# PR #130 SOP 센서 기반 점검 판단 제안

## 제안 대상

- 기준 브랜치: PR #130 `codex/pr128-sop-grounding`
- 전달 대상: Closed-loop / Operations 담당자
- 변경 성격: SOP grounding fixture를 현장 점검 질문 초안에서 **센서 기반 Inspection Result 판단 기준**까지 확장한다.

## 문제

현재 예지보전 데이터는 위험 신호와 Product Result/Evidence를 제공하지만, 위험 신호가 실제 고장으로 이어졌는지까지 증명하지 않는다. 따라서 Closed-loop가 "고장을 예방했다", "정비 효과가 입증됐다"라고 주장하면 증거 범위를 넘는다.

그 대신 운영 제품 관점에서는 다음 흐름이 더 안전하다.

```text
Product Result / Evidence
-> Inspection WorkOrder
-> SOP sensor judgment
-> Inspection Result
-> Operations manual Recommendation
-> Manager Decision
-> Maintenance WorkOrder / Action
-> MaintenanceEvent
-> Runtime Overlay 재관측
```

## 제안

PR #130의 `procedure-grounding.schema.json`에 `sensor_judgment` 블록을 추가한다. SOP는 모델 결과를 대체하지 않고, 현장 점검자가 기록할 Inspection Result의 판단 기준을 제공한다.

예시 기준:

- `tool_wear_min >= 220 min`이면 `maintenance_recommended`
- `overstrain_index`가 product type별 임계값을 넘으면 `maintenance_recommended`
- `temperature_difference_k >= 8 K`이면 열 경로 점검 필요

## 데이터 영향

추가되는 데이터:

- SOP criterion id
- 기준 센서 factor
- operator / threshold / unit
- 허용 outcome
- human check required 여부
- Inspection Result mapping
- allowed / forbidden claim boundary

바뀌면 안 되는 데이터:

- Canonical sensor history
- Product Result/Evidence
- Model Artifact
- 기존 Recommendation/Decision/WorkOrder lineage
- hidden truth / evaluation truth

## Closed-loop 경계

SOP sensor judgment는 Inspection Result의 운영 사실을 만든다. 이것만으로 MaintenanceEvent를 만들지 않는다.

정비 경로는 다음 승인을 요구한다.

```text
Inspection Result
-> Operations manual Recommendation
-> process_manager accept
-> Maintenance WorkOrder requested
```

## UI / Report 문구

허용:

- "SOP 기준상 정비 필요 점검 결과"
- "센서 기준이 점검 결과를 지지"
- "정비 전 위험 판단과 정비 후 재관측을 연결"

금지:

- "실제 고장 예방 입증"
- "정비로 downtime 절감"
- "정비 완료 후 정상화"
- "SOP가 자동 정비 승인"

## 구현 범위

이번 변경은 PR #130 기준 schema/fixture/proposal만 다룬다. API mutation, DB migration, UI 표시 확장은 별도 PR에서 처리한다.

후속 구현에서 필요한 항목:

- Inspection Result payload에 `sop_judgment_refs[]` 추가
- Operations manual recommendation 생성 시 SOP criterion lineage 보존
- Report 문구에서 Product Evidence와 SOP 판단 근거를 분리
- E2E에서 `Product Result -> Inspection Result -> manual recommendation -> maintenance WorkOrder` lineage 확인

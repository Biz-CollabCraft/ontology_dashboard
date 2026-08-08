# Week 2 역할 분담 및 산출물 정의

- 문서 상태: `Week 2 execution baseline`
- 기준일: `2026-08-08`
- 제품·계약 기준 저장소: `Biz-CollabCraft/ontology_dashboard`
- 데이터·파이프라인 기준 저장소: `Biz-CollabCraft/gen_data`
- 비교 프로토타입: `oosuhada/agentic-ontology-dashboard`
- 기준 데이터: Canonical V3.1

## 1. 목적

Week 2의 목표는 기능을 계속 확장하는 것이 아니라, 멘토링에서 요구한 세 가지
산출물을 팀 기준으로 고정하고 동일한 Result Artifact를 Dashboard, API, Report가
함께 소비하도록 연결하는 것이다.

필수 공통 산출물은 다음 세 가지다.

1. 요구사항 정의서
2. MVP 설계 계획서
3. 실제 확인 가능한 MVP 화면

개인 숙제는 서로 독립된 네 제품을 만드는 일이 아니라 하나의 결과 계약을 네
방향에서 검증하는 병렬 작업으로 해석한다.

```text
Canonical V3.1
      ↓
데이터·예측 파이프라인
      ↓
Result Artifact / Evidence
      ├────────→ Prediction API
      ├────────→ Dashboard
      └────────→ Report
```

## 2. Week 2 기준 문서

팀 작업은 아래 문서를 단일 기준으로 사용한다.

- [요구사항 명세](./week2-requirements-specification.md)
- [기능 명세](./week2-functional-specification.md)
- [공통 스키마 정의](./week2-schema-definition.md)
- [API 명세](./week2-api-specification.md)
- [리포트 명세](./week2-report-specification.md)
- [MVP 설계 명세](./week2-mvp-design-specification.md)
- [현행 구현 기준선](./current-mvp-implementation-baseline.md)
- [계약 검토 체크리스트](./week2-contract-review-checklist.md)

개인 프로토타입에서 작성된 상세 명세와의 관계는
[프로토타입 문서 이관 매핑](./week2-prototype-doc-migration-map.md)에 기록한다.

## 3. 최종 역할 요약

| 담당 | 역할 | Week 2 핵심 책임 | 완료 산출물 |
|---|---|---|---|
| 우수 | 팀원1 · Frontend | MVP 화면과 공통 결과 계약 연결 | Overview·Objects·Operations·Executive Report 화면, 캡처, 데모 흐름, API 연결 상태 |
| 광우 | 팀원2 · Contract/Docs | 요구사항·기능·스키마·API·리포트 계약 고정 | 요구사항·기능·API·스키마·리포트·MVP 설계 문서 |
| 성민 | 팀원3 · Prediction/Data | 결과 조회 API와 데이터·예측 파이프라인 재현성 | Predictions 목록/상세 조회, Result Artifact 생성, manifest/checksum, 재현성 확인 |
| 호범 | 팀원4 · Report/LLM | 검증된 결과를 근거 기반 보고서로 변환 | Event Report 입력/출력, deterministic 우선, LLM 보조, 예시 결과 |

팀원 번호보다 담당자 이름과 역할명을 우선 사용한다. 역할 재조정 이후 문서와
대화에서 `팀원1~4`만 사용하면 API·리포트 담당이 혼동될 수 있기 때문이다.

## 4. 먼저 고정할 공통 입력 계약

네 담당자가 서로의 완료를 기다리지 않도록, Week 2 구현은 같은 최소 결과 필드를
기준으로 병렬 진행한다. 정확한 타입과 enum은 `week2-schema-definition.md`를 따른다.

### 최소 공통 필드

- asset/equipment identifier
- display name
- line/site 등 화면 표시용 위치 식별자
- observed/as-of time
- failure probability
- risk/status grade
- confidence
- predicted failure type 또는 현재 계약의 동등 의미 필드
- recommended decision/action
- top factors
- data quality warning/hold 상태
- dataset/model/artifact provenance

화면 표현 방식 자체는 파이프라인 계약이 아니다. 예를 들어 표, 그리드, 설비 이미지,
차트 종류는 Frontend가 결정할 수 있다. 반대로 24시간 시계열, peer percentile,
과거 고장 패턴 유사도처럼 새 계산 결과가 필요한 UI는 Result Artifact 계약을
확장하므로 Week 2 필수 범위에 넣지 않는다.

## 5. 우수 — Frontend / MVP 화면

### 역할 목적

이미 구현된 프로토타입을 처음부터 다시 만드는 것이 아니라, Week 2 공식 범위에
필요한 화면을 팀 계약에 맞춰 추출·연결한다.

### 필수 화면

1. Overview
2. Objects
3. Operations
4. Executive Report

### 최소 완료 조건

- 설비 목록에서 ID/명, 위험도, 상태 문구와 색상을 확인할 수 있다.
- 색상만으로 상태를 표현하지 않는다.
- 선택 설비의 상세 근거를 확인할 수 있다.
- 같은 설비의 상태와 확률이 화면 간 일치한다.
- loading/empty/error와 데이터 품질 상태를 구분한다.
- 실제 API가 준비되기 전에는 동일 계약의 mock fixture로 병렬 개발할 수 있다.
- 발표용 화면 링크와 주요 화면 캡처를 제공한다.

### 이번 주에 새로 확대하지 않는 것

- 새로운 상용화 V3/V4 화면
- 3D 설비 시각화
- peer comparison
- 과거 고장 패턴 similarity
- 자유 배치 Analysis Canvas
- 전체 역할별 독립 화면

## 6. 광우 — Contract / Requirements / Specifications

### 역할 목적

화면·API·Report가 서로 다른 필드와 의미를 사용하지 않도록 제품 계약을 팀 저장소에
고정한다. 문서 작업은 구현을 멈추게 하는 승인 게이트가 아니라 병렬 개발을 가능하게
하는 기준선이어야 한다.

### 필수 완료 조건

- 요구사항, 기능, API, 공통 스키마, 리포트, MVP 설계 문서가 서로 링크된다.
- Current 구현과 Target/V2 제안을 구분한다.
- 결정 완료 항목과 backlog를 분리한다.
- 같은 필드에 서로 다른 이름을 강제하지 않는다.
- 팀원이 문서만 읽고 mock 입력을 만들 수 있다.

## 7. 성민 — Prediction API / Pipeline / Reproducibility

### 역할 목적

Canonical V3.1을 입력으로 제품이 소비할 Result Artifact를 안정적으로 생성하고,
그 결과를 조회 API로 제공한다.

### 최소 완료 조건

```text
Canonical input
→ pipeline function/command
→ Result Artifact
→ predictions list/detail
```

- 한 함수 또는 명령으로 결과를 생성할 수 있다.
- 동일 입력과 동일 설정의 반복 실행 결과가 재현된다.
- 데이터 버전과 모델/Artifact 버전을 추적할 수 있다.
- 목록 조회와 설비 단건 조회가 가능하다.
- Frontend/Report가 사용할 샘플 응답을 제공한다.

현재 팀 서비스가 project/workspace scope를 사용한다면 멘토 PPT의
`GET /predictions`, `GET /predictions/{설비ID}`는 실제 서비스 경로에 맞춰
호환 또는 매핑해도 된다. 단, 발표 문서에 대응 관계를 명확히 기록한다.

## 8. 호범 — Report / LLM

### 역할 목적

Result Artifact와 Evidence에 존재하는 사실을 설비 상태 요약과 역할별 보고 문장으로
변환한다.

### Week 2 우선순위

```text
EventReportInput mock
→ deterministic report block
→ schema validation
→ 필요 시 LLM 문장화 보조
```

기간 집계형 ExecutiveReportInput과 고급 LLM Agent는 Target/V2 후보로 둔다.

### 최소 완료 조건

- 설비 하나의 상태 요약 문단을 생성한다.
- 숫자와 상태 판단은 입력 데이터에서 가져온다.
- LLM이 새로운 고장 원인이나 수치를 만들어내지 않는다.
- LLM 실패 시 deterministic/template fallback이 가능하다.
- 근거 필드 또는 provenance를 추적할 수 있다.

## 9. 의존관계와 병렬 작업 원칙

잘못된 순서:

```text
Pipeline 완료
→ API 완료
→ Frontend 시작
→ Report 시작
```

권장 순서:

```text
공통 최소 계약 Freeze
      ↓
┌──────────┬──────────┬──────────┬──────────┐
│ Pipeline │   API    │ Frontend │  Report  │
│  실제화  │  mock→실제│ mock→실제 │ mock→실제 │
└──────────┴──────────┴──────────┴──────────┘
      ↓
하나의 설비/이벤트로 통합 데모
```

따라서 팀원3의 파이프라인이 완성될 때까지 다른 팀원이 기다리지 않는다. 공통 계약의
mock Result Artifact를 먼저 공유하고, 실제 결과가 나오면 데이터 소스만 교체한다.

## 10. 통합 데모 완료 정의

대표 설비 한 대를 기준으로 아래 흐름이 이어지면 Week 2 최소 통합이 성립한다.

```text
Pipeline
→ Result Artifact 생성
→ Prediction API 조회
→ Dashboard에서 같은 설비/확률/상태 확인
→ Report에서 같은 근거를 사용한 상태 요약 확인
```

멘토 발표에서는 다음 한 문장으로 설명할 수 있어야 한다.

> 1주차에 확보한 제조 예지보전 데이터를 공통 Result Artifact로 표준화하고,
> 2주차에는 동일 결과를 Prediction API, 역할별 Dashboard, 설비 상태 Report가
> 독립적으로 소비하도록 MVP 구조를 분리했습니다.

## 11. 저장소 책임

### `Biz-CollabCraft/ontology_dashboard`

- 요구사항·기능·API·리포트·공통 스키마 계약
- MVP UI와 서비스 통합 코드
- 화면 캡처와 발표 문서

### `Biz-CollabCraft/gen_data`

- Canonical 데이터 생성·갱신
- 예측/결과 추출 파이프라인
- Result Artifact 실제 생성
- 재현성 검증과 샘플 결과

같은 계약 문서를 두 저장소에 복제하지 않는다. `gen_data`는
`ontology_dashboard`의 공통 계약을 참조하고 실제 생성 코드와 결과 예시만 관리한다.


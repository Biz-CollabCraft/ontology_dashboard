# Week 2 계약 검토 체크리스트

## 1. 목적과 판정 기준

이 문서는 현행 실행 코드와 Week 2 설계안을 비교해 팀 결정을 기록한다. 모든 항목을
미결정으로 간주하지 않으며, [현행 MVP 구현 계약 기준선](./current-mvp-implementation-baseline.md)을
코드 사실의 기준으로 사용한다.

| 분류 | 의미 |
|---|---|
| `현행 구현 계약` | 코드·schema·테스트에서 확인된 값 |
| `용어·표현 합의` | 내부 계약은 유지하고 제품 표시를 통일할 항목 |
| `부분 일치` | 방향은 같지만 필드·경로·책임이 일부 다름 |
| `구현 변경 필요` | 채택하면 코드·API·UI·테스트 변경이 필요한 요구사항 |

각 결정에는 `선택`, `변경 내용`, `코드 영향`, `근거`, `결정자`, `결정일`을 기록한다.

## 2. 현황 요약

| ID | 주제 | 분류 | 현재 상태 |
|---|---|---|---|
| DEC-COM-01 | 기준 저장소 | 부분 일치 | 문서와 실행 코드 저장소 분리 확인 |
| DEC-COM-02 | 사용자 명칭 | 용어·표현 합의 | 권한 역할은 구현 완료 |
| DEC-COM-03 | Decision·Note 범위 | 구현 변경 필요 | 둘 다 저장 기능으로 구현 |
| SCR-01 | 화면별 실제 필드 | 부분 일치 | 네 화면 구현, 제안 필드와 차이 |
| SCR-02 | 상태 명칭 | 용어·표현 합의 | Artifact 4등급과 ViewModel 품질 상태 분리 필요 |
| SCR-03 | 필터·정렬·이동 | 구현 변경 필요 | 현행 필터·URL 계약과 제안이 다름 |
| SCR-04 | 화면 상태 | 부분 일치 | loading·empty·error·stale·permission 구현 |
| API-01 | API 구조 | 구현 변경 필요 | 현행 API와 제안 경로가 다름 |
| API-02 | pagination | 구현 변경 필요 | offset/limit 구현 |
| API-03 | 위험등급 책임 | 현행 구현 계약 | Artifact status 사용 |
| API-04 | snapshot·stale | 부분 일치 | 프론트 24시간 기준 구현 |
| API-05 | 결합 필드·provenance | 부분 일치 | API/ViewModel 확장 존재 |
| API-06 | fallback | 현행 구현 계약 | Gold Fixture와 warning 구현 |
| RPT-01 | LLM 입력 JSON | 구현 변경 필요 | 현행 ReportRequest 존재 |
| RPT-02 | LLM 출력 JSON | 구현 변경 필요 | 현행 report schema 존재 |
| RPT-03 | 문장 안전 규칙 | 현행 구현 계약 | prompt·schema·평가 규칙 존재 |
| RPT-04 | 실패 대체 | 현행 구현 계약 | LLM→deterministic→template 구현 |

이 분류는 팀 결정의 대체물이 아니다. `현행 구현 계약`은 코드 사실을 확정하며,
그 계약을 제품 기준으로 계속 유지할지는 팀이 결정한다.

## 3. 공통 결정

### DEC-COM-01 — 기준 저장소

- 현행: 제품·계약 문서는 `Biz-CollabCraft/ontology_dashboard`, 실행 코드는
  `oosuhada/agentic-ontology-dashboard` 정리 브랜치에 있다.
- 결정: 실행 코드를 팀 저장소로 이전·병합할 시점과 방법.
- 분류: `부분 일치`

### DEC-COM-02 — MVP 사용자 명칭

- 현행 권한: `manager`, `engineer`.
- 현행 UI: 관리자·임원, 실무 엔지니어.
- 문서 제안: 생산 관리자, 현장 담당자.
- 결정: 내부 role enum을 유지한 채 표시 명칭을 매핑할지.
- 분류: `용어·표현 합의`

```text
내부 enum: manager / engineer 유지
API/Auth 역할: manager / engineer
현재 로그인 표시: 관리자·임원 / 실무 엔지니어
업무 관점 후보: 생산 관리자 / 현장 담당자
최종 표시 명칭: 팀 합의 필요
```

### DEC-COM-03 — Decision·Note 범위

- 현행: Decision과 Note 모두 실제 저장 기능이다. 관리자는 `events.decision`,
  엔지니어는 `events.note` 권한을 사용하며 Activity 감사 이력과 테스트가 있다.
- 결정: 현행 유지 또는 기능 제외. 제외하면 API·UI·권한·테스트 변경이 필요하다.
- 분류: `구현 변경 필요`

## 4. 팀원1 — 화면 계약

### SCR-01 — 화면별 실제 필드

- 현행 Overview: 위험 KPI·Downtime·판단 대기 Event 중심.
- 현행 Objects: 검색·라인·상태·담당자 필터와 설비 Inspector 중심.
- 현행 Operations: Event Queue, Evidence, Decision, Note, Activity 중심.
- 현행 Executive Report: 선택 Event 단위 역할별 보고서.
- V2 제안: 가동·생산·정비 기간 집계, site/cell/기간 필터와 기간 기반 보고서.
- 결정: 화면별 현행 유지·보강 또는 V2 전환 범위.
- 분류: `부분 일치`

### SCR-02 — 상태 명칭과 표현

- Artifact `status_grade`: `normal`, `attention`, `warning`, `critical`.
- ViewModel 데이터 품질 상태: `data_quality_hold`; Artifact enum이 아니다.
- 현행 표시: 정상, 주의, 경고, 위험, 데이터 확인.
- 결정: API 원본 상태와 화면 합성 상태를 분리하고 현행 표시 명칭으로 통일할지.
- 분류: `용어·표현 합의`

### SCR-03 — 필터·정렬·이동

- 현행 Objects 필터: 검색, 라인, 상태, 담당자.
- 현행 URL: `view`, `asset_id`, `event_id`, `role`, `workspace_id`.
- 문서 제안: 사이트, 셀, 설비 유형, 상태, 기간과 필터 URL 유지.
- 결정: 현행 유지, 필터 추가 또는 URL 계약 확장.
- 분류: `구현 변경 필요`

### SCR-04 — 화면 상태

- 현행: loading, empty, error, stale, permission과 fallback warning을 사용한다.
- 결정: 화면별 문구·재시도 동작·접근성 완료조건 보강.
- 분류: `부분 일치`

## 5. 팀원3 — 데이터·조회·집계 API 계약

### API-01 — API 구조

- 현행 Canonical base path:
  `/api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance`.
- 현행 핵심: `GET /dashboard`, `GET /results/latest`.
- 현행 Event: `/api/events/{event_id}/evidence|report|decision|notes|activity`.
- 문서의 `/overview`, `/objects`, `/operations`는 `변경 제안`이다.
- 결정: 현행 경로 보강 또는 화면별 API 재설계.
- 분류: `구현 변경 필요`

### API-02 — 목록 pagination

- 현행 `/results/latest`: `offset`, `limit`, `total`; 기본 100, 최대 500.
- 문서의 `page`, `size`: `변경 제안`.
- 결정: 현행 유지 또는 호환·마이그레이션 계획을 포함한 변경.
- 분류: `구현 변경 필요`

### API-03 — 위험등급 산출 책임

- 현행: API는 Artifact의 4등급 `status_grade`를 사용하고 ViewModel은 데이터 품질
  보류를 `data_quality_hold`로 별도 표현한다.
- 결정: 두 상태를 분리하고 임계값 재계산을 API에 추가하지 않을지.
- 분류: `현행 구현 계약`

### API-04 — 기준시각과 stale

- 현행: 프론트가 최신 `observedAt` 기준 24시간 초과를 stale로 판단한다.
- 결정: 24시간을 제품 계약으로 채택할지, 백엔드 산출로 이동할지와 시간대 기준.
- 분류: `부분 일치`

### API-05 — 결합 필드와 provenance

- 현행: Result Artifact, Event/Evidence와 Asset/ViewModel 확장 필드가 함께 사용된다.
- 결정: 원천·결합·파생 필드를 응답에서 어떻게 구분하고 provenance를 어디까지
  노출할지.
- 분류: `부분 일치`

### API-06 — fallback

- 현행: Canonical Runtime 실패 시 Gold Fixture를 사용하고 warning과 fallback
  표시를 제공한다.
- 결정: 발동 조건, 허용 환경, 응답 필드와 사용자 문구를 최종 고정.
- 분류: `현행 구현 계약`

## 6. 팀원4 — 리포트 API·생성 계약

### RPT-01 — 입력 JSON

- 현행: `ReportRequest(role, locale, use_llm)`.
- 문서의 기간·필터·집계를 포함한 `ReportInput`: `변경 제안`.
- 검토안: V2 `ReportInput`을 변경 제안으로 유지하고 현행 `ReportRequest`를
  대체하지 않는다. mock 입력으로 deterministic 생성 가능성을 먼저 검증한다.
- 담당: 팀원4가 mock 계약 검증과 향후 리포트 API 구현을 맡는다.
- 코드 영향: 이번 단계는 API 변경 없음.
- 분류: `구현 변경 필요`

### RPT-02 — 출력 JSON

- 현행: `schemas/report.schema.json`의 role-aware grounded report.
- 문서의 `ReportOutput`: `변경 제안`.
- 검토안: `executive-report-v1.0`을 V2 후보로 검증하고 현행 grounded report
  schema와 분리한다.
- 담당: 팀원4.
- 코드 영향: 실제 적용 시 schema·UI·테스트 변경 필요.
- 분류: `구현 변경 필요`

### RPT-03 — 문장 규칙

- 현행: 고장·인과·자동 실행을 확정하지 않고 근거·한계·citation을 보존하는
  prompt, schema와 평가 규칙이 있다.
- 검토안: 권장안 수락. 고장·원인 확정, 자동 정지·정비 지시, 비용 절감·생산
  손실 단정을 금지한다. 입력 수치와 enum을 변경하지 않고 없는 값은 추론하지 않는다.
- 분류: `현행 구현 계약`

### RPT-04 — 실패 대체 응답

- 현행: LLM 실패 시 deterministic report, 최종 template fallback과 경고 표시를
  사용한다.
- 검토안: LLM → deterministic → template 흐름을 유지하고 V2 명칭을 별도로
  정의한다. 현행 `deterministic_fallback`은 V2의 `generation_method=deterministic`,
  `fallback_reason=llm_failed`로 매핑한다.
- 담당: 팀원4 Report API.
- 분류: `현행 구현 계약`

## 7. 결정 기록 양식

각 항목 아래에 다음 형식으로 기록한다.

```text
선택:
변경 내용:
코드 영향:
근거:
결정자:
결정일:
```

## 8. 검토 완료 조건

- 17개 항목의 현행값과 변경 제안이 구분된다.
- 구현 변경 항목에는 영향 범위와 전환 방법이 기록된다.
- 합의 결과가 스키마·기능·API·리포트·MVP 설계에 반영된다.
- 실제 API 경로와 JSON schema를 추적성 매트릭스에 연결한다.
- 모든 최종 결정에 결정자와 결정일이 있다.

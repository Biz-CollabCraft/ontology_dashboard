# 현행 MVP 구현 계약 기준선

## 1. 목적과 기준

이 문서는 Week 2 문서의 제안과 이미 구현된 제품 계약을 구분하기 위한 기준선이다.

- 제품·계약 문서 기준: `Biz-CollabCraft/ontology_dashboard`
- 현행 실행 코드 기준: `oosuhada/agentic-ontology-dashboard`의
  `codex/current-mvp-repository-convergence-20260806` 브랜치
- 저장소 통합: 실행 코드를 팀 저장소로 이전하거나 병합하는 별도 결정이 필요하다.

현행 구현값은 제품 방향이 영구 확정됐다는 의미가 아니다. 이를 변경하는 항목은
단순 확인이 아니라 코드·테스트·데이터 마이그레이션 영향을 검토하는 변경 결정이다.

## 2. 확인된 현행 계약

| 영역 | 현행 구현 |
|---|---|
| 인증 역할 | `manager`, `engineer` |
| UI 역할 | 관리자·임원, 실무 엔지니어 |
| 권한 | 관리자 `events.decision`, 엔지니어 `events.note` |
| 쓰기 기능 | Decision·Note 실제 저장, Activity 감사 이력 제공 |
| Operations | Event Queue, Evidence, Recommendation, Decision, Note, Activity 중심 |
| Artifact 위험 enum | `normal`, `attention`, `warning`, `critical` |
| ViewModel 품질 상태 | `data_quality_hold`; Artifact `status_grade`와 별도 |
| 상태 표시 | 정상, 주의, 경고, 위험, 데이터 확인 |
| Objects 필터 | 검색, 라인, 상태, 담당자 |
| URL 상태 | `view`, `asset_id`, `event_id`, `role`, `workspace_id` |
| 최신 결과 pagination | `offset`, `limit`, `total`; 기본 100, 최대 500 |
| stale | 프론트에서 최신 관측시각 기준 24시간 초과 |
| 데이터 fallback | Canonical Runtime 실패 시 Gold Fixture와 warning 사용 |
| Report 요청 | `ReportRequest(role, locale, use_llm)` |
| Report 출력 | `schemas/report.schema.json`의 role-aware grounded report |
| Report fallback | LLM → deterministic → 최종 template 표시 흐름 |

## 3. 현행 핵심 API

Canonical Predictive Maintenance base path:

```text
/api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance
```

| Method | Path |
|---|---|
| GET | `/dashboard` |
| GET | `/results/latest` |
| GET | `/api/events/{event_id}/evidence` |
| POST | `/api/events/{event_id}/report` |
| POST | `/api/events/{event_id}/decision` |
| POST | `/api/events/{event_id}/notes` |
| GET | `/api/events/{event_id}/activity` |

## 4. 변경 결정이 필요한 주요 차이

| 주제 | 현행 | Week 2 제안 | 결정 성격 |
|---|---|---|---|
| Operations | Event 업무 흐름 | 생산 Cycle·정비 목록 | 제품 흐름 재설계 |
| Decision·Note | 저장 기능 | 조회 중심 또는 제외 | 기존 기능 제거·범위 변경 |
| Pagination | offset/limit | page/size | API 계약 변경 |
| Report JSON | ReportRequest와 report schema | ReportInput/ReportOutput | API·LLM·UI 계약 변경 |
| Objects 필터 | 검색·라인·상태·담당자 | 사이트·셀·유형·상태·기간 | UI·조회 계약 변경 |
| 역할 명칭 | 관리자·임원/실무 엔지니어 | 생산 관리자/현장 담당자 | 표시 용어 합의 |

## 5. 사용 원칙

- 명세서의 현행 설명은 이 문서를 따른다.
- 현행과 다른 내용에는 `변경 제안`을 표시한다.
- 변경 제안을 채택하기 전에는 실제 API 경로와 JSON schema를 대체하지 않는다.
- 팀 결정에는 결정자, 결정일, 코드 영향과 전환 방법을 기록한다.

# Week 2 추적성 매트릭스

## 1. 목적

요구사항이 기능, 화면, API, 스키마와 테스트까지 연결되는지 확인한다. API 경로와
테스트 파일명은 구현 담당자 합의 전 제안 상태다.

표의 `/overview`, `/objects`, `/operations`, `/reports/executive`는 목표 설계 경로다.
현행 경로는 [현행 MVP 구현 계약 기준선](./current-mvp-implementation-baseline.md)의
`/dashboard`, `/results/latest`와 Event API이며, 최종 결정 후 두 계약의 매핑을
추가해야 한다.

| 요구사항 | 기능 | 화면 | API | 스키마 | 테스트 |
|---|---|---|---|---|---|
| CM-01 동일 자산·시각 | FEAT-CM-002/003 | 전체 | 전체 응답 `as_of` | DataStatus, provenance | TC-CM-001 화면 간 동일성 |
| CM-02 원천·파생 구분 | FEAT-CM-003 | 전체 | 상세·보고서 | ResultArtifact, provenance | TC-CM-002 출처 보존 |
| CM-03 위험 enum | FEAT-CM-005 | 전체 | 목록·상세 | `status_grade` | TC-CM-003 enum 검증 |
| CM-04 상태 접근성 | FEAT-CM-005 | 전체 | 해당 없음 | 표시 매핑 | TC-UI-001 색상+문구 |
| CM-05 버전 표시 | FEAT-CM-003 | 전체 | 목록·상세·보고서 | provenance | TC-CM-004 버전 일치 |
| CM-06 화면 상태 | FEAT-CM-004 | 전체 | 오류 envelope | DataStatus | TC-UI-002 상태별 UI |
| CM-07 truth 비노출 | 전체 | 전체 | 전체 | 제품 스키마 제외 | TC-SAFE-001 truth 차단 |
| OV-01 설비 현황 | FEAT-OV-001 | Overview | GET `/overview` | OverviewSummary | TC-OV-001 가동 합계 |
| OV-02 위험 현황 | FEAT-OV-002 | Overview | GET `/overview` | status_counts | TC-OV-002 등급 합계 |
| OV-03 유형 요약 | FEAT-OV-003 | Overview | GET `/overview` | asset_type_counts | TC-OV-003 유형 합계 |
| OV-04 상위 위험 | FEAT-OV-004 | Overview | GET `/overview` | AssetPredictionSummary | TC-OV-004 정렬·중복 |
| OV-05 운영 요약 | FEAT-OV-005 | Overview | GET `/overview` | OverviewSummary | TC-OV-005 Operations 일치 |
| OV-06 상세 이동 | FEAT-OV-006 | Overview→Objects | GET `/objects/{id}` | `asset_id` | TC-E2E-001 문맥 유지 |
| OB-01 설비 목록 | FEAT-OB-001 | Objects | GET `/objects` | 목록 envelope | TC-OB-001 필터·페이지 |
| OB-02 기본정보 | FEAT-OB-002 | Objects | GET `/objects/{id}` | AssetDetail | TC-OB-002 Asset 일치 |
| OB-03 최신 센서 | FEAT-OB-003 | Objects | GET `/objects/{id}` | Observation | TC-OB-003 유형별 필드 |
| OB-04 센서 추세 | FEAT-OB-004 | Objects | GET `/objects/{id}/observations` | Observation[] | TC-OB-004 기간·센서 |
| OB-05 예측 결과 | FEAT-OB-005 | Objects | GET `/objects/{id}` | ResultArtifact | TC-OB-005 Artifact parity |
| OB-06 판단 근거 | FEAT-OB-006 | Objects | GET `/objects/{id}` | TopFactor[3] | TC-OB-006 순서·부호 |
| OB-07 설비 관계 | FEAT-OB-007 | Objects | GET `/objects/{id}` | AssetRelation | TC-SAFE-002 인과 금지 |
| OB-08 정비 이력 | FEAT-OB-008 | Objects | GET `/objects/{id}/maintenance` | MaintenanceEvent | TC-OB-008 자산 범위 |
| OP-01 생산 현황 | FEAT-OP-001 | Operations | GET `/operations` | 운영 요약 | TC-OP-001 목록 합계 |
| OP-02 생산 목록 | FEAT-OP-002 | Operations | GET `/operations/production` | ProductionCycle | TC-OP-002 Artifact 결합 |
| OP-03 정비 현황 | FEAT-OP-003 | Operations | GET `/operations` | 운영 요약 | TC-OP-003 목록 합계 |
| OP-04 정비 목록 | FEAT-OP-004 | Operations | GET `/operations/maintenance` | MaintenanceEvent | TC-OP-004 필터 |
| OP-05 운영 영향 | FEAT-OP-005 | Operations | GET `/operations` | 파생 집계 | TC-SAFE-003 비용·인과 금지 |
| OP-06 상세 이동 | FEAT-OP-006 | Operations→Objects | GET `/objects/{id}` | `asset_id` | TC-E2E-002 문맥 유지 |
| EX-01 보고 기준 | FEAT-EX-001 | Report | POST `/reports/executive` | ReportContext | RPT-TC-001 |
| EX-02 핵심 현황 | FEAT-EX-002 | Report | POST `/reports/executive` | ReportSummary | RPT-TC-001/003 |
| EX-03 위험 분포 | FEAT-EX-002 | Report | POST `/reports/executive` | status_counts | RPT-TC-001 |
| EX-04 상위 설비 | FEAT-EX-003 | Report | POST `/reports/executive` | ReportRiskAsset | RPT-TC-002/003 |
| EX-05 운영 요약 | FEAT-EX-002 | Report | POST `/reports/executive` | ReportSummary | RPT-TC-001 |
| EX-06 시사점·근거 | FEAT-EX-004 | Report | POST `/reports/executive` | EvidenceReference | RPT-TC-004/005 |
| EX-07 한계 | FEAT-EX-006 | Report | POST `/reports/executive` | limitations/provenance | RPT-TC-008/009 |
| EX-08 실패 대체 | FEAT-EX-005 | Report | POST `/reports/executive` | generation_method | RPT-TC-006/007/010 |

## 2. 누락 검사

- 모든 화면 요구사항에 기능 ID가 있다.
- 모든 데이터 기능에 스키마가 있다.
- 쓰기 기능은 미합의로 필수 추적표에서 제외했다.
- 실제 API 경로와 테스트명이 확정되면 제안값을 교체해야 한다.


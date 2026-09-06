# 독립 공장 현황 페이지 기준 로컬 브랜치 흡수 계획

## 기준과 범위

2026-09-07 기준 대상은 `codex/standalone-factory-main`이다. 원격 조회 후 `origin/main` ec7d05f3가 현재 HEAD f89da53a의 조상임을 확인했다. 현재 미커밋 변경을 먼저 커밋·푸시하고 초안 PR로 보존한다. 이 문서는 흡수 계획이며 다른 브랜치 병합 완료 보고가 아니다.

## 브랜치별 판정

비교 수치는 각 브랜치와 main의 공통 조상 이후 변경 파일을 현재 작업 파일과 바이트 단위로 비교한 값이다. 파일 차이는 기능 누락의 증명이 아니며, 동일 파일 수 역시 전체 기능 검증을 뜻하지 않는다. 삭제 항목은 이 수치에서 제외했다.

| 브랜치 | tip | 동일 / 상이 / 현재 경로 없음 | 흡수 방식 |
|---|---|---|---|
| three-role-backend-read-contract | f89da53a | 68 / 8 / 0 | 현재 HEAD와 동일 조상. 이미 포함돼 있으므로 중복 병합 금지. 상이 8개는 이후 현 작업 변경 |
| backend-integration-main | 2e666e6d | 54 / 18 / 21 | 최우선: materialization·Context 계약·CI·React 소비 경로 비교. 이미 포함된 의미는 제외하고 누락 기능만 이식. 검증 문서는 당시 실행 증거로 구분 |
| pm-gold-scorer-live-fix | 69c73810 | 21 / 19 / 10 | AI 생산 근거·평가 검증을 다음 순위로 이식. 작업 복사본의 미커밋 변경을 별도 스냅샷으로 보존한 뒤 비교 |
| operations-traceability-integration | b330ae9f | 0 / 11 / 2 | ViewModel·React 소비자와 추적성 마이그레이션을 함께 검토. 0049 PostgreSQL / 0045 SQLite 번호를 그대로 복사하지 말고 현재 이력과 내용 비교 |
| factory-status-first-screen-brief | eb7aef62 | 0 / 0 / 1 | 원본 설계 문서 1개를 참고 이력으로 보존. 구현 요구사항과 차이는 따로 표기 |
| main | ec7d05f3 | 현재 브랜치 조상 | PR 전 다시 fetch하여 새 변경이 생겼을 때만 통합 |

## 다른 작업 복사본

- backend-integration-main 작업 복사본: clean.
- pm-gold-scorer-live-fix 작업 복사본: AI tool pipeline·summary·provider와 평가 파일 등 수정 5개, 평가 문서·테스트 등 미추적 항목 존재. 이번 푸시에는 포함하지 않는다.
- detached 1589d99e 작업 복사본은 독립 작업 상태로 보존한다.
- 브랜치 삭제, reset, 전체 폴더 덮어쓰기, 무조건적인 cherry-pick은 하지 않는다.

## 기능별 진행 순서

1. 현 브랜치 전체 작업 및 검증 자료를 초안 PR에 고정한다.
2. backend-integration의 18개 차이 파일을 `계약 → 저장 → API → ViewModel → UI → 테스트`별로 분류한다. 현재 SQL schema/event binding 개선을 되돌리지 않는다.
3. pm-gold 작업 복사본의 미커밋 변경을 별도 보존한 뒤, AI 생성/검증 변경만 현 summary와 통합한다. 실제 provider 결과와 deterministic/fixture 평가를 분리한다.
4. traceability는 현재 마이그레이션 중복·번호·업그레이드 경로를 먼저 해결하고 양 DB 및 UI 소비자 테스트와 함께 반영한다.
5. 문서·평가 이력은 코드 검증과 분리하여 반영한다.
6. 기능 단위 커밋마다 범위 테스트와 PostgreSQL 실제 조회를 수행하고 PR 본문을 갱신한다. 흡수 전후 출처 commit, 변경 기능, 제외 이유, 검증 결과를 표로 남긴다.

## 현 PR에서 완료로 간주하지 않는 사항

- 전체 설비의 AI 브리핑 자동 생성: 아직 연결되지 않았다. 현재는 권한 있는 사용자의 명시적 생성과 저장 결과 조회다.
- 모든 압축기의 생산 의존 Context: 공급 대상 시나리오의 v2 상세 검증은 CMP-S03-L03-01 범위다.
- 단위는 등록된 가정이며 원천 검증된 물리 단위나 정상 운전 범위가 아니다.
- 목표 역할과 기존 점검 API 권한 차이는 남아 있다. 역할 탭은 실제 권한을 늘리지 않는다.
- 일정 협의, 실제 생산 회복, 전체 저장 액션 E2E, 운영 배포 검증을 완료로 보고하지 않는다.

## 이번 푸시 전 검증

- 백엔드 대상 테스트: 124 passed, 7 skipped. skip은 실제 PostgreSQL 검증 성공으로 해석하지 않는다.
- 프론트 독립 페이지·라우팅: 24 passed.
- 프론트 빌드: 성공(단위 매핑 변경 시 실행).
- 로컬 PostgreSQL 기반 API와 세 역할 브라우저 검증은 `docs/eval/standalone-page-2026-09-06`에 보존. 각 문서는 실행 당시 버전/범위의 기록이며 최신 전체 시스템 성공을 뜻하지 않는다.
- 새 파일 포함 비밀키 패턴 검사: 발견 없음. 테스트 계정 정보는 로컬 시연용이다.

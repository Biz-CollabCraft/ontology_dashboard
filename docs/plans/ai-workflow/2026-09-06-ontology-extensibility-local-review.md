# 온톨로지 확장성 관련 로컬 브랜치 검토
검토일: 2026-09-06

## 결론
원천 Context와 사건 연결을 분리하고 저장 스키마 버전으로 해석하는 변경은 구현되어 있다. 설비 중심 조회는 유지된다. 따라서 “원천 재사용과 스키마 변경을 고려한 근거 저장 구조”가 정확한 설명이다. 범용 Object/Link 모델이나 대규모 처리 성능을 검증했다고 말하지 않는다.

## 검토 대상
- 발표 문서 저장 브랜치: codex/pm-gold-scorer-live-fix, 69c73810. 아래 변경은 이 브랜치에 포함되어 있지 않다.
- 저장 구조: codex/backend-integration-main, 2e666e6d. 핵심 변경 60cc8060 및 2e666e6d. 작업 폴더 깨끗함.
- 조회 계약: codex/three-role-backend-read-contract, f89da53a. 저장 구조를 선택 이관하고 공통 조회 API를 추가한 별도 브랜치. 작업 폴더 깨끗함.
- 로컬 ref와 작업 폴더 기준 검토. 원격 main 반영·배포 상태를 판정하는 리뷰가 아니다. 브랜치 전환·merge·코드 수정 없음.

## 변경의 의미
1. operational_context_sources는 조직/프로젝트/워크스페이스/설비/도메인/원천 버전으로 불변 원천을 저장한다.
2. operational_context_bindings는 원천과 Evidence snapshot 연결 및 사건별 영향 정보를 저장한다. 동일 원천 계획을 두 사건에 연결해도 원천은 1개, 연결은 2개다. 사건 연결이 원천 필드를 덮어쓰지 못한다.
3. source_version과 schema_version을 구분하고 저장된 schema_id/version에 맞는 validator를 선택한다. 최신 앱 모델의 기본값으로 과거 원본을 다시 쓰지 않는다. 미지원 버전은 실패로 처리한다.
4. source/binding 양쪽 checksum을 fingerprint에 포함한다. 같은 시점에 Context 집합을 한 번 확보해 조회와 캐시 판단에 사용한다.
5. 별도 read-contract 브랜치는 출처·버전·유효기간·미연결 사유를 공통 API로 전달한다. 명령이나 LLM 생성을 실행하지 않는 조회다.

## Claim 판정
| 주장 | Evidence state | Architecture fit | 근거 |
|---|---|---|---|
| 같은 원천 버전을 여러 사건에 재사용 | Verified | Pass | storage_records, evolution 다중 사건 테스트 실행 |
| 저장 스키마별 해석·과거 원본 보존 | Verified | Pass | registry, v1→v2 앱 변경 및 과거 조회 테스트 실행 |
| 미지원·손상·만료·다른 scope 차단 | Verified | Pass | repository 검증 및 SQLite 회귀 |
| 공통 조회 API·Packet 전달 | Verified (로컬 계약 범위) | Pass | read_view/router와 API·Packet 관련 테스트 실행 |
| 새 공통 API의 브라우저 연결 | Not Proven | Unknown | 해당 브랜치는 프론트 변경/E2E를 완료 범위에서 제외 |
| 설비 중심을 벗어난 범용 관계 확장 | Not Proven | Unknown | asset_id 필수, source identity 및 SQL 조회에 포함 |
| 실제 제조 시스템 연동·대규모 처리 확장성 | Not Proven | Unknown | 합성·로컬 계약 검증이며 해당 운영 평가 없음 |

검토한 범위에서 새로 확정한 correctness 결함은 없다. 신규 도메인 자동 등록이나 범용 그래프 지원으로 발표하는 것은 구현보다 넓은 주장이다. DOMAINS/VALIDATORS/ports가 고정되어 있어 새 도메인·스키마에는 validator와 소비 경로 변경이 필요하다.

## 이번 실행
기존 main 작업 폴더의 Python 환경을 재사용하되 PYTHONPATH는 각 검토 checkout의 systems/backend로 지정했다. integration 자체 환경에는 pytest가 없어 초기 실행은 실패했고, 사용 가능한 환경으로 재실행했다.
- backend-integration: test_operational_context_evolution.py + test_operational_context_repository.py → 19 passed / 19 skipped, 5.54초.
- three-role: test_operational_context_read.py → 8 passed / 3 skipped, 3.21초.
- skipped는 일회용 PostgreSQL 미가용 경로. PostgreSQL RLS·팀 DB 현재 상태는 이번 실행으로 확인하지 못했다.
- read-contract 테스트는 APP_ENV=test 및 명시적 heuristic fallback 사용. live 모델 품질 증거가 아니다.
- 팀 DB에 과거 합성 14건을 적재했다는 문서는 읽었지만 팀 DB 재조회는 하지 않았다.

## 발표 3장에 권장하는 구성
- 문제: 설비 중심으로 자료를 묶어도 같은 원천 계획을 사건마다 복제하면 원천 버전과 사건별 영향이 섞인다. 앱 모델 변화가 과거 자료의 해석을 바꿀 수도 있다.
- 선택: 원천 자료와 사건 연결을 분리하고 저장 스키마별로 해석한다.
- 결과: 원천 계획 재사용, 과거 버전 의미 보존.
- 즉시 검증: 원천 1개→사건 연결 2개, 원천 변경 거부, v1 자료 보존 테스트.
- 보조: 필요한 근거를 AI에 전달하는 Selection 29→8은 별도 단계다. 관계 구조 확장성의 수치로 쓰지 않는다.

권장 대본:
“설비를 중심으로 생산과 정비 정보를 연결했습니다. 그런데 같은 생산계획이 여러 사건에 쓰이고 데이터 형식도 바뀔 수 있어, 사건마다 자료를 복제하는 방식에는 한계가 있었습니다. 그래서 원천 자료와 사건별 연결을 분리하고, 저장 당시의 스키마 버전으로 읽도록 바꿨습니다. 같은 원천 하나를 두 사건에 연결해도 원천이 중복되거나 바뀌지 않는지, 앱 모델이 바뀌어도 과거 자료가 그대로 읽히는지를 테스트했습니다.”

권장 시각화: 생산계획 v1 원천 카드 1개 → 사건 A / 사건 B 연결 2개. 옆에 저장 schema v1 → v1 해석, 새로운 schema v2 → v2 해석. asset 범위는 유지하고 여러 설비 공유까지 그리지 않는다.

## 코드 근거
- backend-integration systems/backend/app/infra/db/operational_context_repository.py:24,119,215,242,293
- backend-integration systems/backend/app/operations/operational_context_versions/registry.py
- backend-integration tests/test_operational_context_evolution.py:23,42,54,77,101,119,129
- backend-integration docs/operations/operational-context-db-migration.md
- three-role systems/backend/app/operations/router.py:1176
- three-role tests/test_operational_context_read.py
- three-role docs/operations/three-role-backend-read-contract.md

발표 제작 문서 본문은 이번 검토에서 변경하지 않았다. 변경된 온톨로지 설명과 브랜치별 근거를 먼저 이 검토 기록으로 남겼다.

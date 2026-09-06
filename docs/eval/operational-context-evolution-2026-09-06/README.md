# 운영 Context 스키마 보완 및 DB 적용 증거

2026-09-06, `codex/backend-integration-main`, 직전 기준 `60cc8060`. 이 디렉터리와 함께 커밋된 코드가 검증 대상이다. PR #166을 다시 수정하거나 merge한 작업이 아니라, 통합 브랜치의 운영 Context 후속 보완이다.

## 근본 원인과 수정

| 재현한 문제 | 수정 | 새 회귀 증거 |
|---|---|---|
| 현재 앱 모델로 payload 정규화 후 checksum을 검증해 optional 기본값 추가만으로 과거 자료가 failed로 변함 | 원본 checksum을 먼저 검증하고 저장된 schema_id/version의 동결된 계약으로 검증 | v2 optional 필드 추가를 모사해도 v1 원본/조회 유지, 미지원 버전 차단 |
| 원천 버전 PK에 event가 없어 같은 계획의 두 이벤트가 immutable 충돌 | 불변 source와 event binding/projection 분리 | 같은 owner version으로 source 1건/binding 2건, 원천 사실 변경은 여전히 거부 |

P1 두 건은 SQLite/PostgreSQL에서 보완 확인. planning 검증도 ViewModel의 현재 스키마에서 독립시켰다. 범용 Object/Link 연결, 라인/주문/공유 자원 subject, 도메인 port 등록은 후속 P2로 유지한다. 임의 JSON이나 AI가 원천 사실·risk·authorization·상태 전이를 쓰는 경로를 추가하지 않았다.

## 실행 결과

| 범위 | 결과 | 증거 |
|---|---|---|
| backend 회귀 | 398 passed / 2 skipped | [원본 출력](backend-regression.txt) |
| 스키마 진화 전용 | 14 passed; 위 398에 포함 | [원본 출력](schema-evolution-tests.txt) |
| 배포 가드/DDL 원자성 | 추가 3 passed | [원본 출력](deployment-tests.txt) |
| 기존 로컬 PG 자료 이관 | 원본 14 유지, 새 sources/bindings 각각 14, 재실행 unchanged 14 | [해시 및 수량](local-migration.json) |
| 실제 팀 DB 사전 검사 | 정확한 demo scope/asset, pending 0049/0050, manifest hash 확인 | [preview](team-db-preview.json) |
| 실제 팀 DB 적용 | 한 트랜잭션 commit, sources 14 / bindings 14 | [apply](team-db-applied.json) |
| 실제 팀 DB 재실행 | pending 없음, inserted 0 / unchanged 14 | [repeat](team-db-reapply.json) |
| 실제 팀 DB 재조회 | 버전별 validator/checksum을 거친 14건이 seed payload와 정확히 일치 | [readback](team-db-readback.json) |
| 재시작한 로컬 API | health/Packet/Detail 200, JSON Schema 유효, 동일 snapshot/evidence, 요약 저장본 재사용 | [API 결과](runtime-api.json) |

총 실행 결과는 회귀 398 + 배포 3 = 401 passed, 2 skipped이다. 스키마 전용 14건을 다시 더하지 않는다. skip은 SQLite 대상 PostgreSQL 전용 RLS 검사와 제거된 AdaptiveWorkbench 대상이다. 실제 PostgreSQL RLS 검사는 별도로 실행됐다.

회귀 범위에는 snapshot mismatch, malformed/provider failure containment, retry/fallback, summary reuse, atomic/stale-worker fencing, deterministic selection, gold/eval, 계약 벡터 및 ViewModel이 포함된다. 배포 검사는 잘못된 host/hash의 연결 전 거부, seed 단계 강제 실패 시 DDL+marker rollback, 미검토 pending migration 거부를 격리 PostgreSQL에서 검증한다. 새 테스트 파일은 backend CI 목록에 포함했다. GitHub CI 실행 결과는 이 기록의 로컬 테스트 결과와 다르다.

관련 테스트는 PostgreSQL 테스트 환경을 준비하고 다음과 같이 재실행한다.

```sh
python -m pytest -q tests/test_operational_context_evolution.py \
  tests/test_operational_context_deployment.py tests/test_operational_context_repository.py \
  tests/test_operational_context_import_cli.py
```

## 트랜잭션의 의미

DDL만 성공하고 seed가 실패한 상태가 남지 않도록 migration SQL, schema_migrations marker, source와 binding을 한 PostgreSQL transaction으로 commit한다. 기존 advisory migration lock도 함께 사용한다. 계획 source가 저장된 뒤 binding 충돌이 발생해도 해당 배치의 신규 source는 rollback된다. 기존 원본은 삭제/수정하지 않는다. 이것은 DB 원자성 보장이며 원격 앱 배포까지 원자적으로 완료했다는 의미가 아니다.

## 주장 경계와 남은 배포 작업

- 실제 팀 DB에 반영한 자료는 **합성 데모 14건**이다. 실 MES/WMS/QMS 적재 증거가 아니며 `synthetic_demo_context`와 원래 유효기간을 유지했다.
- 로컬 원본 checksum은 복사 전후 `d281c080dd002325c5700648f34de15e0ff1383ef429c22c258335324868e4f1`로 같다. 기존 원본 테이블은 유지했다.
- 8월 29일 이벤트와 일치하는 계획은 없다. Packet과 ViewModel 모두 영향 미산정/temporal unknown을 유지했다. 임의 fixture 기간 연장은 하지 않았다.
- 로컬 API 요약은 기존 `deterministic_fallback` 저장본을 재사용했다. 새 외부 LLM 호출·품질 평가의 증거가 아니다. 이전 후보에서 얻은 live-provider 결과를 이번 코드의 품질 수치로 옮기지 않는다.
- **운영 DB 적용 완료, 원격 애플리케이션 코드 배포 미실시.** 새 코드의 로컬 backend vertical slice는 확인했으나 원격 앱 연결 및 전체 브라우저 E2E 완료를 주장하지 않는다.
- 발표에서 현재 이벤트의 숫자 생산 영향 또는 원격 신버전 앱을 보여줘야 한다면, 일치하는 승인된 원천 자료와 앱 배포가 여전히 필요하다. DB migration 자체의 blocker는 해소됐다.

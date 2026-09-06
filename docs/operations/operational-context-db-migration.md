# 운영 Context DB 이관

생산·정비 준비·품질/납기·계획·영향 계산 정책을 버전과 시점이 고정된 DB Context로 읽는다. 진단 risk, 추천 액션, 권한 및 Closed-loop 상태 전이는 기존 계층이 결정한다. AI는 근거를 설명하고 원천 Context를 쓰거나 승인하지 않는다.

## 최종 저장 계약

- `operational_context_sources`: 조직/프로젝트/워크스페이스/설비/도메인/원천 버전으로 식별하는 불변 원천 자료. `schema_id/schema_version`은 원천의 `source_version`과 별개다. 출처, 합성 여부, 갱신 시점, 유효기간, freshness 정책, 원본 payload와 checksum을 저장한다.
- `operational_context_bindings`: source와 Evidence snapshot의 연결 및 이벤트별 영향 projection. 같은 계획 버전을 여러 이벤트에 연결할 수 있다. source의 사실을 변경하려면 새 source_version이 필요하다. 연결 payload는 원천 필드를 덮어쓸 수 없다.
- 기존 `operational_context_snapshots`는 삭제하지 않는다. 기존 행은 검증 후 위 두 테이블로 복사하며 원본과 checksum을 보존한다.

PostgreSQL에는 0049 다음 0050, SQLite에는 0045 다음 0046을 적용한다. 두 새 테이블 모두 append-only이며 PostgreSQL은 tenant RLS를 강제한다. source와 binding 적재는 하나의 트랜잭션이다. 하나라도 충돌하면 그 배치 전체를 취소한다.

조회는 저장한 원본 checksum을 먼저 검증하고 저장된 schema 버전의 validator로 해석한다. v1 Pydantic 계약은 `operational_context_versions/v1.py`, planning v1은 독립된 `operational-context-planning-v1.schema.json`에 고정했다. 현재 앱 모델이나 ViewModel의 기본값 추가로 과거 저장 내용을 재정규화하지 않는다. 새 스키마는 별도 validator와 consumer 변환을 추가해야 한다. 미지원 버전은 값을 숨긴다.

선택한 Evidence의 as-of에서 유효한 자료만 선택한다. 동률은 원천 갱신 시점·버전 및 정확한 event 연결 우선순위로 결정한다. source와 binding 양쪽 checksum이 cache fingerprint에 반영된다. 만료·미연결·손상·DB 장애를 fixture로 대체하지 않는다.

## 기존 데이터 복사

프로젝트 환경에서 DB URL을 secret으로 설정하고 저장소 루트에서 실행한다.

```sh
python scripts/migrate_database.py
python scripts/import_operational_context.py --legacy \
  --organization-id YOUR_ORG --project-id YOUR_PROJECT --workspace-id YOUR_WORKSPACE
# 검증한 동일 범위에 --apply를 추가해 복사한다.
```

`migrate_database.py`는 모든 미적용 SQL을 실행하므로 목록을 먼저 검토해야 한다. legacy 복사는 원본 checksum 및 v1 계약을 검증하며 원본을 수정하지 않는다. 재실행은 unchanged이다. 로컬 합성 demo의 복사는 비운영 환경에서 명시적으로 `--allow-demo`를 사용한다. production importer는 이 옵션이 있어도 합성 자료를 거부한다.

## 실제 원천 자료 적재

실 MES/WMS/QMS 자료는 원천 담당자가 `owner_system` manifest로 제공한다. 기존 fixture의 표시만 바꾸면 안 된다. importer용 URL과 `APP_ENV=production`을 설정한다.

```sh
python scripts/import_operational_context.py \
  --manifest /secure/owner-context.json \
  --organization-id YOUR_ORG --project-id YOUR_PROJECT --workspace-id YOUR_WORKSPACE
# 검증 후 동일 명령에 --apply 추가
```

manifest 기본 실행은 DB에 접속하지 않는 계약 검증이다. 한 배치는 한 tenant/workspace 범위이며 동일 버전·다른 내용은 전부 rollback한다. runtime 계정에는 SELECT, importer에는 SELECT/INSERT가 필요하다. superuser/BYPASSRLS 계정에 의존하지 않는다.

## 승인된 팀 DB의 Manufacturing Demo 적용

2026-09-06 실제 env와 접속 권한을 확인했다. canonical DATABASE_URL은 비어 있고 TEAM_DB_*가 설정돼 있으며, `ontology_service`는 관련 테이블 소유 및 쓰기 권한이 있다. 이전의 “기본 계정이 읽기 전용이라 적재할 수 없다”는 설명은 이 env에 해당하지 않았다. URL이나 비밀번호를 로그에 남기지 않는다.

`deploy_operational_context.py`는 env의 canonical URL 또는 TEAM_DB_*를 읽는다. 정확한 host, 실제 프로젝트/workspace와 asset 존재를 확인하고 검토된 0049/0050 외의 pending migration은 거부한다. preview에서 확인한 manifest checksum이 일치해야 적용한다. SQL, migration marker, seed를 같은 트랜잭션에 넣는다. 실패 시 모두 rollback한다.

```sh
PYTHONPATH=systems/backend python scripts/deploy_operational_context.py \
  --env-file /secure/team.env --expected-host YOUR_REVIEWED_HOST \
  --organization-id org-ontology-demo --project-id manufacturing-demo-project \
  --workspace-id manufacturing-demo --demo-fixtures --evidence /tmp/context-preview.json
# 검토한 동일 인자에 --apply --expected-manifest-sha256 PREVIEW_HASH 추가,
# --evidence는 별도의 적용 결과 파일로 지정한다.
```

`--demo-fixtures`는 위의 정확한 Manufacturing Demo 범위에만 허용한다. 운영 DB에 저장해도 자료는 `synthetic_demo_context`이며 APP_ENV를 바꿔 production 검증을 우회하지 않는다. 원래의 유효기간을 유지하므로 8월 29일 최신 결과에는 일치하는 계획이 없어 영향이 미산정일 수 있다.

실제 적용: 0049/0050 완료, sources 14 / bindings 14, 재적용 inserted 0 / unchanged 14, repository를 통한 14건 재조회 원본 일치. [실행 증거](../eval/operational-context-evolution-2026-09-06/README.md)를 참조한다. DB 적용과 원격 앱 배포는 별개이며 이번에는 원격 앱 배포를 수행하지 않았다.

## 범위와 복구

새 버전으로 정정하며 과거 행을 덮어쓰지 않는다. 기존 데이터가 있는 환경은 새 reader 배포 전에 legacy 복사를 완료한다. 이전 테이블은 보존하지만 이전 앱으로 rollback하면 이전 fixture 경로가 복원될 수 있으므로 동작 연속성을 보장한다고 주장하지 않는다.

이 구조는 설비별 decision-support read model이다. 라인·주문·공유 자원의 일반 Object/Link binding, source-system namespace, 도메인 port 등록 체계와 MES/WMS/QMS 자동 동기화는 후속 범위다. 스키마 버전과 이벤트 연결 문제 해결이 범용 온톨로지 확장성이나 대규모 성능 검증을 뜻하지 않는다.

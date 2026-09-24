# Ontology P0 실행 결과 — snapshot 계약 경계에서 중단

- 날짜: 2026-09-23
- 판정: **제한된 PostgreSQL 지연·문맥 변경 재현 완료 / 엄격한 exact-snapshot gate 미충족 / 전체 지속 부하 P0 미완료 / STOP**
- 제품 개선: 0회. 커밋·푸시·배포·운영 DB·실제 유료 LLM 사용 없음.
- 기준 HEAD: `71337cddd755eaa8cdb762af4598e21b2f7d085f`.
- 실행 위치: DevSpace Max `/Users/hb/Projects/ontology-dashboard`, workspace `ws_98abfab73c`.
- 근거 디렉터리: `experiments/ontology_p0_20260923/`.

## 결론

작은 실제 PostgreSQL 재현에서 GET은 생성하지 않았고, 10초 provider 대기 중에도 응답했다. 생성 중 같은 event의 operational context를 바꾸자 저장 직전 snapshot guard가 결과를 차단했다. 그러나 exact 저장본이 없는 GET은 기존 설계대로 이전 설명을 `LATEST_STORED`로 반환한다. 따라서 계획의 “반환 설명과 요청 snapshot 일치”라는 엄격한 조건은 충족하지 않는다.

이 반환은 숨겨진 최신 상태 재결합이 아니다. 원래 summary key와 provenance가 유지되며 프런트엔드는 “저장된 브리핑 · 이전 업무 시점 기준”으로 표시한다. **현재 계약과 계획의 엄격한 조건 사이의 차이**가 확인됐다. 이 차이를 임의로 통과 처리하거나 제품을 바꾸지 않고 확대 실험을 중단했다. 지속 이벤트에서 안정적인지라는 전체 질문에는 아직 결론을 내릴 수 없다.

## 작업 시작 계약

- Observed problem: 지속 이벤트×느린 provider 조건의 근거 공백. 운영 장애를 관측했다는 주장은 하지 않는다.
- Human hypothesis: unrecorded.
- AI/challenger hypotheses: 순차 생성·scan 후 대기가 준비시간을 늘릴 수 있으며, historical fallback은 exact readiness와 다를 수 있다.
- Falsification condition: 동일 정상/지연 workload에서 scoped correctness와 GET·대조 설비·pending 추이가 유지되면 해당 전파 가설을 기각한다. 이번에는 전체 workload 전에 strict gate가 미충족됐다.
- Decision required: 이전 시점 설명의 표시를 허용할지, 최신 설명 readiness와 어떤 계약으로 구분할지.
- Human decision: pending. Changed belief: unrecorded.

## 실제 실행과 수치

정상 watcher scan으로 10개 설비의 저장본을 만든 뒤 한 설비의 동일 event context를 두 번 바꿨다. 두 번째 변경은 10초 provider 실행 중 발생했다. 모든 수치는 합성 자료와 provider test double을 사용한 **단일 프로세스 FastAPI TestClient** 관측이다.

| 관측 | 실제 결과 |
|---|---|
| 원시 기록 | 179 JSONL rows |
| GET | 5회: pending 1, exact validated 1, disclosed historical 3 |
| provider 경계 호출 | 정상 10 + 지연 1 = 11 |
| GET 유발 provider 호출 | 0, 요청 context로 귀속 |
| 동일 exact key 중복 호출 후보 | 0, 이 작은 표본 범위 |
| 최초 miss GET | HTTP202, 106.5ms |
| exact hit GET | HTTP200, 204.3ms |
| context 변경 후 GET | HTTP200 LATEST_STORED, 128.1ms |
| 느린 생성 중 GET | HTTP200 LATEST_STORED, 116.8ms |
| 생성 종료 후 GET | HTTP200 LATEST_STORED, 139.5ms |
| 지연 provider 실제 구간 | 10.065초 |
| 해당 생성 전체 | 10.251초 |
| 해당 생성의 provider 외 시간 | 약 0.186초; 개별 DB wait로 분해한 값은 아님 |
| 저장 결과 | 무효화된 in-flight key와 새 context key 모두 미저장, worker 종료 |
| 저장 차단 원인 | DB workflow: `agent_review_context_changed_during_generation` |
| 보호 업무 테이블 | 9개 전후 digest 동일; 모두 초기·최종 0행 |

5개의 GET으로 운영 p95나 지연 격리 성능을 주장하지 않는다. oracle의 기계적인 p95 필드는 작은 표본 요약일 뿐이다. 정상 0.1초 지정 provider의 실제 구간도 약 0.102~0.176초였으며, 실험 자원과 계측 오버헤드를 포함한다.

## 원인 근거

1. `systems/backend/app/operations/service.py::cached_agent_review_summary_for_packet`는 exact lookup 후 miss이면 동일 scope/asset/event/history의 최신 저장본을 가져온다. `reuse_eligibility=LATEST_STORED`이며 현재 packet 검증을 통과한 exact 재사용으로 세면 안 된다.
2. `systems/frontend/src/features/operations/overview/NaturalBriefing.tsx`는 이 경로를 이전 업무 시점의 저장본으로 표시한다. 새 identity로 이전 설명을 바꾸어 저장한 증거는 없다.
3. raw context mutation 두 건 모두 context hash와 key를 변경했다. 후속 GET 세 건은 요청 key와 다른 원래 key를 반환했다.
4. workflow `8fb511cc-4860-41e9-bedb-be8637293c56`는 2026-09-23T09:18:22.776975Z~09:18:32.965106Z, status=failed, error_message=`agent_review_context_changed_during_generation`이다. 이 DB 근거와 미저장 key 검사를 함께 사용해 저장 보호를 확인했다.
5. 기존 SQLite 테스트는 의도적인 이전 저장본 반환 테스트 1개 통과, 변경 snapshot에서 None을 기대하는 기존 테스트 1개 실패였다. 새 diagnostic은 역사 반환·원래 key 유지·GET 호출0을 확인했다. 서로 다른 기대를 결과에서 숨기지 않았다.

watcher의 순차 후보 처리와 scan 종료 후 60초 sleep은 코드로 확인했지만, 이번 결과로 지속 workload 병목이나 처리 한계를 정량 확정하지 않는다.

## 대안 비교 — 구현·채택하지 않음

| 선택 | 동작 | 장점 | 비용·판별 기준 |
|---|---|---|---|
| 0. 현 구조 유지 | exact miss에도 명시적 이력 설명 표시 | 기존 가용성과 UX 유지 | 계획의 엄격한 gate 미충족을 인정해야 함. HTTP200을 최신 ready로 세면 안 됨 |
| 1. exact-only 응답 | 현재 key가 없으면 pending, 이력은 별도 조회/표시 | strict snapshot 계약을 직접 만족시킬 방향 | 현재 유용한 이전 설명 가용성 감소. 동일 변경 probe에서 pending 및 GET 호출0 확인 필요 |
| 2. 이력과 현재 readiness 분리 | historical summary와 current-ready 상태를 API/판정에 별도로 표현 | 이전 설명과 최신 준비 여부를 함께 전달 | 클라이언트와 계약의 구분 비용. 계획 변경은 사용자 결정. 같은 workload에서 둘을 분리 집계해야 함 |

대안의 성능 향상이나 비용 절감 수치는 측정하지 않았다. Queue·OTel·새 정책·CI 변경을 선택하지 않았다. 개선0회이므로 before/after 재검증은 해당 없음이며, 다음 loop는 시작하지 않았다.

## 실행 환경과 보존

전용 `ontology-p0-20260923-pg`, localhost55433, PostgreSQL16, CPU2·memory2GiB. 이미지 digest는 supervisor-contract.md에 기록했다. 실제 migrations와 합성10설비 bundle, DB-backed Product Result, 기존 watcher/service/validation/publish/GET/auth 경로를 사용했다. provider 출력은 계약용 test double이며 품질·비용·실제 HTTP retry 평가가 아니다.

runtime preflight는 bootstrap superuser를 사용했으므로 그 실행의 RLS 강제를 검증하지 않았다. 별도 작은 제한 역할 probe는 `ontology_p0_app`의 superuser=false/BYPASSRLS=false, `pm_assets` 정상 scope10·다른 project0을 확인했다. 이것을 전체 API/테이블의 RLS 보장으로 확대하지 않는다.

초기 preflight01/02/02b/02c는 fixture provenance·schema·dataset identity 오류로 provider 경로에 도달하지 못했다. 이를 제품 장애나 정상/느린 표본으로 합치지 않았다. 원시 시도와 수정 원인은 attempts.md에 보존했다. 기존 dirty AGENTS.md, plans README, engineering workflow, 승인 계획서의 SHA256은 시작·종료 동일했다. 제품 소스 diff 없음. 추가 파일은 실험 디렉터리와 이 결과 문서뿐이다.

동일 Max의 재고관리 감독과 부하 직렬화에 합의했다. 이번 작은 preflight에는 다른 실험의 최소 correctness 준비·시험이 겹쳤을 가능성이 있으며 배타적 CPU 측정을 주장하지 않는다. 양쪽 모두 full stress를 실행하지 않았다.

## Known Limitations

| 조건 | 실제 증거/미검증 | 이번 결론에 대한 영향·제외 이유 | 별도 후속 질문 |
|---|---|---|---|
| 지속 이벤트와 3회 반복 | 미실행, measurement poll0 | 전체 P0 완료 불가; strict gate에서 확대 중단 | 허용 계약 확정 후 동일 workload의 준비시간/GET 영향은? |
| timeout→복구·300초 drain | 미실행 | 복구·backlog 보장 없음 | 최신 required 상태가 얼마나 빨리 준비되는가? |
| 10설비0.2event/s sequence | manifest에 준비했으나 재생 안 함 | manifest duration480은 실행시간이 아님 | 정상/지연쌍의 superseded·pending 분모는? |
| 실제 네트워크·다중 worker·crash | 미검증 | TestClient 단일 프로세스 범위 | 배포 topology에서 같은 보호가 유지되는가? |
| DB scope/RLS | runtime admin, 별도 pm_assets만 제한-role 확인 | tenant 격리 전체 보장 없음 | 제한 runtime role 전체 경로는? |
| 업무 side effect | 9개 빈 테이블의 전후 digest 동일 | 전체 DB 또는 일시 생성·삭제 탐지 아님 | 필요한 업무 테이블/감사 범위는? |
| provider 품질·retry·청구 | test double만 사용 | 실제 모델 품질·비용 주장 없음 | 이번 P0 범위 밖 |
| observer 독립성 | 입출력 identity + service-derived key 비교 | 암호학적 key 구현 자체의 독립 oracle은 아님 | 별도 계약 시험 필요 여부 |
| 임계 SLA | 사용자 freshness 목표 없음 | 제품 허용 지연을 AI가 확정하지 않음 | 요구 freshness와 historical 허용 범위는? |

## 재현 자료

첫 항목은 저장소 root 기준이며, 나머지 항목은 `experiments/ontology_p0_20260923/` 기준이다:
- `experiments/ontology_p0_20260923/README.md`: harness/실행 범위.
- `supervisor-contract.md`: 작업 계약·보존 hash·자원 구분.
- `runner.py`, `fixture.py`, `oracle.py`: 실행과 독립 분석.
- `runs/preflight-03/raw.jsonl`: raw SHA256 `3558b87b21ca999556b106042d9158e54c15b13e94d89cce8d6ac523b54649dd`.
- `runs/preflight-03/manifest.json`: fixture hash, migrations, default topology, 준비된 event sequence.
- `runs/preflight-03/failed-workflow-forensic.json`: 저장 차단 DB 근거.
- `runs/preflight-03/revision-hashes.json`: 코드·의존성·근거 hash.
- `runs/preflight-03/oracle.json`, `oracle-result.md`: 독립 검토.
- `rls-probe.json`: 제한 역할의 좁은 RLS probe.
- `attempts.md`, `oracle-existing-tests.txt`, `oracle-api-diagnostic.txt`: 실패 시도와 진단.

전용 컨테이너는 증거 저장 후 중지했으며 DB를 포함해 보존했다. `resource-closeout.md`에 기록했다.

최종 상태: **strict contract 불일치 재현 및 원인 확인 후 STOP. 전체 P0 측정 완료나 제품 보강 완료로 표시하지 않는다.**

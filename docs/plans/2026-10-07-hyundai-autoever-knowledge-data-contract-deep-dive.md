# 현대오토에버용 지식 데이터 계약 Deep-dive 계획

- 작성일: 2026-10-07
- 저장소: `/Users/hb/Projects/ontology-dashboard`
- 시작 revision: `352984a7` (문서 전용 브랜치 `codex/portfolio-company-deepdives`)
- 범위: 지원용 근거 보강 계획. 이 문서는 구현, 성능 주장, 지원서 반영을 승인하지 않는다.

## Problem framing

- **Observed problem:** 현재 저장소에는 AI 브리핑의 원천·snapshot·재사용 상태를 API/타입/UI에서 분리한 focused synthetic contract evidence가 있다. 그러나 지원처가 요구하는 문서 수집·정제·분할·메타데이터·지식 품질 관리와 직접 이어지는, 작은 단위의 재현 가능한 지식 데이터 흐름 증거는 아직 없다.
- **Human hypothesis:** unrecorded.
- **Prediction:** unrecorded.
- **AI/challenger hypothesis:** 하나의 승인된 비민감 문서에서 `원문 → immutable snapshot → segment/metadata → 품질 상태 → 조회 응답 → UI disclosure`를 연결하고, exact/historical/ineligible 상태를 동일한 계약으로 검증하면 기존 readiness 작업을 지식 데이터 관리 역량으로 좁고 정직하게 보강할 수 있다.
- **Falsification condition:** (a) 원문과 segment 또는 metadata 사이의 provenance를 재현할 수 없거나, (b) 세 상태의 API와 UI 의미가 달라지거나, (c) 문서 처리 결과가 실제 지식 품질·현재성 대신 단순 파일 업로드 성공만 보이면 이 축을 채택하지 않는다.
- **Decision required:** 사용할 문서의 출처·공개/비민감성, historical fallback 허용 정책, 실제 provider 호출 허용 여부, Kubernetes 개인 검증 범위를 사용자가 결정한다.
- **Unknowns:** 현재 서비스에서 문서 ingest/chunk/search가 이미 어느 수준까지 존재하는지, 적절한 공개 문서 fixture, 지원 시점의 정확한 JD 문구.
- **Stop condition / budget:** P0~P2의 한 문서·세 상태·focused test 범위까지만 한다. 대규모 corpus, Hadoop/Spark/Hive 운영, 실제 사내 연계, production 성능, 사용자 효용은 범위 밖이다.

## Existing evidence and claim boundary

이미 근거가 있는 것은 `EXACT_VALIDATED`, `LATEST_STORED`, `INELIGIBLE`와 `current_ready`/`historical_available`의 분리, fallback의 fail-closed 처리, focused backend 4개 및 frontend/API/UI 20개 검사다.

다음은 아직 주장하지 않는다.

- Hadoop, Spark, Hive 기반 파이프라인을 구현하거나 운영했다.
- 실제 문서 검색 품질·embedding·RAG 품질을 운영에서 검증했다.
- 실제 provider, multi-worker, 대규모 처리량, 운영 배포를 검증했다.
- 팀의 LLM runtime, 전체 UI 통합, 배포를 개인 기여로 수행했다.

개인 기여 표기는 `Backend Intelligence & Dynamic Reporting` 범위로 제한한다. Kubernetes/CI-CD는 팀 환경 여부와 개인이 재현한 검증을 별도로 표기한다.

## Alternatives

| 선택지 | 내용 | 판별 기준 |
| --- | --- | --- |
| Baseline | 현재 readiness 계약과 synthetic focused test만 evidence card로 정리한다. | 새 ingest 경로 없이도 데이터 품질/현재성 역량을 충분히 설명 가능한가. |
| Challenger | 승인된 공개 문서 1종에 대해 snapshot·segment metadata·상태 계약을 실제로 연결한다. | 문서 provenance와 상태가 API/UI까지 보존되는가. |
| Rejected shortcut | 파일 업로드·청크 수·HTTP 200만 보여준다. | 품질/현재성/근거를 판별하지 못하므로 채택하지 않는다. |

## Work slices

### P0 — 현재 증거의 기준선 고정

1. 기존 readiness plan/evidence/decision과 코드 경로를 한 장의 evidence map으로 연결한다.
2. raw prediction이 Product Result/Evidence로 승격되는 경계, snapshot identity, 상태 enum, API, ViewModel/UI를 표시한다.
3. 기존 synthetic 검증의 revision·fixture·한계를 명시한다.

**Acceptance:** HTTP 200 또는 비어 있지 않은 summary가 current-ready와 동치가 아니라는 설명을 코드 경로와 테스트로 추적할 수 있다.

### P1 — 최소 문서 지식 데이터 흐름

1. 사용자가 승인한 공개·비민감 문서 1종을 고정 fixture로 정한다.
2. 원문 hash, 수집 시각, source URI/식별자, parser version을 snapshot으로 남긴다.
3. segment에는 source span, ordering, metadata schema version, snapshot reference를 둔다.
4. 누락·파싱 실패·snapshot mismatch를 명시적 상태로 만들고, 추정으로 정상화하지 않는다.

**Invariants:** segment는 하나의 snapshot에만 귀속된다. 원문 변경 뒤 이전 segment가 current로 보이지 않는다. metadata가 없으면 검색/재사용 적격성을 승격하지 않는다.

### P2 — 현재성 계약과 소비 경계 연결

1. exact validated, disclosed historical, ineligible/fallback의 세 fixture를 만든다.
2. service→repository→router→API type→ViewModel/UI가 동일한 상태를 보존하는지 focused contract test로 확인한다.
3. UI에는 source/as-of, current 여부, historical 사유, 다음 행동을 표시한다.

**Metrics:** 상태 pair 정확성, snapshot/segment provenance 일치, provider-call count, stale save count. 미측정 성능·검색 정확도는 `not measured`로 남긴다.

### P3 — 운영 증거 후보 (별도 승인 후)

Kubernetes/CI-CD를 보강하려면 Deployment/Service, Config/Secret 경계, readiness/liveness, 구·신 계약 호환성, 재시작 또는 rollback을 격리 환경에서 재현한다. 이는 P0~P2 통과 뒤에도 자동 시작하지 않는다.

## Discriminating experiment

- **Fixture/workload:** P1 문서 1종과 정확/과거/부적격 3 fixture. 실제 provider 호출은 별도 승인 전에는 하지 않는다.
- **Baseline:** 기존 summary readiness 경로.
- **Challenger:** snapshot-bound segment/metadata와 상태 contract를 함께 소비하는 경로.
- **Adoption gate:** provenance와 세 상태가 end-to-end로 일치하고 failure disclosure가 API/UI에서 보이면 P1~P2 evidence를 채택한다. 하나라도 어긋나면 구현을 확장하지 않고 evidence에 FAIL/STOP을 기록한다.

## Deliverables and evidence

- `docs/plans/`의 본 계획
- 실행 뒤 별도 `docs/evidence/` 기록: revision, 환경, fixture 출처, 명령, raw 결과 위치, 측정 한계
- 별도 `docs/decisions/` 기록: historical fallback 및 다음 slice 채택 여부 — 사용자 소유
- 지원용 1페이지: 문제 → 데이터 계보 → 상태표 → 코드/테스트 → 한계 → 개인/팀 경계

## STOP

이 문서 작성만으로 새 데이터 파이프라인 구현을 시작하지 않는다. P1 시작은 문서 fixture와 product policy에 대한 사용자의 명시 승인 후에만 가능하다.

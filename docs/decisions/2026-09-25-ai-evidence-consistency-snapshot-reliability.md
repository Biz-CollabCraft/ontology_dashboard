# Decision record(결정 기록): AI Evidence Consistency(AI 근거 일관성) & Snapshot Reliability(스냅샷 신뢰성)

- Date(날짜): 2026-09-25
- Repository(저장소): `/Users/hb/Projects/ontology-dashboard`
- Evidence(근거): `docs/evidence/2026-09-25-ai-evidence-consistency-snapshot-reliability.md`
- Human hypothesis(사람 가설): unrecorded(미기록)
- Human decision(사람 결정): pending(대기)
- Changed belief(변경된 믿음): unrecorded(미기록)

## Decision required(필요한 결정)

다음 product policy(제품 정책)는 사람 소유로 남긴다.

1. exact-only(정확 일치 전용): 새 snapshot의 validated summary(검증된 요약)가 없으면 pending(대기)을 반환한다.
2. exact current-ready(정확 현재 준비) + disclosed historical fallback(명시된 과거 대체): 과거 저장본은 제공하되 current-ready와 명시적으로 분리한다.
3. historical fallback(과거 대체) 유지 범위: 어떤 화면·역할·freshness(신선도)에서 허용할지 정한다.

## Decision Gate comparison(결정 게이트 비교)

| Option(선택지) | Concrete response(구체 응답) | Existing evidence(기존 근거) | User impact(사용자 영향) | Unresolved requirement(미해결 요구) |
| --- | --- | --- | --- | --- |
| exact-only(정확 일치 전용) | exact validated(정확 검증됨) key가 없으면 `202` pending(대기)만 반환한다. | 2026-09-23 P0에서 first miss(최초 불일치)는 `202`, GET provider call(조회 제공자 호출)은 0회였다. | 오래된 prose(문장)를 현재 결과로 오해할 여지를 가장 작게 한다. 현재 summary가 없을 때 읽을 설명도 없다. | 허용 가능한 pending duration(대기 시간)과 freshness objective(신선도 목표)를 사람이 정해야 한다. |
| disclosed historical fallback(명시된 과거 대체) | exact miss(정확 불일치)에서는 `LATEST_STORED`, `current_ready=false`, `historical_available=true`와 이전 시점 표시를 반환한다. | P0는 context mutation(문맥 변경) 뒤 original key(원래 키) provenance(출처)를 유지한 historical response(과거 응답)를 관측했다. 현재 API/UI tests(테스트)는 이 boolean pair(불리언 쌍)와 이전 시점 표시를 확인한다. | 과거 설명을 계속 읽을 수 있다. 소비자가 current-ready(현재 준비)와 historical(과거)을 구분해야 한다. | 어떤 screen(화면), role(역할), freshness window(신선도 구간)에서 이를 허용할지 사람이 정해야 한다. |
| fallback readiness normalization(대체 요약 준비 상태 정규화) | deterministic fallback(결정론적 대체)은 `INELIGIBLE`, `false`, `false`이며 fallback reason(대체 사유)을 유지한다. | 이번 focused backend/API test(집중 백엔드/API 테스트)는 invalid provider candidate(잘못된 제공자 후보)를 이 상태로 확인했다. | fallback을 validated current(검증된 현재)로 표시하지 않는다. | 이 변경은 위 두 response policy(응답 정책) 중 하나를 선택하지 않으며 fallback visibility(대체 표시 범위)는 별도 사람 결정이다. |

이 표는 adoption(채택) 결정이 아니다. 수치·provider readiness(제공자 준비)·multi-worker behavior(다중 워커 동작)·production usability(운영 사용성)는 이 비교의 근거가 아니다.

## Prepared implementation candidate(준비된 구현 후보)

fallback summary(대체 요약)를 `EXACT_VALIDATED` / `current_ready=true`로 승격하지 않도록 service readiness normalization(서비스 준비 상태 정규화)을 좁게 바꾼다. 이는 exact-only와 disclosed-history 중 어느 정책도 채택하지 않으며 fallback reason(대체 사유)과 materialization status(구체화 상태)를 보존한다.

## STOP(중단)

focused validation(집중 검증) 뒤 이 Decision Gate에서 멈춘다. 사용자의 policy 선택 없이 API response semantics(응답 의미), historical UI(과거 UI), provider retry(제공자 재시도), cache migration(캐시 마이그레이션), multi-worker(다중 워커)를 확장하지 않는다.

# 솔루션링크용 Evidence-aware AI Solution Deep-dive 계획

- 작성일: 2026-10-07
- 저장소: `/Users/hb/Projects/ontology-dashboard`
- 시작 revision: `352984a7` (문서 전용 브랜치 `codex/portfolio-company-deepdives`)
- 범위: 지원용 AI 솔루션·사용자 흐름 보강 계획. 이 문서는 구현, 외부 배포, 지원서 반영을 승인하지 않는다.

## Problem framing

- **Observed problem:** 기존 readiness 계약은 API/타입/UI에 상태를 전달하지만, 사용자가 AI 브리핑을 요청하고 근거·상태·다음 행동을 이해하는 완결된 제품 흐름으로 검증된 것은 아니다. 결과가 존재해도 최신 근거인지, 과거 저장본인지, 생성 불가인지 사용자에게 어떻게 전달할지가 사용성 관점에서 남아 있다.
- **Human hypothesis:** unrecorded.
- **Prediction:** unrecorded.
- **AI/challenger hypothesis:** 하나의 실제 UI 여정에서 근거, as-of, 상태, 다음 행동을 함께 전달하고, 오류/과거/부적격 응답을 최신 AI 판단처럼 표시하지 않도록 검증하면 AI 솔루션의 full-stack 경계를 보여줄 수 있다.
- **Falsification condition:** (a) 상태가 화면에서 사라지거나 문구와 API 의미가 충돌하거나, (b) 사용자가 historical/fallback을 current 결과로 오인할 수 있거나, (c) 데모가 fixture 하드코딩 또는 성공 화면만으로 이루어지면 이 축을 채택하지 않는다.
- **Decision required:** 대표 사용자 역할과 행동, historical 결과를 제공할 화면·조건, 화면 시연의 공개 범위, 실제 provider 호출 여부를 사용자가 정한다.
- **Unknowns:** 솔루션링크의 지원 직무/JD 최종 문구, 현 프런트의 상태 소비 경로, 대표 시나리오가 실제로 UI까지 연결되어 있는지.
- **Stop condition / budget:** API·프런트 한 개 여정, 실패 포함 focused regression, 30~60초 시연 재현까지만 한다. 대규모 UX 리디자인, 모델 품질 평가, production deployment는 범위 밖이다.

## Existing evidence and claim boundary

현재 근거는 source/provenance·snapshot·readiness·fallback 상태를 API/타입/UI 계약으로 보존한 focused synthetic 검증이다. 이것은 제품 UI 전체, 실제 LLM provider, response latency, 사용자 만족도, production availability 증거가 아니다.

솔루션링크용 메시지는 “AI가 정답을 냈다”가 아니라 다음으로 한정한다.

> AI 응답의 근거 시점과 검증 상태를 API와 화면에서 함께 전달해, 사용자가 최신 결과·이전 저장본·검증 불가를 구분하고 다음 행동을 선택하도록 설계한다.

## Alternatives

| 선택지 | 내용 | 판별 기준 |
| --- | --- | --- |
| Baseline | 상태 enum과 UI 문구를 정적 화면/문서로만 제시한다. | 실제 요청·응답 경계가 확인되지 않는다. |
| Challenger | 한 사용자 요청을 API 응답과 상태별 UI, 다음 행동까지 실제로 연결한다. | 정상/과거/부적격에서 오인이 없는가. |
| Rejected shortcut | 성공한 current 화면만 녹화한다. | 실패와 상태 경계를 숨기므로 채택하지 않는다. |

## Work slices

### P0 — 대표 시나리오와 계약 현황 확인

1. 기존 UI에서 실제로 소비하는 API 응답과 ViewModel을 확인한다.
2. 단일 사용자 여정을 고정한다: `브리핑 요청 → 결과/근거 확인 → 상태 이해 → 가능한 다음 행동 선택`.
3. representative scenario에 포함할 상태를 확정한다: exact current, disclosed historical, ineligible/fallback.

**Acceptance:** 각 화면이 어떤 API field를 읽고, 사용자가 어떤 행동을 할 수 있는지 표로 추적된다.

### P1 — 상태를 행동 가능한 UI로 연결

1. current 결과에는 근거 시점과 검증 상태를 표시한다.
2. historical 결과에는 이전 저장본임과 기준 시각/사유를 표시하고, 현재 결과처럼 시각적 우선순위를 주지 않는다.
3. ineligible/fallback에는 생성된 답변처럼 보이는 카드 대신 이유와 재시도·검토 등 허용된 다음 행동만 제시한다.
4. legacy/신규 API 응답의 정규화가 같은 사용자 의미를 유지하는지 확인한다.

**Invariants:** HTTP 성공 여부만으로 green/current 상태를 만들지 않는다. fallback은 current-ready로 승격되지 않는다. UI는 원천이 없는 확신 문구를 생성하지 않는다.

### P2 — API·프런트 회귀 및 실패 경로 검증

1. 세 상태 fixture로 router/service/API type/ViewModel/UI contract test를 만든다.
2. 네트워크 오류, 빈 요약, scope/snapshot mismatch, legacy 응답을 별도 case로 둔다.
3. 한 상태를 수정했을 때 다른 상태의 문구·행동이 변하지 않는지 regression을 확인한다.

**Metrics:** 상태별 렌더링 결과, CTA 노출 여부, API/UI enum·boolean pair 일치, provider call count. UX 만족도·실제 사용자 전환율은 측정하지 않았다고 기록한다.

### P3 — 재현 가능한 시연과 포트폴리오 근거

1. 격리 환경과 고정 fixture에서 P0 대표 시나리오를 재생한다.
2. 정상 화면만이 아니라 historical 또는 ineligible 한 경우를 1회 포함한다.
3. 30~60초 시연은 사용자 흐름을 보여주고, 별도 evidence card에는 상태표·API 경로·테스트 범위·한계를 둔다.

**Acceptance:** 시연이 코드와 fixture로 다시 재현되고, “운영 검증” 또는 “모델 정확도” 같은 미측정 주장을 포함하지 않는다.

## Discriminating experiment

- **Fixture/workload:** 상태 3종과 오류 2종의 고정 API fixture, 격리 프런트/백엔드 실행 환경.
- **Baseline:** 현재 상태 정보가 일부 누락되거나 성공 화면 중심인 소비 흐름.
- **Challenger:** 상태·근거·CTA를 API와 UI에서 명시적으로 보존하는 흐름.
- **Adoption gate:** 모든 fixture에서 UI 문구, CTA, 상태 field가 일치하고 브라우저 시연으로 재현되면 채택한다. 오인 가능성이 하나라도 있으면 데모·지원 문구에 사용하지 않고 STOP한다.

## Deliverables and evidence

- `docs/plans/`의 본 계획
- 실행 뒤 `docs/evidence/`: revision, 실행 환경, fixture, 테스트·시연 결과, 영상/스크린샷의 재현 방법, 한계
- 실행 뒤 `docs/decisions/`: historical/fallback 소비 정책과 지원용 채택 여부 — 사용자 소유
- 포트폴리오 카드: 문제 → 사용자 여정 → 상태/근거 경계 → 테스트 → 개인/팀 범위 → 한계

## STOP

이 문서 작성은 계획 단계다. P1 구현은 대표 시나리오와 historical/fallback 제품 정책을 사용자가 선택한 뒤에만 시작한다. 실제 provider·외부 배포·사용자 테스트는 별도 승인 없이는 실행하지 않는다.

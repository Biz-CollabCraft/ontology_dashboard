# Ontology Dashboard — Engineering Foundations Upgrade

- 작성일: 2026-09-20
- 상태: P0-P2 implemented and verified
- 대상: `Biz-CollabCraft/ontology_dashboard`
- 기준 문서:
  - `docs/operations/current-operations-implementation-baseline.md`
  - `docs/plans/ai-workflow/`
  - `docs/eval/`
  - `docs/architecture-decisions/`

## 목적

이 프로젝트를 단순 "LLM 브리핑 기능"이 아니라 **불확실한 AI를 제조 운영 시스템 안에서 신뢰성 있게 사용하는 구조**로 더 명확하게 증명한다.

기존 강점인 evidence selection, snapshot consistency, generation/read separation, deterministic fallback, 장애 주입 평가를 유지하면서 다음 세 영역을 보강한다.

1. briefing observability
2. AI authority / security boundary
3. scale behavior와 비용 구조

## 공통 원칙

- Event/Evidence/Decision/Action의 canonical 제품 계약을 임의 변경하지 않는다.
- 기존 검증 수치와 보고서를 재사용할 때 실험 조건을 함께 보존한다.
- LLM은 위험등급, 권한, 승인, 상태전이의 최종 소유자가 아니다.
- 운영 최신 결과와 fixture/fallback을 구분한다.
- Kubernetes 등 인프라 도입은 부하 측정 결과가 필요성을 보여줄 때만 후속 제안한다.
- 현재 다른 작업의 미커밋 변경을 흡수하거나 되돌리지 않는다.

## 실행 순서

### P0 — Briefing Observability
문서: `01-briefing-observability.md`

한 briefing 생성/재사용 결정의 입력 근거, snapshot, selection, model call, validation, cache/reuse, latency를 추적한다.

2026-09-20 기준 `briefing-operational-trace-v1.0` 구현과 회귀 검증을 완료했다. 구현·검증 상세와 기존 baseline test conflict는 P0 문서에 기록한다.

### P1 — AI Authority & Security Boundary
문서: `02-ai-authority-security.md`

LLM과 deterministic system의 책임 경계를 문서화하고 malformed output, stale context, prompt/evidence 공격면을 검증한다.

2026-09-20 기준 S1~S5 security regression과 evidence-injection fixture, unknown action-token fail-closed 검증을 완료했다.

### P2 — Scalability Evaluation
문서: `03-scalability-evaluation.md`

100/500/1000 asset 시나리오에서 watcher/change detection/candidate generation/LLM call 구조를 측정해 실제 병목을 찾는다.

2026-09-20 기준 local detection 실측 + 기존 live-provider latency replay 기반 scale evaluation과 bounded-queue challenger 비교를 완료했다. serial baseline은 9개 중 8개 scenario에서 10초 deadline을 초과했고, 주 병목은 provider/concurrency projection으로 확인됐다. Kubernetes/HPA 필요성은 입증되지 않았다.

## Engineering 결론

2026-09-20 P0~P2 결과를 합치면 이 프로젝트의 핵심은 단순한 "LLM 브리핑 생성"이 아니다.

1. **신뢰성 — P0**
   - briefing 하나가 어떤 Event/Evidence snapshot과 selection 결과를 사용했는지 `trace_id`로 추적한다.
   - 생성/재사용 이유, provider/validation 실패, fallback, token/latency를 서로 구분한다.

2. **권한 경계 — P1**
   - LLM은 grounded summary와 설명을 생성하는 expression layer다.
   - RBAC, `available_actions`, 승인, 상태전이, snapshot consistency, fallback 선택은 deterministic system이 소유한다.
   - evidence 안의 instruction-like text는 data로 취급하며 system instruction으로 승격하지 않는다.

3. **확장성 — P2**
   - 100/500/1000 asset synthetic workload에서 local change detection p95 최대는 evaluator artifact 기준 약 **0.743 ms**였다.
   - 10초 poll 조건에서 serial provider replay는 **9개 scenario 중 8개**에서 deadline을 초과했다.
   - 8-worker bounded queue는 end-to-end latency를 개선했지만 모든 medium/burst workload를 해소하지 못했다.
   - 따라서 현재 확인된 우선 병목은 watcher CPU가 아니라 **provider latency/concurrency와 generation scheduling**이다.
   - Kubernetes/HPA 또는 단순 서버 증설 필요성은 이 평가만으로 입증되지 않았다.

### 대외 설명 / 포트폴리오 경계

다음 표현은 현재 evidence 범위에서 사용할 수 있다.

> 100·500·1000대 설비 시나리오를 평가해 로컬 변경 감지보다 LLM provider latency가 주요 병목임을 확인하고, bounded queue·coalescing 구조의 효과와 한계를 비교했습니다.

면접에서 구조적 판단까지 설명할 때는 다음과 같이 말할 수 있다.

> 처음에는 polling 자체가 병목일 수 있다고 가정했지만, 100/500/1000대 조건에서 측정한 결과 local change detection은 10초 주기에 비해 매우 작았습니다. 반면 기존 live-provider latency를 replay하면 순차 생성은 대부분의 workload에서 deadline을 넘었습니다. 그래서 인프라를 바로 확장하기보다 변경 감지 후 필요한 건만 생성하고, 같은 설비의 아직 시작하지 않은 오래된 candidate를 최신 candidate로 합치는 구조를 먼저 검증했습니다.

다음 표현은 사용하지 않는다.

- "1000대 설비를 실시간으로 지원한다."
- "1000대 환경에서 실제 OpenAI throughput을 검증했다."
- "8-worker 구조가 10초 SLA를 보장한다."
- "Kubernetes가 필요하다/불필요하다가 확정됐다."
- "실제 운영 비용 절감이 검증됐다."

P2에서 local detection은 실제 코드 실행 측정이지만 provider 구간은 기존 live-provider 측정 latency를 재생한 projection이다. 이 둘을 같은 종류의 실측으로 표현하지 않는다.

## 완료 조건

- 한 briefing lifecycle을 end-to-end trace로 설명할 수 있다.
- AI가 소유하지 않는 결정과 권한 경계가 테스트로 고정된다.
- scale 관련 주장은 반복 가능한 부하 테스트에서 나온다.
- synthetic fixture와 실제 provider 호출 결과를 구분한다.
- 포트폴리오에는 이 레포의 검증된 evidence만 전달한다.

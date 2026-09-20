# Ontology Dashboard — Engineering Foundations Upgrade

- 작성일: 2026-09-20
- 상태: planned
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

### P1 — AI Authority & Security Boundary
문서: `02-ai-authority-security.md`

LLM과 deterministic system의 책임 경계를 문서화하고 malformed output, stale context, prompt/evidence 공격면을 검증한다.

### P2 — Scalability Evaluation
문서: `03-scalability-evaluation.md`

100/500/1000 asset 시나리오에서 watcher/change detection/candidate generation/LLM call 구조를 측정해 실제 병목을 찾는다.

## 완료 조건

- 한 briefing lifecycle을 end-to-end trace로 설명할 수 있다.
- AI가 소유하지 않는 결정과 권한 경계가 테스트로 고정된다.
- scale 관련 주장은 반복 가능한 부하 테스트에서 나온다.
- synthetic fixture와 실제 provider 호출 결과를 구분한다.
- 포트폴리오에는 이 레포의 검증된 evidence만 전달한다.

# P2 — Scalability Evaluation

## 문제

현재 데모의 10초 주기 감시와 briefing generation 정책을 100대 이상 설비로 일반화하려면 실제 호출량, queue pressure, latency, token/cost를 측정해야 한다.

목표는 Kubernetes를 도입하는 것이 아니라 **어디서 scale 문제가 발생하는지 증명하는 것**이다.

## 비교 구조

### Baseline

현재 watcher/polling/generation 정책을 가능한 한 그대로 재현한다.

### Candidate

필요할 경우 다음과 같은 구조를 challenger로 둔다.

```text
poll/watch
  → deterministic change detection
  → briefing candidate
  → bounded queue
  → generation worker
  → persistence/cache
```

challenger는 baseline 측정 후에만 구현/채택한다.

## Workload

최소:

- 100 assets
- 500 assets
- 1000 assets

각 workload에 대해 이벤트 변화율을 따로 둔다.

예:

- low-change: 대부분 상태 동일
- medium-change
- burst/high-change

모든 asset이 10초마다 의미 있게 변한다고 가정하지 않는다.

## 측정값

### Watch/Detection
- poll/read operations/sec
- changed assets/events
- candidate generation rate
- detection latency

### Queue/Workers
- queue depth
- queue wait p50/p95
- worker utilization
- dropped/coalesced candidate count
- end-to-end p50/p95

### LLM
- LLM calls/min
- generated vs reused briefing count
- input/output tokens
- estimated/provider-reported cost
- provider latency
- concurrency

### Correctness Invariant
최적화 때문에 다음이 조용히 감소하면 안 된다.

- mandatory evidence recall
- important-event detection
- snapshot consistency
- latest valid briefing availability

## 테스트 원칙

- 인프라 부하는 mock provider로 먼저 측정
- 실제 LLM은 작은 표본으로 latency/token/cost만 확인
- mock 결과를 실제 provider throughput으로 주장하지 않음
- 동일 workload로 baseline/challenger 비교
- 최소 3회 반복하고 편차를 기록

## 채택 Gate

queue/worker 또는 수평 확장 구조는 다음 중 하나 이상이 관측될 때 고려한다.

- polling loop가 deadline을 지속적으로 초과
- queue wait가 사용자/운영 허용치를 초과
- provider concurrency 제한 때문에 backlog 누적
- 단일 process CPU/memory 병목
- 장애 격리를 위해 worker 분리가 필요

Kubernetes/HPA는 stateless worker 수평 확장이 실제로 필요한 후속 단계일 뿐, P2 완료 조건이 아니다.

## 완료 조건

- 100/500/1000 asset 동일 조건 결과표
- baseline 병목 위치 확인
- challenger가 있으면 같은 workload 비교
- correctness invariant 회귀 여부 기록
- 실제/모의 provider 경계 명시
- "설비 N대 지원" 같은 포트폴리오 주장은 측정 환경과 함께만 사용

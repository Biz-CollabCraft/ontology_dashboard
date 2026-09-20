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

## 구현 상태 — 2026-09-20

P2는 `scripts/evaluate_briefing_scalability.py`로 구현했다. 하네스는 측정 경계를 두 층으로 분리한다.

1. **로컬 실측:** 실제 `decide_generation()` 경로를 100/500/1000 asset × low/medium/burst change에 대해 3회 반복해 wall/process CPU를 측정한다.
2. **provider/queue projection:** 저장소에 이미 있는 2026-09-05 live-provider 120-run의 개별 latency/token row를 discrete-event replay한다. 이번 P2 실행에서 새 외부 LLM 호출은 0회다.

Baseline은 현행 serial watcher 형태이고, baseline deadline miss가 확인된 뒤 challenger로 latest-per-asset bounded queue + 8 worker를 같은 workload에 적용했다. queue capacity는 asset 수로 제한하고, 대기 중 같은 asset의 이전 candidate는 최신 candidate로 coalesce한다.

정본 결과:

- `docs/eval/engineering-foundations/briefing-scalability-2026-09-20.md`
- `docs/eval/engineering-foundations/briefing-scalability-2026-09-20.json`

### 결과 요약

- workload: 100 / 500 / 1000 assets
- change profile: 1% / 10% / 50%
- poll interval: 10초
- detection benchmark: 각 scenario 3회
- provider reference: 기존 live-provider 120 rows
- 새 외부 provider 호출: 0
- local detection wall p95 최대: evaluator commit `1e3da69e` artifact 기준 약 **0.743 ms**
- serial baseline deadline miss: **8 / 9 scenarios**
- 8-worker challenger가 모든 candidate를 10초 안에 완료한 scenario: **4 / 9**
- challenger candidate drop: **0**
- backlog 상황에서 same-asset superseded candidate는 coalesce
- 최신 changed asset materialization: evaluated challenger에서 100%
- cost: not configured
- memory: not measured

해석상 local change detection은 현재 병목이 아니다. 기록된 provider latency를 재생하면 serial generation이 대부분의 workload에서 10초 deadline을 넘긴다. 8-worker bounded queue는 end-to-end/queue wait를 크게 낮추지만 medium/burst workload를 모두 해소하지 못한다.

따라서 다음 우선순위는 provider concurrency limit, demand generation, batching/coalescing 정책의 재평가다. 이 결과만으로 Kubernetes/HPA 도입을 정당화하지 않는다. host memory도 측정하지 않았으므로 memory headroom 주장은 하지 않는다.

### 핵심 해석

이 평가에서 확인한 것은 "1000대 지원 가능"이 아니라 **설비 수 증가 시 어느 계층이 먼저 병목이 되는지**다.

- polling/change detection 자체는 현재 측정 범위에서 병목이 아니었다.
- serial LLM generation은 작은 변화율에서도 asset 수가 커지면 poll deadline을 넘겼다.
- worker 병렬화는 효과가 있었지만 burst workload에서는 provider-side backlog가 남았다.
- 따라서 다음 설계 판단은 서버 증설보다 generation demand를 줄이고 provider concurrency를 제어하는 쪽이 우선이다.

즉 아키텍처 판단 순서는 다음과 같다.

```text
더 큰 서버 / Kubernetes 선도입
        X
        |
실측 병목 확인
        ↓
change detection은 충분히 작음
        ↓
provider latency / concurrency가 병목
        ↓
demand generation + coalescing + bounded worker
        ↓
그래도 host/resource 병목이 측정될 때 수평 확장 검토
```

### 포트폴리오/면접 표현

권장 문장:

> 100·500·1000대 설비 시나리오를 평가해 로컬 변경 감지보다 LLM provider latency가 주요 병목임을 확인하고, bounded queue·coalescing 구조의 효과와 한계를 비교했습니다.

설명형 답변:

> 처음에는 polling 자체가 병목일 수 있다고 생각해 설비 수를 100·500·1000대로 늘려 측정했습니다. local change detection p95는 최대 약 0.743ms였지만, 기존 live-provider latency를 replay한 serial generation은 9개 시나리오 중 8개에서 10초 deadline을 넘었습니다. 8-worker 구조로 개선됐지만 medium/burst workload에는 backlog가 남아, Kubernetes보다 provider concurrency와 demand generation을 먼저 개선해야 한다고 판단했습니다.

주의: 위 수치에서 local detection은 실제 코드 실행 측정이고, provider/queue는 기존 live-provider latency를 이용한 replay/projection이다. 따라서 "1000대 실제 OpenAI 부하 테스트", "1000대 지원 검증", "10초 SLA 보장"으로 표현하지 않는다.

### Correctness invariant

- important-event detection: synthetic changed labels 기준 100%
- snapshot consistency: scheduler가 candidate version을 변경하지 않음
- latest valid changed asset: challenger 종료 시 최신 version materialization 100%
- candidate drop: 0
- mandatory evidence recall: scale scheduler가 evidence selection을 변경하지 않으며, 기존 `tests/test_operational_evidence_selection.py` 회귀로 별도 보호

이 하네스의 coalescing은 **같은 asset의 아직 시작하지 않은 과거 candidate를 최신 candidate로 교체**하는 scheduling 최적화다. 이미 시작한 generation의 결과를 다른 snapshot으로 재바인딩하지 않는다.

## 완료 조건

- [x] 100/500/1000 asset 동일 조건 결과표
- [x] baseline 병목 위치 확인
- [x] challenger를 같은 workload로 비교
- [x] correctness invariant 회귀 여부 기록
- [x] 실제/모의·replay provider 경계 명시
- [x] "설비 N대 지원" 같은 포트폴리오 주장은 측정 환경과 함께만 사용

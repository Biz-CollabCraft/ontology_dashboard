# Ontology Dashboard 범위·깊이·종료 검토

작성일: 2026-09-24  
기준 브랜치: `main` @ `fe866559`

## 1. 현재 변경사항 검토

현재 working tree의 실제 제품 변경은 없고, AI-assisted engineering rule과 2026-09-23 P0 contract-boundary 실험 증거가 추가되어 있다. P0는 exact snapshot과 historical fallback의 계약 차이를 재현한 뒤 의도적으로 STOP했다.

이 프로젝트는 이미 충분한 기능과 평가 자료가 있다. 현재 가장 큰 위험은 **추가 기능으로 기존 강한 증거를 희석하는 것**이다.

## 2. 대표 문제

> 여러 시점의 센서·정비·운영 근거를 AI 설명에 사용할 때 서로 다른 snapshot이 섞이지 않도록 하고, 필요한 근거만 결정론적으로 선택해 재현 가능한 판단 근거를 제공한다.

## 3. 깊이 축

### 축 A — snapshot consistency / cache identity

- snapshot identity를 무엇으로 정의하는지
- exact key와 latest stored를 왜 구분하는지
- context change during generation을 왜 저장 차단하는지
- stale read와 disclosed historical result의 차이
- cache invalidation 기준
- content hash/version/time 중 어떤 식별자가 어떤 한계를 갖는지

### 축 B — deterministic evidence selection

- 후보 27개에서 6개로 줄이는 selection contract
- 필수 근거 recall의 정확한 분모
- token 절감과 correctness 사이 trade-off
- LLM이 selector가 아니라 coordination/summary layer에 머문 이유
- fixture와 failure injection으로 regression을 어떻게 검증했는지

## 4. 현재 변경사항 수정 방향

### 유지

- snapshot guard
- generation/read separation
- deterministic selection
- historical fallback을 명시적으로 보여주는 현재 계약
- failure injection/evaluation evidence

### 지금 결정이 필요한 한 항목

2026-09-23 P0에서 확인된 다음 정책을 명시적으로 결정해야 한다.

- exact-only로 최신 readiness를 강제할지
- historical summary와 current-ready를 분리할지
- 현재 disclosed historical fallback을 유지할지

이 결정 전에는 workload 확대 실험을 재개하지 않는다.

### 중단

- 멀티에이전트 추가
- LangGraph 재도입
- 새로운 retrieval/RAG 구조
- 대규모 지속 부하 테스트
- queue/OTel 신규 도입
- 새로운 제품 기능

현재 핵심 질문을 해결하지 않는 확장은 닫는다.

## 5. 수정 순서

1. historical fallback/current readiness 정책을 문서에서 하나로 확정한다.
2. 선택한 계약을 API/ViewModel/eval terminology에 동일하게 반영한다.
3. 기존 P0 harness로 exact/historical/pending 상태를 다시 검증한다.
4. 기존 72-run 안정성 자료와 현재 P0를 혼동하지 않도록 평가 목적을 분리한다.
5. 포트폴리오 수치는 metric 정의가 불명확하면 제거한다.
6. 3분 설명과 15분 deep dive 질문 목록을 문서화한다.

## 6. 종료 조건

- snapshot key와 mismatch block을 코드 수준으로 설명 가능
- exact/current/historical 상태가 UI/API/eval에서 일관됨
- evidence selection의 recall/token 수치 정의가 명확함
- 실제로 측정한 범위와 합성 fixture 범위를 구분함
- 추가 agent 없이도 현재 문제를 완결된 이야기로 설명 가능

## 7. 면접 방어 질문

- snapshot key는 어떤 필드로 구성되고 왜 그런가?
- timestamp만으로 identity를 만들면 어떤 문제가 있나?
- context가 generation 중 변경되면 왜 결과를 버리나?
- historical fallback은 stale bug인가, 의도된 UX인가?
- 후보 27→6에서 필수 근거 recall 100%의 의미는?
- deterministic selector를 LLM selector보다 선택한 이유는?
- cache invalidation을 언제 수행하는가?

## 8. 다음 작업 1개

새 기능을 만들지 않는다. **P0가 드러낸 exact/current/historical 계약을 확정하고 기존 평가·포트폴리오 표현을 그 계약에 맞춰 정리한다.**

# P1 — AI Authority & Security Boundary

## 목적

AI가 잘못된 출력을 만들더라도 제품의 핵심 상태와 권한 경계를 넘지 못하도록 현재 설계를 명문화하고 회귀 테스트한다.

## 책임 경계

### LLM이 담당할 수 있는 것

- grounded briefing/summary 생성
- 선택된 evidence의 자연어 설명
- review/checklist 초안
- 이미 허용된 범위 안의 next-step 설명

### Deterministic System이 소유해야 하는 것

- identity / RBAC
- `available_actions`
- 위험 enum 및 canonical 상태 계약
- Decision/Note 저장 권한
- state transition
- snapshot/evidence consistency validation
- generation/reuse policy
- schema validation
- 승인 필요 여부
- fallback 선택

LLM 자연어가 위 deterministic state를 직접 덮어쓰지 않는다.

## 위협/실패 시나리오

### S1. Malformed model output
- schema 불일치
- 필수 필드 누락
- 허용되지 않은 action 문자열

기대: reject/fallback, canonical state 변경 없음.

### S2. Stale evidence
- 화면/현재 Event와 briefing snapshot 불일치

기대: 현재 guard 정책에 따라 차단 또는 명시적 재생성/hold.

### S3. Evidence text injection
센서 메모/작업자 note/evidence 문자열에 모델 지시문처럼 보이는 텍스트가 포함되는 경우.

기대:
- evidence는 data로 취급
- system/developer instruction처럼 승격되지 않음
- 권한/action contract 변경 불가

### S4. Unsupported action suggestion
LLM이 현재 role의 `available_actions` 밖 행동을 제안.

기대:
- 실행 권한 생성 금지
- UI/action contract는 backend deterministic result를 따름

### S5. Provider unavailable
기대:
- 현재 deterministic/template fallback 규칙 준수
- LLM 실패를 정상 생성으로 기록하지 않음

## 문서화 항목

- trust boundary diagram
- LLM input에 포함되는 데이터 클래스
- output validation point
- canonical state mutation point
- role/action authorization point
- fallback path

## 완료 조건

- S1~S5 회귀 테스트 존재
- LLM 결과가 RBAC/Action 계약을 우회하지 못함
- evidence injection fixture 존재
- raw chain-of-thought 저장을 요구하지 않음
- 사용자에게 보여주는 설명과 시스템 권한 판단을 분리

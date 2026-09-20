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

## Trust boundary

```text
Canonical Product Result / Event Evidence / owner records
                    |
                    v
        deterministic projection + selection
                    |
                    v
      Agent Review Packet (read-only data)
                    |
                    | JSON user payload
                    v
+---------------- LLM boundary ----------------+
| system prompt: authority/read-only contract  |
| evidence/note text: untrusted data only      |
| output: prose-only editable fields           |
+----------------------------------------------+
                    |
                    v
 schema + structured grounding + prose grounding
                    |
          +---------+---------+
          | valid             | invalid/provider failure
          v                   v
 grounded summary        deterministic fallback
          |                   |
          +---------+---------+
                    v
             read-only consumer

Mutation/authorization path is separate:
Identity/RBAC -> backend available_actions -> explicit API command
LLM summary output is not an input to this path.
```

### LLM input data classes

- deterministic risk/priority facts
- selected Evidence and source references
- inspection/SOP metadata
- operation/maintenance history context
- evidence gaps and limitations
- read-only Closed-loop boundary metadata

Evidence, operator notes and other free text remain **data inside the JSON user payload**. They are not concatenated into the system prompt and are not trusted as instructions.

### Validation / mutation / authorization points

- Output shape: editable summary JSON schema
- Structured grounding: source refs, asset/snapshot identity, evidence gaps, inspection focus
- Natural-language grounding: forbidden claims, directive prose, numeric/priority consistency, action-token checks
- Snapshot consistency: generation policy and current-packet guard before storage
- Canonical mutation: Decision/Note/maintenance APIs only, outside briefing generation
- Authorization: Identity/RBAC and backend-produced `available_actions`
- Fallback: malformed output or provider failure -> deterministic summary; failure reason remains observable

Raw chain-of-thought is neither requested nor stored. Operational trace stores bounded status, validation/failure metadata, IDs and timings only.

## 구현 상태 — 2026-09-20

P1은 기존 schema/grounding/snapshot/provider guards를 재사용하고, 누락됐던 **unknown action-like identifier** 차단을 보강했다. 생성 산문에 `delete_asset`, `restart_machine`처럼 명령 동사가 포함된 snake_case action token이 나오면 `unsupported_action_token`으로 fail-closed 한다. 일반 내부 필드명은 action으로 오탐하지 않도록 동사 기반으로 제한했다.

Evidence injection fixture는 `tests/fixtures/security/briefing_evidence_injection.json`에 고정했다. `tests/test_briefing_ai_authority_security.py`가 S1~S5를 직접 검증한다.

검증 결과:

- P1 S1~S5: 5 passed
- 기존 summary contract: P1 변경 관련 회귀는 통과
- 기존 summary contract 전체의 1개 실패는 clean HEAD에서도 동일 재현되는 baseline test mismatch이며 P1과 무관
- agent-review packet gold contract의 SOP checklist 1개 불일치도 clean HEAD에서 동일 재현되며 P1 변경과 무관

## 완료 조건

- [x] S1~S5 회귀 테스트 존재
- [x] LLM 결과가 RBAC/Action 계약을 우회하지 못함
- [x] evidence injection fixture 존재
- [x] raw chain-of-thought 저장을 요구하지 않음
- [x] 사용자에게 보여주는 설명과 시스템 권한 판단을 분리

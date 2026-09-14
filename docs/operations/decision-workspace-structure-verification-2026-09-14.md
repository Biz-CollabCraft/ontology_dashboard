# Decision Workspace 구조 검증 — 2026-09-14

이 문서는 `codex/decision-workspace-integration` 브랜치의 Decision Agent 통합을 구조 관점에서 검증한 기록이다. 로컬 코드·테스트·정적 아키텍처 규칙 기준이며, 배포 검증·현장 설비 성과·사람 판단 시간 단축을 의미하지 않는다.

## 현재 기준

- 기준 브랜치: `codex/decision-workspace-integration`
- 원격 반영 커밋: `abc2dce6 fix(decision): align workspace session contract`
- 추가 로컬 수정: operations 계층의 LLM provider import 경계 정리
- 이전 백엔드 통합 커밋: `0a0db640 feat(decision): persist workspace decision sessions`
- 최초 검토 기준 커밋: `8976820b docs: 사건과 관측 분리 증거 및 개선 계획 정리`

## 검증 결론

구조 방향은 유지 가능하다. Decision Agent는 read-only context를 조회하고 추천 후보를 만들며, 실제 mutation은 기존 업무 액션과 사용자 검토 뒤에만 연결된다. 이번 검증에서 남아 있던 문제는 두 가지였다.

1. 프론트가 백엔드 세션 상태 `ready_for_review`를 내부 `completed` 별칭으로 바꿔 소비했다. 이 때문에 계약명이 흔들리고 회귀 테스트가 문제를 가렸다.
2. operations 계층의 LLM planner/interpreter가 `httpx`와 `app.infra.llm.provider`를 직접 import했다. 동작은 가능했지만, 도메인/operations가 infra 구현을 알면 아키텍처 규칙을 위반한다.

두 문제를 수정한 뒤 정적 아키텍처 검증과 관련 테스트를 통과했다.

## 경계별 판정

| 경계 | 판정 | 근거 |
|---|---|---|
| Backend DecisionSession 계약 | Pass | `ready_for_review`, `abstained`, `failed`, `stale` 상태가 서버 계약의 정본이다. |
| Frontend 소비 계약 | Pass | 프론트 fixture, adapter, panel이 `ready_for_review`를 그대로 소비한다. |
| Lost-response/retry 식별 | Pass | 최초 POST에 안정적인 `request_id`를 붙이고, 같은 decision scope에서 같은 값이 생성됨을 테스트한다. |
| Read-only Agent 경계 | Pass | Agent/MCP-style tool은 context 조회만 수행하며 session/proposal은 `mutation_attempted=false`와 `human_approval_required=true`를 강제한다. |
| Policy Guard | Pass | 추천 허용 action은 deterministic Policy Guard 결과 안에 갇힌다. LLM은 allowlist 밖 action을 만들 수 없다. |
| Human-in-the-loop | Pass | 추천 버튼은 바로 mutation하지 않고 사용자 검토 영역을 연다. 실제 업무 요청은 기존 availableActions와 execution binding이 동시에 맞을 때만 열린다. |
| Operations/Infra 의존성 | Pass after fix | planner/interpreter는 `app.common.llm_contract.LLMProvider` 포트만 알고, HTTP/provider 구현은 infra에 남긴다. |
| LangGraph 품질 우위 | Not Proven | 구조적으로 bounded loop, durable checkpoint, 병렬 read는 검증했지만, fixture/gold-set 기준에서 LLM이 deterministic보다 제품 가치가 높다는 증거는 아직 없다. |
| Live backend 성능/KPI | Not Measured | 현재 수치는 fixture/gold-set 또는 로컬 테스트 기준이다. 현장 운영 성과로 표현하지 않는다. |

## 검증 명령과 결과

```text
python3 systems/verify_architecture.py
=> [ARCHITECTURE-CHECK] PASS
```

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_decision_session_service.py \
  tests/test_decision_session_api.py \
  tests/test_decision_durable_runner.py \
  tests/test_decision_session_client.py \
  tests/test_llm_runtime_controls.py \
  tests/test_decision_evidence_guards.py \
  tests/test_operational_decision_api.py \
  tests/test_filesystem_briefing_binding.py \
  tests/test_filesystem_briefing_history.py \
  tests/test_agent_briefing_decision_flow.py \
  tests/test_decision_text_di.py \
  tests/test_decision_text_interpreter.py \
  tests/test_decision_ambiguous_evaluation.py \
  tests/test_backend_strict_architecture.py
=> 126 passed
```

```text
cd systems/frontend && npm run test -- DecisionProposalPanel.test.tsx
=> 33 passed
```

```text
cd systems/frontend && npm run lint
=> TypeScript check passed
```

```text
git diff --check
=> passed
```

프론트 단위 테스트는 일반 샌드박스에서 Vite 임시 파일 생성 권한 때문에 한 번 실패했으며, 동일 명령을 권한 있는 실행으로 재수행해 통과했다. 이는 코드 실패가 아니라 `node_modules/.vite-temp` 쓰기 권한 문제다.

## 구조 효과 검증 해석

이번 구조의 효과는 정확도 우위가 아니라 안전한 연결성에서 확인됐다.

- 같은 판단 범위의 재요청이 같은 DecisionSession으로 수렴할 수 있다.
- 서버 상태명과 화면 소비 계약이 일치한다.
- LLM provider 장애나 malformed output은 planner/interpreter 경계에서 안전 실패로 접히고 deterministic fallback 또는 abstain 경로로 간다.
- LangGraph durable runner는 read-only tool call을 병렬로 예약·저장·재시도하지만, checkpoint가 manufacturing mutation 권한을 갖지 않는다.
- execution binding은 서버가 기존 closed-loop availableActions에서 허용된 action/target만 골라 내려준다.

따라서 현재 PR에서 말할 수 있는 주장은 “Decision Agent를 기존 Operations 계약에 맞춰 안전하게 붙였다”이다. “LLM이 deterministic보다 낫다”, “현장 업무 시간이 줄었다”, “실제 공장 성과가 개선됐다”는 아직 말하면 안 된다.

## 모델 평가 문서 주의

`docs/eval/decision-agent-planner-evaluation-2026-09-14.md`와 일부 과거 ambiguous 평가 문서의 `gpt-4o-mini` 표기는 당시 평가 조건이다. 현재 구조 검증의 모델 조건이나 기본 운영 모델을 뜻하지 않는다. 최신 판단은 `decision-agent-correction-evaluation-2026-09-14.md`의 한계와 동일하게, deterministic 기준 경로를 유지하고 LLM/LangGraph 우위는 Not Proven으로 둔다.

## 남은 한계

1. 구조화된 blocker, 추가 측정 요구, source-owned conflict 신호를 실제 운영 producer가 공급하는 통합은 아직 fixture-backed 검증이다.
2. LangGraph 병렬 read와 durable checkpoint는 구조적으로 검증됐지만, live backend 지연/복구 성능 수치로 표현하지 않는다.
3. MCP transport는 read-only tool contract 관점에서 구현되어 있으나, 외부 MCP 서버 운영 검증이나 배포 관측은 별도다.
4. MONITOR, REQUEST_ADDITIONAL_DIAGNOSIS, REVIEW_PLANNED_MAINTENANCE의 독립 mutation 계약은 구현하지 않았다. 현재는 추천·검토 후보까지만 지원한다.
5. 최종 승인 mutation은 기존 closed-loop API가 다시 검증한다. Decision Agent 출력은 승인 자체가 아니다.

## 다음 판단

이제 남은 작업은 새 기능을 더 붙이는 것이 아니라 PR/브랜치 설명을 이 검증 결과에 맞추는 것이다. 강조점은 다음과 같다.

- backend durable session + frontend contract alignment
- read-only Agent / deterministic Policy Guard / HITL 유지
- fixture-backed 평가와 live 성능 주장의 분리
- LLM/LangGraph 우위 Not Proven 명시

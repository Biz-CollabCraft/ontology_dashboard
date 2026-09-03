---
title: Operational Domain Extension Implementation Report
type: evaluation
status: implementation-candidate-frozen
date: 2026-09-02
candidate_sha: 5633f9143baf6b80b73dd14732c769382d69c1fa
---

# Operational Domain Extension Implementation Report

## Result

운영 도메인 확장의 코드 구현 candidate를
`5633f9143baf6b80b73dd14732c769382d69c1fa`로 고정했다.

- targeted and compatibility regression: **154 passed, 0 failed**
- deterministic synthetic smoke: **passed**
- tested scenarios: ready, part blocked, quality hold
- mutation attempts: **0**
- generated recommendations: **0**
- role truth consistency: **pass**
- relationship source/version/as-of completeness: **pass**
- external API fallback isolation: **pass** (`timeout`, `malformed_response` -> `failed` gap)
- actual MES/CMMS/WMS/QMS connectivity: **not evaluated / not connected**
- B1/B2/B3 and live LLM quality: **not run; final evaluation phase**

첫 전체 회귀는 `APP_ENV=test`에서 model artifact가 없고 heuristic fallback도 명시되지 않아
43건이 환경 정책으로 중단됐다. 저장소가 요구하는
`ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1`을 명시한 재실행에서 실제 계약 불일치
3건을 발견했고, GS-004 SOP expected 및 workflow evaluation scope expectation을 현재 gate와
정합화한 뒤 154건이 모두 통과했다.

## Implemented Vertical Slice

| Area | Implementation evidence | State |
|---|---|---|
| fixed request identity | immutable organization/project/workspace/asset/evidence/as-of contract | Verified |
| versioned context envelope | status, source version/update, retrieved-at, as-of, freshness, refs, limitations | Verified |
| production context | typed order/WIP/alternative capacity fixture and read port | Verified for synthetic source |
| maintenance context | window, action candidate/part requirement, inventory snapshot, skill/technician readiness | Verified for synthetic source |
| quality/delivery context | lot/WIP/order/delivery relationships and quality hold gate | Verified for synthetic source |
| isolated DB read path | scope-bound SQLite snapshot adapter opened with `mode=ro` | Verified |
| relationship resolver | typed RDB/flat-ID paths with gaps/conflicts and source metadata | Verified |
| impact simulation | stop/planned/continue deterministic comparison with no recommendation | Verified |
| bounded ReAct orchestration | allowlisted reads, step budget, retry, structured trajectory, version revalidation | Verified |
| external API fallback | timeout/malformed context failures become failed gaps with reason; no domain data is synthesized | Verified for synthetic failure ports |
| role-specific brief | same truth with role-specific ordering and explicit gaps/limitations | Verified |
| materialization/handoff | temporal guard, version-keyed immutable brief, human-selected non-command package | Verified |
| production external systems | MES/APS/CMMS/WMS/QMS/workforce adapters | Not connected |
| live LLM evaluation | B1/B2/B3, gold quality, concurrency, human sample | Deferred until after implementation |

## Architecture Decision

관계 질문은 현재 indexed relational snapshot과 deterministic resolver로 해결된다. 따라서
Knowledge Graph를 production dependency로 추가하지 않는다. 실행 orchestration도 단일 bounded
agent와 typed ports 안에서 실패·재시도·시간 정합성을 표현할 수 있으므로 LangGraph와
multi-agent 분리는 보류한다.

멀티에이전트나 KG/LangGraph는 실제 service trace에서 계획서의 decision gate 조건이 둘 이상
반복되고, 동일 gold set 비교에서 품질·latency·failure isolation 개선이 입증될 때만 별도
candidate로 평가한다.

## Boundary Confirmation

- Product Result Artifact와 Evidence는 변경하거나 재계산하지 않는다.
- 운영 context는 risk judgment를 덮어쓰지 않는다.
- synthetic source는 `synthetic_demo_context`로 유지한다.
- stale/unavailable/not-connected 데이터는 0 또는 정상값으로 합성하지 않는다.
- action candidate의 부품 관계를 reservation, issue, usage 또는 completed action으로 승격하지 않는다.
- LLM은 향후 structured brief를 설명할 수 있지만 수치 계산·추천·선택·mutation을 소유하지 않는다.
- Decision Handoff Package는 command가 아니며 Backend Closed-loop의 최신 권한·상태·version 검증을
  통과해야 다음 action이 노출된다.

## Evidence

- `tests/eval/results/operational_domain_extension_smoke_2026-09-02.json`
- `scripts/evaluate_operational_decision_support.py`
- `tests/test_operational_context_sqlite.py`
- `tests/test_operational_decision_agent.py`
- `tests/test_operational_relation_resolver.py`
- `tests/test_operational_decision_brief.py`
- `tests/test_operational_decision_materialization.py`

## Next Phase: Final Evaluation

이 구현 보고서는 live 품질 우위를 주장하지 않는다. 다음 단계에서
`2026-09-02-001-agent-workflow-final-evaluation-plan.md`에 따라 candidate SHA를 입력으로 고정하고
다음 순서로 평가한다.

1. 실제 service/DB reliability 반복 평가
2. 동일 provider/model/schema/rubric의 B1/B2/B3 live 비교
3. LLM gold quality 반복 평가
4. concurrency/pressure run
5. 사람 표본 검토
6. stability와 quality를 분리한 최종 통합 리포트

외부 운영 시스템 연결 전 평가는 synthetic/isolated DB 범위를 넘는 actual 운영 효과 증거로
사용하지 않는다.

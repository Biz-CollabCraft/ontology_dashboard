# Decision Agent ambiguous 재평가 — 2026-09-14

현재 LLM planner의 기본 경로 승격 근거는 확보되지 않았다. 먼저 structured schema 결함을 수정했으며, 그 후 동일한 fixture와 고정 채점 기준으로 deterministic과 LLM 구성의 Agent를 비교했다. 아래 수치는 **작성한 합성 시나리오 기준과의 일치율**이다. 현장 전문가가 확정한 정답률이나 live backend 성능이 아니다.

## 조건과 재현성

- Worktree: `/Users/hb/.devspace/worktrees/ontology-dashboard-9a87037d`
- HEAD 및 remote-tracking ref: `c9702e729ae836009b615e563e22cc0e9267d8d6`, `codex/decision-agent-mvp`.
- 최초 상태: tracked 수정 6개, untracked 5개. `git diff --check` 통과. 기존 변경 유지.
- 모델: OpenAI `gpt-4o-mini`, temperature 0. 각 7개 케이스 × 5회, arm별 35회. 직렬 실행, graph import 사전 수행.
- 입력은 합성 packet 및 tool projection fixture다. 실제 read-only facade와 bounded graph를 호출하지만 도메인 저장소, DB, backend HTTP API, MCP transport, 센서 시스템은 호출하지 않는다.
- Policy Guard, 5개 read-only tool, Human approval 경계를 유지했다. 이 작업에서 mutation·프론트·commit·push는 수행하지 않았다.
- 수정 전후 fixture/oracle manifest SHA-256: `21630eab46c19e8535f77c207f0694e06ca2e5d8ba227d3915afbbf39742e56d`. 정답·시나리오 ID·평가 설명은 planner 입력에 넣지 않았다.
- 프롬프트 및 deterministic 추천 규칙은 재평가 중 변경하지 않았다. 출력에 맞춰 정답을 변경하지 않았다.

## 평가 기준

- Tool path: 필수 도구가 `available`로 조회되고, 허용하지 않은 도구나 중복 호출이 없으면 통과. 순서는 독립 조회이므로 허용한다. canonical exact는 별도 기록한다.
- 선택적 도구는 유지보수 시 severity 확인용 condition/inspection, 충돌 시 추가 context 확인 등을 허용한다. 이 호출은 불필요로 단정하지 않으며 전체 호출 수에는 포함한다.
- Missing required tools: 미호출 또는 `available`이 아닌 필수 도구 수. Unnecessary calls: 허용 집합 밖 호출 + 중복 호출.
- Action: 케이스별 사전 정의한 허용 답 집합과 비교. Joint success는 tool path와 action 동시 통과.
- Abstain appropriateness: 보류 필수 케이스의 미보류와 보류 불허 케이스의 보류를 실패로 처리한다. 보류 선택 가능 케이스는 양쪽 허용. Provider/graph 오류를 적절한 abstain으로 인정하지 않는다.
- Planner API calls는 논리적인 provider 생성 호출 수, HTTP requests는 schema fallback까지 포함한 실제 전송 시도 수다. Token은 provider가 보고한 값이며 미측정은 null이다.
- LLM 구성에서도 fallback이 있을 수 있다. 단계별 오류와 실제 proposal/도구 결과를 raw artifact에 남겼다. engine 이름만으로 순수 LLM 성공이라 판정하지 않는다.

## 시나리오별 결과

warning 그룹(A1/A2/A7)과 maintenance 그룹(A3/A4/A5/A6)은 각각 policy facts가 완전히 같다. A6는 maintenance 조회의 해소 불가능한 limitation만으로 보류 가능하고, A7은 condition의 측정 불확실성만으로 추가 진단/보류 가능해 짧은 경로를 허용한다.

| 케이스 | 합성 기준 허용 답 | Deterministic | LLM 구성 |
|---|---|---|---|
| A1_PERSISTENT_RAPID: 지속적 급격 악화, 점검 없음 | REQUEST_INSPECTION | 100.0% | 0.0%; REQUEST_ADDITIONAL_DIAGNOSIS × 4, MONITOR × 1 |
| A2_TRANSIENT_MEASUREMENT: 일시 신호, 추가 측정 필요 | REQUEST_ADDITIONAL_DIAGNOSIS | 0.0% | 100.0%; REQUEST_ADDITIONAL_DIAGNOSIS × 5 |
| A3_RESERVED_UNSUITABLE: 납기 압박·전량 예약·부적합 창 | REVIEW_PLANNED_MAINTENANCE, ABSTAIN | 100.0% | 0.0%; REQUEST_MAINTENANCE × 5 |
| A4_READY_PLANNED: 여유 480분·재고 가용·적합 창 | REVIEW_PLANNED_MAINTENANCE | 100.0% | 0.0%; REQUEST_MAINTENANCE × 5 |
| A5_REPLENISHMENT: 현재 재고 없음·보충 예정 | REVIEW_PLANNED_MAINTENANCE, ABSTAIN | 100.0% | 0.0%; REQUEST_MAINTENANCE × 5 |
| A6_CONFLICT: 해소 불가능한 근거 충돌 | ABSTAIN | 0.0% | 0.0%; REQUEST_MAINTENANCE × 5 |
| A7_UNKNOWN: 보정 미확인·추세 unknown | REQUEST_ADDITIONAL_DIAGNOSIS, ABSTAIN | 0.0% | 100.0%; REQUEST_ADDITIONAL_DIAGNOSIS × 5 |

높은 납기 압박은 설비 위험의 긴급도를 뜻하지 않는다. `fully_reserved`는 전량이 예약되어 가용 재고가 0이라는 뜻이며, 현재 정비를 위한 예약이라는 소유 관계는 없다. 따라서 A3에서 즉시 정비를 단일 정답으로 두지 않았다. A3/A5의 planned review는 현재 실행 가능함을 뜻하지 않는다.

## 집계

| 지표 | Deterministic | LLM 구성 |
|---|---:|---:|
| 도구 경로 허용 기준 일치 | 100.0% | 57.1% |
| Canonical 순서까지 일치 | 71.4% | 0.0% |
| 행동 허용 답 일치 | 57.1% | 28.6% |
| 도구+행동 동시 성공 | 57.1% | 0.0% |
| Abstain 적절성 | 85.7% | 85.7% |
| 평균 불필요 도구 호출 | 0.000 | 1.229 |
| 평균 필수 도구 누락 | 0.000 | 0.000 |
| 평균 총 지연(초) | 0.024 | 6.949 |
| 평균 planner API 지연(초) | 0.000 | 6.924 |
| 평균 planner 생성 호출 | 0.000 | 6.943 |
| 평균 HTTP 전송 시도 | 0.000 | 6.943 |
| 평균 token | 미측정 대상 | 5525.8 |
| fallback을 포함한 run | 0/35 | 35/35 |
| 최종 abstain | 0/35 | 0/35 |

- LLM fallback 오류별 횟수: `{'tool_selection_outside_allowlist': 71}`. 행동 ranking 실패가 포함된 run: 0/35.
- Provider 오류 0, 운영 오류 0. HTTP 상태별 횟수: `{200: 243}`.
- 평균 실제 도구 호출 수: deterministic 2.57, LLM 구성 4.94. 선택적 도구도 포함한다.
- 최종 추천의 policy containment: 70/70. Human approval required: 70/70.

필수 보류 케이스 A6에서 실제 보류는 양쪽 모두 0/5다. 집계 abstain 적절성 85.7%는 보류 불필요 케이스까지 포함하므로 보류 능력의 성공률로 읽으면 안 된다.

## 수정한 결함과 기존 평가 해석

기존 ToolSelection/ActionRanking의 default 필드가 OpenAI strict schema의 required 목록에서 빠졌다. 실제 응답은 HTTP 400 `Missing next_tool`이었다. Provider는 json_object로 재요청했지만 schema가 프롬프트에 없어 `reason` 없는 JSON이 나왔고, Pydantic 검증 실패 후 deterministic fallback이 실행됐다. 기존 평가 스크립트는 provider 예외만 기록하여 이 planner 검증 실패를 잡지 못했다. 기존 단위 테스트도 대문자 도구 값을 사용하여 선택 fallback을 정상 경로처럼 통과시켰다.

- 수정: planner의 다섯 default 선언을 제거해 nullable 필드도 명시 반환하도록 했다. runtime validation과 allowlist는 강화된 채 유지된다.
- 회귀: strict schema의 모든 property가 required인지, 실제 LLM 도구 선택이 deterministic 경로와 구분되는지 검사했다. 기존 FakeProvider의 도구 값도 소문자 계약으로 수정했다.
- 수정 전 본 평가: LLM 구성 35/35가 fallback, 행동 일치 20/35. 이 결과를 LLM 품질로 해석하지 않는다.
- 이전 3-scenario 보고서의 provider 오류 0은 planner 오류 0의 증거가 아니다. 과거 결과가 실제 LLM 판단이었다는 주장에는 추가 검증이 필요하다.

## 한계와 다음 판단

1. 현재 기본 경로 승격은 보류한다. 이 fixture 기준에서도 근거를 효율적으로 선택하고 충돌에 보류하는 능력이 충분히 확인되지 않았다. schema 문제를 고쳐도 의미 판단 문제는 남는다.
2. `REQUEST_MAINTENANCE`는 실행이나 즉시 정지를 뜻하지 않는 요청이다. `REVIEW_PLANNED_MAINTENANCE`와의 우선순위 및 긴급도 의미를 현장 담당자와 먼저 확정해야 한다. 현재 gold는 작성자 기준이며 맹검 전문가 정답이 아니다. A1의 추가 진단도 상황에 따라 가능한 답이므로 이 점수만으로 현장 열등성을 확정할 수 없다.
3. 일부 tool 필드가 unknown이어도 payload는 available이다. inspection 결과의 존재를 completeness=complete로 보는 기존 projection과 condition 신호의 자유 문자열은 품질/출처 확인을 대체하지 않는다. 이번 fixture는 도메인 모델 전체 생산 경로의 검증 자료가 아니다.
4. 다음 구현 후보는 도구가 남지 않았을 때 종료, 동적 tool allowlist를 schema에도 반영, fallback 단계의 production session 노출이다. 이후 action 의미·근거 충족 조건을 확정하고 미사용 holdout에서 재평가한다. 이번 결과에 맞춘 prompt 튜닝은 하지 않았다.
5. 사람이 판단하는 시간, 공장 성과, 비용 절감, live backend latency는 측정하지 않았다. 5회 반복은 안정성 관찰이며 35개의 독립 사건 표본이 아니다. MONITOR와 긴급 정비의 양성 정답 coverage도 부족하다.
6. 기존 dependencies는 LLM_PROVIDER 설정에 따라 planner를 활성화한다. 본 평가가 기본 경로 승격을 승인하는 것은 아니며, 이 wiring은 기존 사용자 변경으로 보존했다.

## 검증과 변경 파일

- `132 passed, 7 skipped` (8.59초). Decision 전체, context ports/contract/evolution, operational decision API/materialization, strict architecture 포함. PostgreSQL fixture를 사용하는 항목은 로컬 DB 테스트 조건 미충족으로 skipped; 실DB 검증으로 표현하지 않는다.
- `git diff --check` 및 프론트 변경 없음 확인. staging/commit/push 없음.
- 기존 11개 미커밋 파일 유지. 이번에 추가 수정한 기존 파일: `systems/backend/app/operations/decision_llm_planner.py`, `tests/test_decision_llm_planner.py`, 기존 평가 보고서에 해석 주석.
- 새 파일: `scripts/evaluate_decision_agent_ambiguous.py`, `tests/test_decision_ambiguous_evaluation.py`, `tests/test_decision_planner_wire.py`, `tests/test_decision_context_validation.py`, 본 보고서, raw artifact 2개.

## 산출물과 재실행

- [수정 후 raw 결과](decision-agent-ambiguous-final-2026-09-14.json)
- [수정 전 fallback 진단 결과](decision-agent-ambiguous-before-schema-fix-2026-09-14.json)
- [평가 스크립트](../../scripts/evaluate_decision_agent_ambiguous.py)

Raw JSON 두 파일은 기존 `.gitignore`의 `docs/eval/**/*.json` 정책으로 Git 추적에서 제외되며, 현재 worktree에 로컬 보존했다. ignore 정책이나 index는 변경하지 않았다.

```sh
PYTHONPATH=systems/backend:scripts PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_decision_agent_ambiguous.py --iterations 5 --workers 1 --env-file /Users/hb/Documents/final/ontology-dashboard/.env --output /private/tmp/decision-agent-ambiguous-rerun.json
```

키 값은 출력하지 않는다. deterministic만 실행하려면 `--arm deterministic`을 쓰고 `--env-file`을 생략한다. 원본 manifest는 각 raw artifact에 포함되어 있다.

## 후속 수정

[수정 및 재평가 보고서](decision-agent-correction-evaluation-2026-09-14.md)에 이전 입력·정답 고정 비교와 의미를 명시한 v2 결과를 따로 기록했다. 이 문서와 raw는 수정 전 결과로 보존한다.

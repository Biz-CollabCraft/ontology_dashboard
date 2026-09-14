# Decision Agent 기준 선택: Luna + v4

2026-09-14 사용자가 평가 결과의 한계를 남기고 Luna를 사용하도록 승인했다. 현재 기준은 **gpt-5.6-luna + quoted-text-evidence-interpreter-v4**, deterministic planner, read-only tool, deterministic Policy Guard, Human-in-the-loop다. 추가 점수 개선용 튜닝은 중단한다.

## 선택 근거와 남기는 한계

[v4 회귀 비교](../eval/decision-gold-v1.1/prompt-v4-evaluation-2026-09-14.md)에서 Luna는 제안 라벨 기준 정보 누락 60/60, 세 행동 관련 플래그 60/60, LangGraph 행동 제약 60/60, 불필요 보류 0/36이었다. 전체 6항목은 47/60이고 의미 분류는 v3 저장 응답 재채점의 56/60에서 48/60으로 낮아졌다. 선택적 측정의 의미 분류 및 unclear/not_stated 경계는 불안정하다.

조건부 측정의 현재 조건 미확인과 모호함+필수 측정 복합 지시의 표현 한계는 남는다. 미정 4건을 자동 승인하거나 없애지 않았다. 원문 20개를 3회 반복한 합성 개발/회귀 비교이며 사람 검수/현장 정확도 인증이 아니다. v3는 기존 응답 재채점으로 비교했고 동시 재호출 대조는 아니다. Luna 배치 평균 6.280초는 4o-mini 3.560초보다 느렸으며 단일 세션의 지연으로 해석하지 않는다.

## 적용한 설정과 코드

대상 worktree: `/Users/hb/.devspace/worktrees/ontology-dashboard-9a87037d`.

| 항목 | 기준 |
|---|---|
| LLM_PROVIDER | openai-compatible |
| LLM_MODEL | gpt-5.6-luna |
| LLM_REASONING_EFFORT | low |
| LLM_MAX_COMPLETION_TOKENS | 4096 |
| temperature | 요청에서 생략 |
| LLM_TIMEOUT_SECONDS | 90 (이 로컬 Decision Agent 설정) |
| DECISION_AGENT_PLANNER | deterministic |
| text interpreter | quoted-text-evidence-interpreter-v4 |

새 `.env`는 이 worktree에만 생성했다. Git 제외, 파일 권한 0600이며 기존 승인된 설정의 API credential만 필요한 값으로 전달하고 DB 설정은 복사하지 않았다. 다른 checkout의 `.env`나 실행 서버는 변경하지 않았다. `.env.example`에는 비밀값 없이 기준 모델과 low/4096/deterministic 설정을 남겼다. 예제의 공통 timeout은 기존 20초이며 이번 로컬 프로필은 평가와 같은 90초다.

기본 OpenAI-compatible provider가 optional LLM_REASONING_EFFORT와 LLM_MAX_COMPLETION_TOKENS를 실제 요청에 전달하도록 연결했다. 미설정이면 기존 동작을 유지하고, 유효하지 않은 설정은 요청 전에 실패한다. schema 재시도에도 설정이 유지된다. gpt-5 계열 temperature 생략은 기존 로직을 사용한다.

모델 ID와 요청 설정을 명시적으로 선택한 것이며 제공사 내부 가중치/배포 버전의 불변성을 보증하는 것은 아니다. 과거 실행은 응답 모델, 원문, 프롬프트, 소스 해시와 함께 보존한다.

## 확인한 증거

- provider 요청 옵션·schema 재시도·기본 동작 호환성과 Decision Agent 경계: **86 passed**.
- 평가 전용 ModelProvider가 아닌 실제 configured_provider()로 새 worktree `.env`를 로딩했다. 기본 DecisionSession service 경로에 합성 packet/ports를 주입해 메모 1건을 처리했다.
- 실제 HTTP 응답 모델 `gpt-5.6-luna`, reasoning_effort=low, max_completion_tokens=4096, temperature 없음, json_schema, HTTP 200. API 요청 1회, 1,073 tokens, finish_reason=stop.
- 추천은 REQUEST_ADDITIONAL_DIAGNOSIS. 메모리 내 세션 재조회 내용이 일치했고, 사람 승인 필요=true, mutation_attempted=false였다.
- [정제된 실제 요청·응답 확인 기록](../eval/decision-gold-v1.1/luna-v4-runtime-proof.json). credential은 기록하지 않았다. JSON은 로컬 평가 증거이며 git의 기존 제외 규칙을 유지했다.

이번 실행은 합성 도구 데이터 + 실제 provider + 실제 application service의 확인이다. HTTP API 서버, DB 영속화, 프론트 화면 검증은 아니다. 점검 당시 해당 Decision Agent worktree에서 떠 있는 서버는 없었고 다른 worktree의 서버는 재시작하지 않았다. 따라서 로컬 설정 적용과 위 실행 확인까지 완료했으며, 기존 실행 서버/배포 환경에 반영됐다고 주장하지 않는다.

원본 v1/v1.1 데이터, 과거 점수, 검수 pending 상태는 유지한다. 최신 승인 대상은 이 모델/프롬프트의 사용 기준 선택이며 사람의 도메인 정답 검수 승인과 다르다. 이번 작업에서 commit/push는 하지 않았다.

## 후속 HTTP 통합 검증

[2026-09-14 HTTP·PostgreSQL 검증](../eval/decision-gold-v1.1/http-postgres-check-2026-09-14.md)에서 실제 Luna 연결과 인증·재조회·읽기 전용 경계는 확인했다. 다만 두 도구의 중복 문구가 예산 제한을 초과해 오류 보류되는 결함을 재현했으므로 정상 추천 경로는 아직 통합 검증 통과가 아니다. 모델 선택 한계와 별개의 수집기 수정 사항이다.

## 입력 예산 결함 수정 완료

[중복 문구 예산 수정·HTTP 재검증](../eval/decision-gold-v1.1/http-budget-fix-2026-09-14.md)에서 고유 원문과 출처 수집 한도를 분리했다. 관련 테스트 90개가 통과했고 동일 HTTP 요청 두 번 모두 예산 오류 없이 REQUEST_INSPECTION을 반환했다. 실제 Luna 호출·세션 재조회·도메인 DB 무변경도 확인했다. 과거 실패 기록은 수정 전 증거로 보존한다.

## 구조 효과 비교

[구조 비교 결과](../eval/decision-structure-evaluation-2026-09-14.md)에서 순차 구현과 LangGraph의 동등한 재시도·결과를 확인했다. 조기 보류는 도구 조회를 줄였지만 단계별 해석은 모델 호출을 늘렸고, 긍정적 조기 제안은 상반된 후속 근거를 놓칠 수 있었다. LangGraph만의 성능 우위로 주장하지 않는다.

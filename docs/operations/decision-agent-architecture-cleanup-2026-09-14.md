# Decision Agent 의존 경계 정리

2026-09-14, 기존 미커밋 작업을 유지한 상태에서 정리했다. 프론트 변경, 도메인 mutation, commit/push, 외부 LLM 호출은 없다.

## 변경과 이유

- `app/common/llm_contract.py`에 LLMProvider와 ProviderUnavailable을 배치했다. 판단 코드는 통신 구현이 아닌 공통 계약만 참조한다. 기존 infra provider 경로에서도 두 이름을 재노출하여 다른 소비자의 호환성을 유지했다.
- OpenAICompatibleProvider가 httpx의 timeout/HTTP 오류를 ProviderUnavailable로 변환한다. planner와 문구 해석기는 httpx import 없이 기존 실패/보류 경로를 사용한다. 400 응답의 structured-schema fallback 동작은 유지했다.
- `app/diagnosis/contracts.py::selected_complete_file_tick`이 선택된 시나리오 또는 현재 관측 조회를 담당한다. 라우터와 브리핑은 같은 공개 계약을 사용한다. artifact 생성도 기존 공개 계약을 직접 사용한다.
- HTTP 503 변환은 라우터에 남긴다. 공개 조회 계약은 CompleteFileTickNotFound를 전달하며, 브리핑의 기존 archive fallback에서 처리할 수 있다.

## 검증

- 전체 `systems.verify_architecture`: **PASS**, 기존 위반 **6 → 0**. 검사 규칙이나 allowlist를 완화하지 않았다.
- 관련 회귀 검사 **96 passed**: 공개 조회·시나리오 선택, 통신 어댑터 timeout/503, schema fallback, planner, 문구 해석, DI, durable runner, 세션 API, 아키텍처 검사기.
- 실제 OpenAI 어댑터에 httpx timeout을 주입하여 공통 오류 → TextInterpretationError, 빈 cache 유지까지 확인했다. 외부 네트워크를 사용하지 않았다.
- `git diff --check`: PASS.

## 당시 별도 확인된 기존 실패

`tests/test_filesystem_briefing_history.py`의 7개 검사는 여전히 실패한다. 작업 디렉터리 파일을 되돌리지 않고, HEAD 버전 filesystem_briefing.py를 별도 Python 프로세스 메모리에 로딩해 같은 검사를 수행했을 때도 7개가 실패했다.

- 성공 경로 3개: 테스트 서비스 대역(SimpleNamespace)에 현재 packet 구현이 사용하는 `_closed_loop_context_for_fixture` 등이 없다.
- 오류 경로 4개: 테스트는 HTTPException을 기대하지만 application 함수는 이미 BriefingHistoryUnavailable을 발생시킨다.

첫 오류를 넘어선 후의 전체 이력 조립 정확성은 이 테스트들로 검증되지 않았다. 이번 경계 정리에서 이력 조립이나 기대 결과를 함께 변경하지 않았다. 따라서 전체 테스트 통과라고 표현하지 않는다. 다음 점검은 서비스 대역/예외 계층 계약을 맞추고 실제 이력 조립을 검증하는 것이다.

## 이전 평가 증거

이전 durable 평가의 등록 파일과 코드 hash는 당시 결과를 보존한다. 이번 변경으로 일부 소스 hash가 달라졌으므로 과거 등록을 현재 코드와 동일하다고 주장하지 않는다. 병렬 속도나 Luna 의미 해석 성능을 이번 변경 이후 새로 측정한 것은 아니다.


## 후속: 활성 경로 확인과 이력 연결 수정

`operations.router._selected_agent_review_packet` 및 `dependencies.refresh_stored_agent_briefing`이 FILE 사건에 이 함수를 실제 사용한다. 따라서 미사용 레거시로 제외할 수 없었다.

- FILE packet이 이미 조회한 정확한 event lineage 대신 fixture 이력을 다시 읽던 부분을 수정했다.
- 조회한 workflow_as_of를 packet에 보존해 센서 관측 뒤에 기록된 점검·생산 협의를 현재 이력으로 평가한다.
- 승인 대기 문구 검사는 work-order 사실이 아니라 이미 scope 검증된 별도 production_coordination 사실을 사용하도록 연결했다.
- 테스트 서비스 대역은 운영 컨텍스트 read port를 갖추도록 보강했고, 실제 생산 협의 activity_type 및 현행 판단 stage에 맞췄다. application 예외와 API 503 매핑은 각각 검증한다.
- 기존 prompt-version 기대값 v3.7은 이미 적용된 v3.8에 맞췄다. 프롬프트 본문이나 모델은 이번 수정에서 바꾸지 않았다.

당시의 7건 실패 기록은 원래 상태를 설명한다. 후속 수정의 최종 테스트 결과는 [실행 마무리 기록](decision-agent-followthrough-2026-09-14.md)에 기재한다.

# 예측 결과 → 브리핑 생성·검증 → 워크플로우 → 화면 통합 검증

최신 통합 상태: [최종 통합 보고](final-demo-ai-briefing-integration.md).

2026-09-08 · 작업 브랜치 `codex/demo-ai-briefing-placement`

## 범위

기존 화면 replay는 저장된 근거 패키지에서 출발하여 예측 실행, 실제 워크플로우와 저장·조회 경로를 건너뛰었다. 이번 검사는 별도 임시 SQLite DB를 만들고 아래 실제 구현을 연결했다.

1. GS-001~GS-008 관측 입력 → 실제 `HeuristicPredictor.predict` 실행
2. `build_product_result_artifact` → 실제 Result/Evidence 구성
3. `asset_detail_view_model` → `agent_review_packet` → 선택 근거·시간 범위·decision flow 구성
4. 실제 `AgentReviewSummaryProvider` → 생성 응답 병합, 내용 검사, 재검사 피드백, 실패 차단
5. 실제 `AgentReviewSummaryWorkflow` → materialization → SQLite 요약/워크플로우 기록 저장
6. 실제 인증 후 `/api/objects/{asset}/agent-review-summary` 및 `/detail-view` 조회
7. 기존 `FinalBriefingDemo` → `EngineerFactoryStandalone` → `NaturalBriefing` 표시

외부 LLM 전송 포트만 통제된 테스트 응답으로 대체했다. 예측·패키지·검사기·워크플로우·저장·조회 API는 테스트 더블로 바꾸지 않았다. 예측은 규칙 기반 로컬 예측이며 운영 학습 모델이나 실제 외부 LLM 품질을 검증한 결과가 아니다.

브라우저는 원래 8328 요청 주소를 격리 테스트 서버 8338로 전달했다. 테스트 서버는 실제 제품 API를 인증된 TestClient로 호출하고, 반환된 ViewModel과 저장 조회 응답을 demo의 입력 형식으로 연결한다. 운영 API의 공개 네트워크 배포나 직접 로그인 UI까지 검증한 것으로 간주하지 않는다. 검사 중 사용자의 기존 시연 화면/DB를 덮어쓰지 않았다.

## 확인한 연결

- 예측에 실제 전달된 입력 해시가 현재 선택 입력과 같음.
- 예측 확률 = Result 확률 = ViewModel 확률.
- 설비·사건·기준 시각이 패키지, ViewModel, 저장 요약, 워크플로우 기록에서 일치.
- 선택 근거와 citation catalog가 패키지의 허용 근거 범위를 벗어나지 않음.
- 요약 ID·summary key·workflow run ID가 실제 DB 행과 조회 API에서 일치.
- 생성 전 GET 202이며 GET은 LLM 전송 포트를 호출하지 않음.
- 최초 워크플로우에서 8개 생성, 반복 실행에서 8개 재사용. 읽기/재사용은 추가 LLM 호출 없음.
- 잘못된 외부 응답은 실제 제공자 재검사 2회씩 거쳐 fallback으로 저장되고 자연어 화면에서 차단.
- 실패 뒤 유효 응답으로 회복 가능.
- 예측 입력의 토크·시각 변경 시 기존 요약 GET 202로 차단. 해당 1개만 새 key로 생성하며 예측값·화면 기준 시각이 변경 입력으로 갱신.
- 브리핑 작업 전후 업무 활동 기록이 같음. 작업요청·승인·정비 실행을 수행하지 않음.
- 실제 브라우저의 설비 ID·관측값·기준 시각과 조회 ViewModel 값 일치.
- 실제 브라우저의 문장 내용과 DB에서 조회된 해당 역할 문장 일치.

## 발견한 결함과 수정

DB에 `fallback`으로 저장된 결과를 상위 워크플로우가 실패로 집계하지 않아 `completed` / `consumer_ready: completed`로 보고했다.

`systems/backend/app/operations/agent_review_summary_workflow.py`에서 `fallback`도 실패 집계에 포함하도록 수정했다. 이제 전체 검증 실패 시 `terminal_status: partial`, `consumer_ready: partial`이며 화면에는 자연어 응답이 제공되지 않는다. 입력/승인 상태를 수정하는 변경은 아니다.

## 결과

- 새 전체 연결 통합 테스트 3개: 통과. 정상 테스트 1개 내부에서 8개 입력을 실제 전 경로로 대조.
- 기존 기여 계약 테스트 2개: 통과.
- 기존 워크플로우 테스트 3개: 통과.
- 실제 브라우저 정상 경로: **8개 입력 × 3개 관점 = 24/24 통과**.
- 실제 제공자 재검사→fallback 저장→조회→화면 차단: 통과.
- 브라우저 실행 오류: 0.
- `git diff --check`: 통과.

40/40은 코드 계약 검사, 16/16은 브라우저 오류 주입 안정성 검사다. 이번 24/24는 별도로 실제 로컬 예측·워크플로우·임시 DB·조회 API를 연결한 화면 검사다. 서로 다른 검사를 더해 하나의 정확도/안정성 비율로 제시하지 않는다.

## 파일과 재실행

- `tests/briefing_chain_support.py`: 외부 LLM 전송만 대체하는 격리 통합 구성
- `tests/test_agent_prediction_to_screen_chain.py`: 예측·근거·제공자·워크플로우·저장·조회 API·무변경·갱신 검사
- `scripts/serve_briefing_chain_test.py`: 실제 연결 결과를 기존 demo에 전달하는 테스트 전용 서버
- `scripts/verify_prediction_to_screen_chain.mjs`: 실제 표시 문장·값·시각 대조 및 실패 차단 검사
- `/private/tmp/prediction-to-screen-chain-results.json`: 아래 브라우저 검증 명령으로 생성되는 로컬 실행 근거. 원시 JSON은 Git에 포함하지 않으며 [근거 목록](../eval/final-demo-evidence-20260908/README.md)의 해시는 당시 보관본 기준이다.

서버 테스트:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=systems/backend:tests:. python3 -m pytest -p no:cacheprovider tests/test_agent_prediction_to_screen_chain.py tests/test_agent_briefing_contribution_metrics.py -q
```

기존 Vite 3318 실행 상태에서 테스트용 서버를 별도 터미널로 시작한다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/serve_briefing_chain_test.py
```

```sh
node scripts/verify_prediction_to_screen_chain.mjs
```

테스트 서버 종료 시 임시 DB는 제거된다. 실제 외부 LLM, 운영 모델 실행, live DB를 잇는 전체 경로, 배포 환경 및 다중 사용자 부하는 별도 검증 범위다. 팀 DB 읽기 전용 조회 결과와 최신 전체 검증은 [최종 통합 보고](final-demo-ai-briefing-integration.md)에 구분했다.

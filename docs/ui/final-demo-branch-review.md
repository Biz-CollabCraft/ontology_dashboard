# 최종 시연 브랜치 흡수 검토

2026-09-08 · base `origin/demo` = `ae6141ef98cb4ee6ec6ea405b798f97b6fd9b1e1` (원격 갱신 후 확인)

대상은 `codex/demo-ai-briefing-placement`, 소스는 `codex/pr167-ai-briefing-optimization-plan`의 HEAD `8a5c50d8`와 로컬 미커밋 변경이다. 소스와 다른 작업 트리는 수정하지 않았다. 타깃의 기존 58개 변경은 통합 전에 별도 보관했다. 커밋 개수 대신 실제 생성·검증·조회·표시 경로와 파일 내용을 대조했다.

## 흡수와 제외

- 근거 패키지, 선택 문맥, 3역할 계약, 내용·시간 검사, 생성 정책, materialization, 조회 경로, 관련 테스트를 흡수했다.
- 추가 검토에서 평가 도구 2개, 역할/도구 궤적 평가 4개, 화면 준비 테스트와 schema 안내를 동기화했다. 과거 2역할 gold를 3역할 성과로 소급 변경하지 않는다.
- 타깃의 v3.4 마지막 판단 키워드 강조 프롬프트, 자연어 표시·스트리밍·상대 날짜, 기존 화면 구조를 유지했다.
- 통합 테스트에서 확인한 fallback 집계 오류를 타깃에서 수정했다. 제공자 미설정 경로의 CLI/평가 기대 상태도 partial로 갱신했다.
- 기존 Operations 회귀의 역할 불일치는 실제 엔지니어 로그인 → 작업요청 → 매니저 로그인 → 판단 기록 순서로 수정했다. 제품 권한을 완화하지 않았다.
- 과거 v3/v4 응답, 개인 발표자료, 개인 절대 경로를 포함한 일회성 모델 실행 스크립트, 별도 모델 비교 실험과 관련 없는 UI 변경은 흡수하지 않았다. 이를 운영 consumer의 누락으로 간주하지 않는다.
- `tests/briefing_demo_replay_support.py`와 두 로컬 시연 서버는 테스트 전용이다. 운영 라우터에 데모 API를 등록하지 않는다.

## 핵심 파일 대조

| 소스 경로 | 최종 상태 |
|---|---|
| `contracts/schemas/agent-review-packet.schema.json` | 동일하게 흡수 |
| `contracts/schemas/agent-review-summary-v1.1.schema.json` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_briefing_context.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_briefing_review.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_context_tool_pipeline.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_review_packet.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_review_summary.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_review_summary_generation_policy.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_review_summary_materialization.py` | 동일하게 흡수 |
| `systems/backend/app/operations/agent_review_summary_provider.py` | 최종 화면 통합 수정 유지 |
| `systems/backend/app/operations/agent_review_summary_workflow.py` | 최종 화면 통합 수정 유지 |
| `systems/backend/app/operations/context_providers.py` | 동일하게 흡수 |
| `systems/backend/app/operations/router.py` | 동일하게 흡수 |
| `systems/backend/app/operations/service.py` | 동일하게 흡수 |
| `systems/frontend/src/standalone/aiBrief.js` | 동일하게 흡수 |
| `systems/frontend/src/standalone/aiBrief.test.js` | 동일하게 흡수 |
| `systems/frontend/src/standalone/briefFormat.js` | 최종 화면 통합 수정 유지 |
| `systems/frontend/src/standalone/briefFormat.test.js` | 최종 화면 통합 수정 유지 |
| `systems/frontend/src/standalone/main.js` | 동일하게 흡수 |
| `systems/frontend/src/standalone/presentation.js` | 최종 화면 통합 수정 유지 |
| `systems/frontend/src/standalone/presentation.test.js` | 최종 화면 통합 수정 유지 |

## 검토 결론

**Verified:** 로컬 예측 → Result/Evidence → 근거 패키지 → 생성 응답 검사 → 워크플로우/임시 DB → 실제 조회 API → 화면의 설비·사건·시각·문장 일치. GET 비생성, 정확한 key 재사용, 변경 입력 차단/갱신, 검증 실패 표시 차단. 업무 활동 기록 무변경.

**Partially Verified:** 실제 팀 DB 연결과 저장 출처는 읽기 전용으로 확인했다. 합성 문맥·미래 관측·저장 AI 요약 부재를 확인했으며 모델 실행이나 브리핑의 live 통합을 입증하지 않는다.

**추가 확인:** 최신 프롬프트의 실제 LLM 호출 2개는 각 1회 재생성 후 최종 통과했다. [호출 점검](final-demo-live-llm-verification.md).

**Not Proven:** 운영 모델 artifact 재실행, live 전체 경로, 배포, 다중 사용자 부하, 현장 사용자 효용과 운영 KPI.

**Architecture Pass (검토 범위):** raw producer/hidden truth를 UI에 전달하지 않고 Result/Evidence와 ViewModel을 소비한다. AI 편집은 설명 문장에 한정한다. 점검·승인·정비 실행의 권한과 소유권을 변경하지 않는다.

커밋은 서버 구현·계약/회귀, 기존 화면 통합·전체 연결 검증, 문서·평가 근거의 세 묶음으로 구성한다. 최신 결과와 재실행은 [통합 보고](final-demo-ai-briefing-integration.md)를 따른다.

> 과거 실험 기록: 작성 당시 코드·프롬프트·입력·채점 조건의 결과입니다. 현재 demo의 검증 결과나 모델 선정으로 해석하지 않습니다. 개인 경로는 당시 산출물 위치이며 새 체크아웃에 포함되지 않을 수 있습니다. [흡수 범위와 재실행](evaluation-experiments-absorption-20260908.md)

# live-fix 선별 흡수 — 2026-09-07

## 기준과 범위

PR #167 `7d6d79f6`와 계획 커밋 `8a5c50d8`를 기준으로 `codex/pm-gold-scorer-live-fix`의 미커밋 변경을 선별 이관했다. 원본 브랜치 전체를 병합하지 않았다.

- 비보류 사건에 생산 맥락이 있으면 위험 등급과 무관하게 조회한다. 데이터 품질 보류의 전용 경로는 유지한다.
- 두 프롬프트 builder에 confidence_label을 전달하며 예시 수량 대신 원천 수량과 0을 보존하도록 지시한다.
- 손실 수량 앞뒤 표현을 검증해 잘못된 수치가 기존 fallback 경로로 거부되도록 한다.
- #167의 데모 가정 표시·짧은 문장 지침을 유지하고 프롬프트 버전을 v1.9-production-grounding으로 갱신한다.
- #167에서 제거된 생산관리자 고정 문구 강제 검증은 복원하지 않았다. 125건/25건 회귀는 현재 공통 수량 검증을 통해 검사한다.
- 기존 평가 요약과 발표 제작·확장성 검토 문서는 과거 기록으로 보존한다. 원본 평가 JSON, 스크립트, 발표 HTML은 제품 소스에 추가하지 않는다.

## 검증

선별 변경을 적용한 독립 작업 폴더에서 관련 테스트 **169 passed, 5 skipped**, `git diff --check` 통과. 새 수량 오류·0 보존·보류 상태·캐시 버전 분리 회귀를 포함한다.

```sh
APP_ENV=test ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 PYTHONPATH=systems/backend python -m pytest tests/test_agent_summary_production_grounding.py tests/test_agent_review_summary_contract.py tests/eval/test_agent_workflow_baseline_simulation.py tests/eval/test_agent_summary_llm_eval.py tests/eval/test_agent_tool_pipeline_eval.py tests/eval/test_agent_decision_support_briefing_eval.py tests/test_operations.py tests/test_agent_review_summary_watcher_cli.py tests/test_materialization_lease_fencing.py -q --tb=short
```

이 결과는 fixture 기반 검증이다. live provider 품질·사용자 유용성·배포 결과는 측정하지 않았다. 동시에 진행 중인 3역할 계약 변경과 통합한 뒤에는 새 계약 기준으로 다시 검증해야 한다.

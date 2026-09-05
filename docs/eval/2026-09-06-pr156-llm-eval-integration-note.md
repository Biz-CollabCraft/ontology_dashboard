# PR156 LLM-Eval Branch Integration Note

작성일: 2026-09-06

## 결론

`codex/pr156-llm-eval`은 현재 발표/평가 정본 브랜치에 **현재 Operations 구조 기준으로 흡수된 상태**로 본다. 원 브랜치의 의미 있는 조각은 "LLM 평가 전후로 Closed-loop feedback이 Agent Review Packet과 후속 평가 맥락에 반영되는지 확인한 API/DB 테스트"다.

## 흡수 기준

원 브랜치에는 예전 `app.mvp` 경로 변경이 남아 있었지만, 현재 체크아웃의 실제 소비 경로는 `app.operations`다. 따라서 예전 경로를 그대로 cherry-pick하지 않고, 현재 경로에서 같은 보증이 존재하는지 확인했다.

확인한 현재 기준:

- `systems/backend/app/operations/agent_review_packet.py`
  - Closed-loop history record가 record type별 우선 ID를 사용한다.
  - maintenance event는 `maintenance_event_id`를 우선 보존한다.
- `systems/backend/app/operations/service.py`
  - maintenance lineage에서 `runtime_status`, `runtime_state`를 Closed-loop context로 전달한다.
- `tests/test_operations.py`
  - inspection request부터 maintenance replay, Agent Review Summary 재생성까지 API-only feedback flow를 검증한다.
- `tests/test_predictive_maintenance_postgresql.py`
  - post-maintenance Product Result promotion 테스트가 현재 파일에 존재한다.

## 현재 확인 결과

```text
PYTHONPATH=systems/backend ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 .venv/bin/python -m pytest tests/test_operations.py -k closed_loop_feedback_flow_reaches_replay -q

1 passed, 66 deselected
```

```text
PYTHONPATH=systems/backend ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 .venv/bin/python -m pytest tests/test_predictive_maintenance_postgresql.py -k closed_loop_feedback_promotes_post_maintenance_product_result -q

1 skipped, 9 deselected
```

## 해석

- 확인됨: SQLite/API 수준에서 Closed-loop feedback이 replay 요청과 Agent Review context까지 이어진다.
- 확인됨: 현재 Operations 경로에는 원 브랜치의 핵심 record-id/runtime-status 보강이 반영되어 있다.
- 부분 확인: PostgreSQL promotion 테스트는 현재 파일에 존재하지만, 이번 로컬 실행에서는 PostgreSQL fixture 미가용으로 skip됐다.
- 미확인: 이 근거만으로 브라우저 UI, 실제 generator 재실행, 외부 MES/CMMS/WMS/QMS 연동까지 검증됐다고 말하지 않는다.

## 발표 반영 기준

발표에서는 이 내용을 주 수치로 앞세우지 않는다. 필요한 경우 Q&A에서 다음 정도로만 사용한다.

"Closed-loop feedback은 별도 API 테스트로 점검 요청부터 정비 후 재평가 요청까지 이어지는지 확인했습니다. 다만 이 근거는 UI 자동화나 외부 운영 시스템 연동 검증이 아니라, 현재 로컬 API/DB 경로 기준입니다."

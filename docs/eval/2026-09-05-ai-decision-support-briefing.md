# AI 판단보조 검증 브리핑

작성일: 2026-09-05

## 한 줄 요약

현재 검증은 **로컬 synthetic fixture 기준으로 AI 판단보조 요약이 필수 판단 항목을 빠뜨리거나 운영 성과처럼 과장하지 않는지 확인한 것**입니다. 실제 MES/CMMS/WMS/QMS 연동, 판단 리드타임 단축, 오판 감소, 생산 손실 감소는 측정하지 않았습니다.

## 검증 범위

- 대상: Agent Review Packet, deterministic Agent Review Summary, read-only tool pipeline
- 데이터 범위: 로컬 synthetic fixture / service-generated packet
- 판단 상황: critical, warning, data-quality hold, normal 4종
- 재사용한 기존 평가: Agent Review Summary 계약, Agent Review Packet gold manifest, tool pipeline 장애 격리/trajectory 평가
- 새로 추가한 평가: `tests/eval/test_agent_decision_support_briefing_eval.py`

## 확인된 항목

| 검증 항목 | 결과 | 설명 |
| --- | --- | --- |
| 판단 항목 누락 테스트 | 확인됨 | 위험 상태, 주요 점검 부위, 생산 영향, 예상 손실 문맥, 점검 승인 여부, 데이터 부족 시 보류 표현을 fixture 기준으로 확인했습니다. |
| 역할별 판단 가능성 체크 | 확인됨 | 현장 작업자는 점검 위치와 부품 후보를 보고, 공정 관리자는 생산 영향, 손실 가능성, 승인 여부, 셀 작업 순서를 보도록 분리되어 있습니다. |
| 우선순위 일관성 테스트 | 확인됨 | critical, warning, data-quality hold, normal 상황에 따라 먼저 조회하는 문맥이 달라집니다. data-quality hold는 `data_quality.lookup`만 사용합니다. |
| 보류/제한 표현 테스트 | 확인됨 | 데이터 부족은 위험도/우선순위/점검대상을 확정하지 않고, 실제 MES 실적 연결 전까지 손실 물량은 계획 기준 추정으로 표시됩니다. |
| 장애 격리 테스트 | 부분 확인 | 현 체크아웃에는 11개 reliability 시나리오 파일은 없고, 기존 tool-pipeline 9개 평가를 재사용했습니다. 새로 과한 장애 시나리오는 만들지 않았습니다. |

## 실행 결과

```text
PYTHONPATH=systems/backend ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 .venv/bin/python -m pytest tests/test_agent_review_summary_contract.py tests/test_agent_review_packet_eval_set.py tests/eval/test_agent_tool_pipeline_eval.py tests/eval/test_agent_decision_support_briefing_eval.py -q

54 passed in 3.71s
```

결과 JSON: `tests/eval/results/agent_decision_support_briefing_eval_2026-09-05.json`

## 발표용 쉬운 말

- gold score: 정답표 기준 필수 판단 항목 반영 점수
- ontology: 흩어진 제조 정보를 판단 가능한 관계 지도
- Agent Review Summary: 사람 검토를 돕는 읽기 전용 판단 요약
- data quality hold: 센서나 이력 근거가 부족해서 판단을 보류한 상태
- deterministic fallback: LLM 없이 규칙으로 만든 안전한 기본 요약

## 말할 수 있는 문장

- "AI 판단보조 요약이 위험 상태, 점검 위치, 생산 영향, 예상 손실 문맥, 승인 여부, 데이터 부족 시 보류 표현을 로컬 fixture 기준으로 빠뜨리지 않는지 테스트했습니다."
- "critical, warning, data-quality hold, normal 상황별로 먼저 확인하는 정보가 달라지는지 확인했습니다."
- "data-quality hold에서는 위험도와 우선순위를 정상값처럼 채우지 않고 판단 보류로 남기는 것을 확인했습니다."

## 말하면 안 되는 문장

- "실제 MES/CMMS/WMS/QMS와 연동되어 운영 판단을 자동화했다."
- "실제 판단 리드타임이 줄었다."
- "오판율이나 생산 손실이 감소했다."
- "사람이 실제로 더 유용하다고 평가했다."
- "LLM 품질이 live provider 기준으로 검증됐다."

## 남은 한계

- human usefulness: not_measured
- live provider quality: not_measured
- operational KPI impact: not_measured
- external system integration: not_measured
- production watcher reliability: not_measured

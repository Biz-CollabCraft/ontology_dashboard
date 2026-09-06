# Final Presentation Evidence Index

작성일: 2026-09-05

## 정본

- 발표 정본 대본: `docs/plans/ai-workflow/2026-09-03-005-ai-solution-engineer-5min-presentation-script.md`
- 보조 제작 명세: `docs/plans/ai-workflow/2026-09-03-003-ai-solution-engineer-final-presentation-production-spec.md`
- 보조 긴 대본: `docs/plans/ai-workflow/2026-09-03-004-ai-solution-engineer-final-presentation-script.md`

발표에서 실제로 읽을 문장은 5분 대본을 기준으로 한다. 긴 대본과 제작 명세는 슬라이드 제작, Q&A, 근거 확인용 보조 문서로만 사용한다.

## 최신 기준

최신 발표 근거는 2026-09-05 기준의 PM validator 보강 이후 산출물을 우선한다.

| 층 | 최신 근거 | 발표 사용 |
| --- | --- | --- |
| 판단보조 fixture 회귀 | `docs/eval/2026-09-05-ai-decision-support-briefing.md` | 필수 판단 항목, 역할별 분리, 보류 표현 확인 |
| 120-run 표본 해석 | `docs/eval/2026-09-05-live-120-sample-rationale.md` | 8개 gold case x 15회 반복의 타당성 및 발표 문장 |
| PR156 LLM-eval branch 흡수 | `docs/eval/2026-09-06-pr156-llm-eval-integration-note.md` | Closed-loop feedback이 Agent Review context로 이어지는지 현재 Operations 기준 확인 |
| live LLM 품질 | `tests/eval/results/agent_summary_llm_eval_live_120_20260905_pm_fix.json` | 120/120 accepted, fallback 0, gold 1.0 |
| 최신 workflow 비교 | `tests/eval/results/agent_workflow_baseline_live_20260905_pm_validator_fix.json` | B3 gold 1.0, PM 1.0, B1 대비 token 감소 |
| holdout/paraphrase | `tests/eval/results/agent_summary_llm_eval_live_holdout_paraphrase_20260905_pm_overfit_check.json` | 24/24 accepted, fallback 0, gold 1.0 |
| human review | `docs/eval/2026-09-05-agent-summary-human-review-holdout-pm-overfit-check.md` | not_measured로만 표시 |

## 발표용 수치

| 항목 | 값 | 근거 | 측정 해석 |
| --- | ---: | --- | --- |
| 판단보조 fixture 테스트 | 54 passed | `docs/eval/2026-09-05-ai-decision-support-briefing.md` | 현재 체크아웃에서 재실행 확인 |
| live LLM quality sample | 120 rows | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | 8 gold cases x 15 iterations |
| live LLM accepted | 120/120 | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | accepted structured summary 기준 |
| live LLM fallback | 0 | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | 120-run quality gate 기준 |
| live LLM gold | 1.0 | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | fixture gold scorer 기준 |
| live LLM p50 | 3,906 ms | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | provider call + local validation end-to-end |
| live LLM p95 | 5,788 ms | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | provider call + local validation end-to-end |
| live LLM total tokens | 215,835 | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | provider usage metadata가 아니라 payload/output 기반 추정 |
| live LLM average tokens | 1,798.6 | `agent_summary_llm_eval_live_120_20260905_pm_fix.json` | provider usage metadata가 아니라 payload/output 기반 추정 |
| provider usage smoke | 1/1 accepted, 6,550 tokens | `docs/eval/2026-09-05-provider-usage-smoke.md` | provider usage metadata를 `provider_reported`로 기록 확인 |
| latest workflow sample | 72 rows | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | B1/B2/B3 x 8 cases x 3 iterations |
| latest workflow B1 gold mean | 0.386995 | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | 일부 invalid/unscored row caveat 포함 |
| latest workflow B2 gold mean | 0.796875 | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | 일부 invalid/unscored row caveat 포함 |
| latest workflow B3 gold mean | 1.0 | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | PM validator 이후 B3 회복 기준 |
| latest workflow B3 token delta vs B1 | -27,918 | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | payload/output 기반 추정 total token |
| latest workflow B3 token delta vs B2 | -43,273 | `agent_workflow_baseline_live_20260905_pm_validator_fix.json` | payload/output 기반 추정 total token |
| holdout/paraphrase sample | 24 rows | `agent_summary_llm_eval_live_holdout_paraphrase_20260905_pm_overfit_check.json` | 8 changed cases x 3 iterations |
| holdout/paraphrase accepted | 24/24 | `agent_summary_llm_eval_live_holdout_paraphrase_20260905_pm_overfit_check.json` | overfit 보조 확인, human review는 미완료 |

## 측정 경계

- 응답시간은 live LLM 120-run artifact의 `latency_ms` 기준이며, provider 호출과 로컬 검증 시간을 포함한 end-to-end 측정이다.
- 최신 workflow 비교 artifact는 B1/B2/B3별 p50/p95 latency를 제공하지 않는다. 따라서 발표에서 A/B/C별 응답시간 차이를 수치로 말하지 않는다.
- 기존 2026-09-05 120-run과 workflow artifact의 token은 provider usage metadata가 아니라 serialized payload와 output size 기반 추정값이다.
- 현재 체크아웃의 live LLM harness는 provider가 usage metadata를 반환하면 `usage_measurement=provider_reported`로 기록하고, provider usage가 없거나 provider 호출이 실패하면 기존 추정값으로 fallback한다.
- 실제 provider usage smoke는 GS-002 1건 기준으로 `provider_reported_rows=1`, `estimated_rows=0`을 확인했다. 이 smoke는 provider usage 수집 기능 확인이며, 기존 120-run token 수치를 대체하지 않는다.
- cost는 가격 설정이 없어 금액으로 확정하지 않는다. `cost.status`는 `not_configured` 또는 `not_measured`로 둔다.
- 72-row workflow 비교는 B1/B2 invalid row와 B3 fallback/reuse caveat가 있으므로, clean model-quality claim은 120-run live quality artifact를 기준으로 말한다.
- PR156 LLM-eval branch의 남은 가치는 Closed-loop feedback 보조 근거다. 발표 본문 수치가 아니라 Q&A용 보조 설명으로만 사용한다.

## 발표에서 말할 수 있는 문장

- "5분 발표의 정본은 5분 압축 대본 하나로 두고, 긴 대본과 제작 명세는 보조 자료로만 사용했습니다."
- "현재 체크아웃에서 판단보조 fixture 테스트는 54개가 통과했습니다."
- "별도 live LLM 120-run에서는 120/120 accepted, fallback 0, gold 1.0을 기록했습니다."
- "이 120회는 8개 gold 시나리오를 각각 15번 반복한 release-gate이며, 운영 전체 통계가 아니라 반복 안정성 확인으로 해석했습니다."
- "응답시간은 p50 약 3.9초, p95 약 5.8초로 측정했고, 이 값은 provider 호출과 로컬 검증 시간을 합친 end-to-end 기준입니다."
- "토큰은 provider 원본 사용량이 아니라 입력·출력 크기 기반 추정이며, 120-run 총 215,835 tokens, 평균 1,798.6 tokens로 기록했습니다."
- "이후 보강한 평가 harness는 provider가 usage를 주면 provider_reported로 기록하도록 바꿨고, 1건 smoke에서 실제 수집을 확인했습니다. 다만 기존 120-run 발표 숫자는 재실행 전까지 추정값으로 표시합니다."
- "최신 72-row workflow 비교에서는 B3가 B1보다 추정 token을 27,918 줄였지만, 이 비교는 invalid row와 fallback/reuse caveat를 함께 봐야 합니다."

## 발표에서 말하지 않을 문장

- "B3가 모든 상황에서 A/B보다 빠르다."
- "기존 120-run artifact에서 provider가 청구한 실제 token/cost를 측정했다."
- "실제 운영 비용이 줄었다."
- "실제 MES/CMMS/WMS/QMS 연동 효과가 검증됐다."
- "human review가 완료됐다."

## 정리 방법

기존 평가 문서는 삭제하지 않는다. 대신 이 index를 최신 발표 기준의 입구로 두고, 오래된 문서는 다음처럼 참조한다.

| 문서 | 상태 | 사용법 |
| --- | --- | --- |
| `2026-09-02-operational-domain-extension-implementation-report.md` | 이전 구현 후보 | 구현 범위와 synthetic 검증 배경 |
| `2026-09-03-agent-workflow-final-evaluation-report-960f4713.md` | 이전 candidate | latency/token/cost 항목 구조 참고 |
| `2026-09-03-selection-live-llm-model-comparison-brief.md` | 이전 selection candidate | 120-run claim 형식 참고 |
| `2026-09-04-pr161-selection-live-llm-evaluation-report.md` | PR 161/163 통합 후보 | live DB/watcher claim은 해당 후보로만 제한 |
| `2026-09-05-b3-gold-surface-match-analysis.md` | 최신 PM scorer/generation 보강 | B3 caveat와 holdout 상태 확인 |
| `2026-09-05-ai-decision-support-briefing.md` | 현재 체크아웃 fixture 검증 | 발표용 쉬운 말과 금지 주장 기준 |

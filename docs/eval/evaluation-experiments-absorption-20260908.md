# 로컬 AI 브리핑 평가 실험 흡수

2026-09-08 · 대상 `codex/demo-evaluation-experiments`, 기준 `origin/demo` b03dd4cc. 원본 `codex/pr167-ai-briefing-optimization-plan` HEAD 8a5c50d8 및 로컬 미커밋 자료. 원본 작업 트리는 수정하지 않았다.

## 범위

| 묶음 | 내용 | 처리 |
|---|---|---|
| 재사용 평가 9개 | 실행기 6개, 비교 회귀 2개, 3역할 gold 1개 | 현재 코드와 연결, 오프라인 검증 |
| 과거 gold 29개 | v3/v4/v4.1/v4.2 정답·검수·입력·등록 파일 | 기존 버전과 내용 보존 |
| 평가 보고서 9개 | 모델 비교, 생성 정책, Luna 검수, 기여 계약, 판단 유용성 | 역사적 조건 안내를 추가해 보존 |
| 일회성 평가 소스 10개 | owner/shared/expanded/Luna 문장 검수 | `.py.txt`로 보관, 자동 실행하지 않음 |

합계 57개 원본이며 [원본 대응표](../../experiments/agent-briefing/source-manifest.json)에 출처 해시가 있다. 재실행 가능 여부와 원시 증거의 존재 여부는 다르다. 과거 보고서가 참조하는 `/private/tmp`, `outputs/` 파일 전체는 Git에 포함하지 않았다.

화면 파일, `ReliabilityWorkspacePreview`, 제품 서버 구현, 발표 문서는 변경하지 않았다. 이미 demo에 흡수된 평가 도구와 회귀는 덮어쓰지 않았다.

## 실행기

| 파일 | 역할 | 실행 경계 |
|---|---|---|
| `compare_agent_review_summary_models.py` | 동일 입력 교차 비교, 원시 후보/최종 제공 분리, 품질·사용량·지연·등록 조건 확인 | 기본 offline. 실제 호출은 명시적 live 모드·입력 식별 필요 |
| `run_pr167_registered_comparison.py` | 당시 3모델 비교 등록·재개 | prepare는 오프라인. 실제 호출은 `--live` 필요 |
| `run_pr167_extended_comparison.py` | 모델별 reasoning 설정을 고정한 비교 | prepare는 오프라인. 모델 조회·배치 실행도 `--live` 필요 |
| `run_luna_120_stability.py` | 등록한 입력의 120회 반복 일정·결과 집계 | 입력과 선택적 env 파일을 명시. `--prepare`만으로 생성하지 않음 |
| `replay_pr167_measured_latency.py` | 측정한 입력별 지연을 시간축 정책에 대입 | 시뮬레이션과 비용 투영이며 운영 효과 측정 아님 |
| `audit_pr167_database_readiness.py` | 지정 DB 읽기 전용 출처·시각·저장 상태 점검 | env 파일 필요, 쓰기·LLM 호출 없음. 이번 흡수 검증에서는 실행하지 않음 |

고정 비교 실행기의 모델 목록·단가·설정은 2026-09-07 실험 조건이다. 최신 모델 추천이나 현재 가격표로 쓰지 않는다. 새로운 선택 실험에는 범용 비교기의 명시적 모델·가격·사전 등록 입력을 사용하고 조건을 새로 등록해야 한다. 외부 호출은 별도 실행 범위다.

흡수 과정에서 개인 저장소/.env 기본 경로를 제거했다. 확장 비교의 `frozen()`이 공유 gold 설정을 남기던 부분은 종료 시 원래 설정과 캐시를 복원하도록 수정해 평가 순서 간 오염을 막았다.

## 이번 검증

- 평가 테스트 전체 `tests/eval`: **120 passed**. 이전 평가 회귀와 새 비교 검사를 함께 실행했다.
- 범용 오프라인 비교: 입력 8개 × 테스트 모델 이름 2개 = **16행 생성**. 실제 모델 성과가 아니다.
- 확장 비교의 `--prepare`: 입력·설정 해시와 등록 파일 생성 확인. 외부 호출 없음.
- Luna 120회 실행기의 `--prepare`: 현재 보관된 8개 데모 패킷으로 120개 일정 등록만 확인. 120회 모델 생성을 수행하지 않았다.
- 생성 정책 평가: 로컬 시뮬레이션 실행 확인. 운영 준비율·실제 호출 감소·비용은 `not_measured`로 유지한다.
- 새 실제 LLM 호출, DB 접속, 화면 수정, 운영 설정 변경 없음.

```sh
APP_ENV=test ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=systems/backend:tests:. python3 -m pytest -p no:cacheprovider tests/eval -q
```

오프라인 비교 예시:

```sh
PYTHONPATH=systems/backend:. python3 scripts/compare_agent_review_summary_models.py --mode offline --model offline-a --model offline-b --gold-answers tests/fixtures/agent_review_packets/gold_answers_three_role_v2.json --output /tmp/briefing-offline-comparison.json
```

새 출력 디렉터리에서 실험 등록만 수행:

```sh
PYTHONPATH=systems/backend:. python3 scripts/run_pr167_extended_comparison.py --prepare --output-dir /tmp/briefing-new-registration
PYTHONPATH=systems/backend:. python3 scripts/run_luna_120_stability.py --prepare --inputs tests/fixtures/final_briefing_demo/cases.json --output-dir /tmp/briefing-new-luna-registration
PYTHONPATH=systems/backend:. python3 scripts/evaluate_agent_review_generation_policy.py --output /tmp/briefing-policy-simulation.json
```

## 보존한 보고서

- [역사적 에이전트 검수](2026-09-06-agent-judge-controlled-historical-report.md)
- [기존 수정 선별 흡수](2026-09-07-live-fix-selective-absorption.md)
- [Luna 제품 검수](2026-09-07-luna-product-validation-decision.md)
- [생성 정책과 당시 종합 평가](2026-09-07-pr167-briefing-final-evaluation.md)
- [GPT-5 mini와 Luna 비교](2026-09-07-pr167-gpt5-mini-luna-comparison.md)
- [SOP·점검 기록 보강](2026-09-07-sop-owner-record-briefing-enrichment.md)
- [판단 유용성 예비 검증](2026-09-08-agent-briefing-usefulness-prelim.md)
- [기여별 검증 매트릭스](2026-09-08-contribution-metric-verification.md)
- [문장 단위 프롬프트 검수](2026-09-08-reader-line-briefing-prompt-evidence.md)

과거 v3.2/v3.3 통과율과 현재 v3.4 호출 점검은 별도 평가다. 20.8%→80.8%와 에이전트 선호 70.8%를 이번 오프라인 실행으로 갱신하지 않는다. 실제 현장 사용자 효과·운영 KPI·배포 검증으로 확대 해석하지 않는다.

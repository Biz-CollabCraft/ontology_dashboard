> 과거 실험 기록: 작성 당시 코드·프롬프트·입력·채점 조건의 결과입니다. 현재 demo의 검증 결과나 모델 선정으로 해석하지 않습니다. 개인 경로는 당시 산출물 위치이며 새 체크아웃에 포함되지 않을 수 있습니다. [흡수 범위와 재실행](evaluation-experiments-absorption-20260908.md)

# AI Briefing Contribution Metric Verification

2026-09-08 기준. 이 문서는 발표에 사용할 기여별 수치 검증 범위를 분리한다. 모든 수치는 로컬 fixture, 로컬 화면 렌더링, 승인된 Luna smoke 기준이며 실제 운영 DB 저장, 배포 환경, 운영 사용자 효과는 포함하지 않는다.

## 기여별 검증 매트릭스

| 기여 | 측정 지표 | 현재 수치 | 검증 상태 | 증거 |
|---|---:|---:|---|---|
| Gold v5 정답셋 보강 | gold case 수 | 9 cases | Verified | `tests/fixtures/agent_review_packets/natural_briefing_v5/gold-v5.json` |
| Gold v5 정답셋 보강 | 역할별 정답 문장 수 | 27 role briefings | Verified | 9 cases × 3 roles |
| Gold v5 정답셋 보강 | 형식/금칙어/기본-승인 변형 분리 검사 | 6 gold tests | Verified | `tests/test_agent_briefing_gold_v5.py` |
| 관계 흐름 결정론화 | 반복 안정성 | 45 deterministic builds | Verified | 9 cases × 5 iterations |
| 관계 흐름 결정론화 | flow fingerprint 안정성 | 45/45 stable | Verified | `outputs/luna-bullets/stability-evidence/stability-report.json` |
| 관계 흐름 결정론화 | payload fingerprint 안정성 | 45/45 stable | Verified | `outputs/luna-bullets/stability-evidence/stability-report.json` |
| 관계 흐름 결정론화 | 입력 mutation 방지 | 45/45 unchanged | Verified | `outputs/luna-bullets/stability-evidence/stability-report.json` |
| 근거 선택/관계 매핑 | current evidence selection 회귀 | 5 tests | Verified | `tests/test_agent_briefing_evidence_selection_flow.py` |
| 근거 선택/관계 매핑 | selected/rejected evidence 전달 회귀 | 3 tests | Verified | `tests/test_agent_selected_evidence_delivery.py` |
| 근거 선택/관계 매핑 | 운영 evidence selection 회귀 | 4 tests | Verified | `tests/test_operational_evidence_selection.py` |
| 경계 검증 | 승인/보류/after-basis/다른 자산 경계 | 4 test defs with parametrized checks | Verified | `tests/test_agent_briefing_luna_boundaries.py` |
| 표현 안전성 | 내부 표현·근거 토큰·잘못된 손실 수량 차단 | 3 test defs with parametrized checks | Verified | `tests/test_agent_briefing_bullet_format.py` |
| 표시 계층 개선 | 날짜·단위·근거 접기 화면 포맷터 | 3 frontend tests | Verified | `systems/frontend/src/standalone/briefFormat.test.js` |
| 표시 계층 개선 | 화면 렌더링 체크 | 7/7 checks passed | Verified | `outputs/luna-bullets/luna-v31-time-unit-guard/rendered-visible.json` |
| SOP 기준 초과 → 점검 판단 | 내부 제품 코드 제거 및 기준 초과의 판단 연결 | 1 gold regression added | Verified | `tests/test_agent_briefing_gold_v5.py` |
| Luna 모델 smoke | 승인 기록 케이스 | 1/1 accepted | Verified smoke | `outputs/luna-bullets/luna-v31-time-unit-guard/gpt-5.6-luna-3.json` |
| Luna 모델 smoke | 데이터 품질 보류 케이스 | 1/1 accepted | Verified smoke | `outputs/luna-bullets/luna-v31-time-unit-guard/gpt-5.6-luna-8.json` |
| Luna 모델 smoke | 전체 smoke | 2/2 accepted | Verified smoke | `outputs/luna-bullets/luna-v31-time-unit-guard/rendered-visible.json` |
| 120-run 안정성 | 120 generation pass rate | v3.2 77/120, 64.17% → v3.3 94/120, 78.33% | Verified live-provider smoke-scale | `outputs/luna-bullets/luna-120-stability-v33/aggregate.json` |
| 120-run 안정성 | v3.3 실패 유형별 count | provider reject 23, unsupported operation candidate 3, raw unit 0, internal/code 0 | Verified live-provider smoke-scale | `outputs/luna-bullets/luna-120-stability-v33/aggregate.json` |
| 120-run 안정성 | v3.3 최저 통과 케이스 | 부품 가용·조달 근거 미제공 7/15, 46.67% | Verified live-provider smoke-scale | `outputs/luna-bullets/luna-120-stability-v33/aggregate.json` |

## 현재 발표 가능 수치

아래 문장은 현재 증거로 방어 가능하다.

- 정답셋은 9개 케이스와 27개 역할별 브리핑으로 보강했다.
- 관계 흐름과 prompt payload는 9개 케이스를 5회씩 반복한 45회 결정론 검증에서 모두 동일하게 유지됐다.
- 관련 backend/gold/selection/flow 회귀는 46개 통과했다.
- 화면 포맷터는 날짜, 단위, 근거 접기 기준 3개 테스트를 통과했다.
- Luna는 승인 기록과 데이터 품질 보류 대표 케이스 2건에서 accepted 2/2, validation error 0건을 기록했다.

## 아직 말하면 안 되는 수치

아래 문장은 아직 근거가 부족하다.

- Luna가 120회 안정성 평가에서 안정적으로 통과했다.
- Luna가 전체 케이스에서 일관되게 가장 우수하다.
- 실제 운영 DB 또는 배포 환경에서 동일 품질이 확인됐다.
- 실제 다운타임, 생산 손실, 업무 시간 절감 효과가 측정됐다.

## 120-run 평가 설계

발표 전에 모델 안정성을 수치로 넣으려면 다음 평가를 추가해야 한다.

| 항목 | 제안 |
|---|---|
| 대상 모델 | `gpt-5.6-luna` |
| 범위 | 9 gold cases |
| 반복 | 총 120 generations |
| 분배 | 9케이스 균등 반복 후 나머지는 승인/보류 경계 케이스에 배정 |
| 필수 지표 | accepted count, validation error count, 내부 필드명 노출 count, 날짜·단위 렌더링 실패 count, 승인/시작/완료 hallucination count |
| 산출물 | raw outputs, rendered-visible outputs, aggregate report, 대표 실패문 |
| 발표 문장 조건 | pass rate와 실패 유형 count가 산출된 뒤에만 사용 |

## 발표용 표현

현재 증거만 쓰면 다음 표현이 안전하다.

> AI 브리핑 개선은 정답셋, 관계 흐름, 근거 선택, 화면 표시를 분리해 검증했다. 9개 케이스·27개 역할 브리핑 기준을 만들고, 45회 결정론 반복 검증에서 flow와 payload가 모두 안정적으로 유지되는 것을 확인했다. SOP 기준 초과는 기준표 설명이 아니라 점검 위치와 다음 판단으로 연결하도록 보강했다. Luna는 승인 기록과 데이터 품질 보류 대표 케이스 2건에서 validation error 없이 통과했으며, 120회 안정성 평가는 추가 측정 대상으로 남겼다.

120-run 후 실제 발표 문장:

> Luna 안정성 평가는 120회 생성 기준 v3.2 77회 통과에서 v3.3 94회 통과로 개선됐고, pass rate는 64.17%에서 78.33%로 14.16%p 상승했다. 보완 후 raw 단위와 내부 코드 노출은 0건으로 줄었지만, provider review reject와 일부 운영 실행 표현 후보가 남아 readiness gap과 착수 조건 문장 구조를 추가 보완 대상으로 남겼다.


## Luna 120-run 안정성 평가 결과

사용자 명시 승인 후 `gpt-5.6-luna`를 대상으로 120회 live generation 안정성 평가를 실행했다. 범위는 8개 owner-expanded 로컬 fixture 입력을 15회씩 반복한 것이다. 실제 팀 DB 저장, 운영 배포, 운영 사용자 효과는 포함하지 않는다.

결과:

- completed runs: 120
- accepted runs: 77
- pass rate: 64.17%
- failed runs: 43
- total model-call duration: aggregate report 기준

케이스별 통과율:

| 입력 | 케이스 | 통과 | 통과율 |
|---:|---|---:|---:|
| 1 | 점검 결과 등록 | 10/15 | 66.67% |
| 2 | 작업요청 등록 · 승인 기록 없음 | 7/15 | 46.67% |
| 3 | 작업요청 승인 기록 있음 | 12/15 | 80.00% |
| 4 | 다른 설비의 원본 관측 | 15/15 | 100.00% |
| 5 | 기준 이후 승인 기록 | 8/15 | 53.33% |
| 6 | 다른 설비·이벤트의 승인 기록 | 3/15 | 20.00% |
| 7 | 부품 가용·조달 근거 미제공 | 11/15 | 73.33% |
| 8 | 데이터 품질 보류 | 11/15 | 73.33% |

실패 유형은 중복 집계 기준으로 다음과 같다. 한 출력이 raw 단위와 지시형 경계 위반을 동시에 가질 수 있으므로 합계는 실패 run 수와 다를 수 있다.

| 실패 유형 | 건수 | 의미 |
|---|---:|---|
| directive_prose_claims | 22 | AI가 `승인 검토/정비 일정/라인 순서를 결정하세요`처럼 권한 소유에 가까운 지시형 문장을 생성 |
| internal_field_or_code_visible | 10 | `제품 유형 M` 등 내부 코드성 표현이 본문에 노출 |
| raw_unit_visible | 9 | `N·m·min` 같은 원자료 단위가 한국어 표시 규칙을 통과하지 못함 |
| provider_review ValueError | 7 | provider content review 단계에서 재작성 후에도 거부 |

해석:

- Luna는 대표 smoke 2건에서는 통과했지만, 120-run 기준으로는 아직 안정적이라고 말하기 어렵다.
- 가장 강한 보완 근거는 `권한 경계가 있는 다음 행동 문장`이다. 브리핑은 “결정하세요”보다 “결정에 필요한 조건은 무엇인지”를 말해야 한다.
- 단위와 내부 코드 표현은 화면 포맷터가 일부 보정할 수 있지만, 모델 원문 품질 기준에서는 추가 prompt/repair가 필요하다.
- 발표에는 “120-run 안정성 평가를 통해 pass rate 64.17%와 주요 실패 유형을 계량화했고, 다음 보완 범위를 좁혔다”라고 말하는 것이 안전하다.

증거 파일:

- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/aggregate.md`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/aggregate.json`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v32b/runs/`


## Luna 120-run v3.3 보완 후 재평가

120-run v3.2에서 실패가 `권한 경계가 있는 지시형 문장`, `내부 코드성 표현`, `raw 단위 노출`에 집중되는 것을 확인한 뒤, provider 재작성 루프를 보강했다. 1차 출력에서 raw 단위, 내부 제품 코드/필드명, contract의 directive 오류가 발견되면 같은 근거로 한 번 더 재작성하도록 했다. 또한 `결정하세요`뿐 아니라 `결정해야 합니다`, `판단해야 합니다`처럼 AI가 승인·착수·정비 일정·라인 순서를 소유하는 표현도 경계로 추가했다.

재평가 결과:

- prompt version: `agent-review-summary-prompt-v3.3-review-repair-boundaries`
- completed runs: 120
- valid model runs: 120
- transport error runs: 0
- accepted runs: 94
- pass rate: 78.33%
- 보완 전 대비: 64.17% → 78.33%, +14.16%p

케이스별 통과율:

| 입력 | 케이스 | v3.3 통과 | 통과율 |
|---:|---|---:|---:|
| 1 | 점검 결과 등록 | 12/15 | 80.00% |
| 2 | 작업요청 등록 · 승인 기록 없음 | 12/15 | 80.00% |
| 3 | 작업요청 승인 기록 있음 | 9/15 | 60.00% |
| 4 | 다른 설비의 원본 관측 | 14/15 | 93.33% |
| 5 | 기준 이후 승인 기록 | 13/15 | 86.67% |
| 6 | 다른 설비·이벤트의 승인 기록 | 13/15 | 86.67% |
| 7 | 부품 가용·조달 근거 미제공 | 7/15 | 46.67% |
| 8 | 데이터 품질 보류 | 14/15 | 93.33% |

실패 유형:

| 실패 유형 | 건수 | 해석 |
|---|---:|---|
| provider review reject | 23 | 2차 재작성 후에도 provider content review를 통과하지 못해 화면 노출 전 차단 |
| unsupported operation candidate | 3 | 착수·완료 같은 운영 실행 표현 후보가 남아 차단 |
| raw unit visible | 0 | v3.2의 9건에서 0건으로 감소 |
| internal field/code visible | 0 | v3.2의 10건에서 0건으로 감소 |

해석:

- 보완 후 단위와 내부 코드 노출은 120-run에서 0건으로 줄었다.
- `다른 설비·이벤트의 승인 기록` 케이스는 3/15에서 13/15로 개선되어, 제외 기록을 현재 승인 상태로 섞는 문제가 크게 줄었다.
- 남은 병목은 부품 가용·조달 근거가 부족한 케이스와 승인된 작업요청의 착수 조건 케이스다. 이 영역은 프롬프트보다 `readiness_gap` 구조를 더 세분화하거나, 승인/착수/일정 문장을 템플릿화하는 쪽이 다음 보완 후보이다.

증거 파일:

- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/aggregate.md`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/aggregate.json`
- `/Users/hb/Documents/Codex/2026-09-07/ontology-dashboard-devspace-hb-workspaceid-ws/outputs/luna-bullets/luna-120-stability-v33/runs/`

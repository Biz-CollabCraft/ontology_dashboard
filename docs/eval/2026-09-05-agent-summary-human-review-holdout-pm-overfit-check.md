# Agent Summary Human Review Sample

## Review identity

- Campaign run ID: `live-holdout-paraphrase-20260905-pm-overfit-check`
- Candidate SHA: `local-pm-overfit-check`
- Provider/model: `openai-compatible / gpt-4o-mini`
- Source artifact: `tests/eval/results/agent_summary_llm_eval_live_holdout_paraphrase_20260905_pm_overfit_check.json`
- Eval set: `agent-review-packet-holdout-v1`
- Selection rule: each case's output at `iteration=1`
- Review status: **not_measured**
- Worksheet generated: `2026-09-05`
- Reviewer/date: `________________ / ________________`

This review is an independent human gate. Automated gold, usefulness, and Korean-quality scores are triage signals only.

## Decision rule

For every case, record:

1. **Usable without edit**: yes only if the copy can be shown to its intended role unchanged.
2. **Incorrect required fact**: quote the incorrect fact, or write `none`.
3. **Awkward Korean**: quote the phrase, or write `none`.
4. **Role mismatch**: describe information or action assigned to the wrong role, or write `none`.
5. **PM boundary check**: confirm production impact, lost units, approval review, and data-quality-hold uncertainty.
6. **Heuristic agreement**: whether automated gold/usefulness/Korean pass agrees with human judgment.

The human gate passes only when all rows are completed and the reviewer explicitly records the disposition.

## Selected outputs

### HGS-001 · CNC-H01-L02-01

- Title: AI 검토 요약 · Holdout 1구역 · 2셀 · CNC 가공기 1 · warning
- Summary: Holdout 1구역 · 2셀 · CNC 가공기 1는 현재 warning 상태이며 예측 위험도는 73.1%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 1구역 · 2셀 · CNC 가공기 1: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: Holdout 1구역 · 2셀 · CNC 가공기 1 위험 감지 건은 현재 생산 영향이 높은 수준으로 분류되며, 360분 기준 약 124건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 토크이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-002 · CNC-H02-L03-02

- Title: AI 검토 요약 · Holdout 2구역 · 3셀 · CNC 가공기 2 · attention
- Summary: Holdout 2구역 · 3셀 · CNC 가공기 2는 현재 attention 상태이며 예측 위험도는 41.7%입니다. 열 방산 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 2구역 · 3셀 · CNC 가공기 2: attention 알림. 스핀들 냉각 라인 및 가공부 열 배출 경로, 주축 모터, 커플링, 동력 전달 하우징에서 열 방산 계통, 동력 전달 계통을 확인합니다. 공정·공기 온도 차이, 토크, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 냉각 팬 유닛, 주축 구동 커플링 키트입니다.
- Process manager: Holdout 2구역 · 3셀 · CNC 가공기 2 위험 감지 건은 현재 생산 영향이 낮은 수준으로 분류되며, 35분 기준 약 7건 손실 가능성이 있습니다. 모델 근거는 공정·공기 온도 차이, 토크, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 24일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-003 · CNC-H03-L04-03

- Title: AI 검토 요약 · Holdout 3구역 · 4셀 · CNC 가공기 3 · critical
- Summary: Holdout 3구역 · 4셀 · CNC 가공기 3는 현재 critical 상태이며 예측 위험도는 93.4%입니다. 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 3구역 · 4셀 · CNC 가공기 3: critical 알림. 주축 모터, 커플링, 동력 전달 하우징에서 동력 전달 계통을 확인합니다. 기계 동력, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름에는 점검 요청이 요청됨 상태로 접수되어 있습니다. 참고 부품 후보는 주축 구동 커플링 키트입니다.
- Process manager: Holdout 3구역 · 4셀 · CNC 가공기 3 위험 감지 건은 현재 생산 영향이 높은 수준으로 분류되며, 410분 기준 약 88건 손실 가능성이 있습니다. 모델 근거는 기계 동력, 과부하 지표, 토크이고 작업 처리 흐름에는 점검 요청이 요청됨 상태로 접수되어 있습니다. 최근 유사 이력은 7월 22일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-004 · CNC-H04-L01-01

- Title: AI 검토 요약 · Holdout 4구역 · 1셀 · CNC 가공기 1 · normal
- Summary: Holdout 4구역 · 1셀 · CNC 가공기 1는 현재 normal 상태이며 예측 위험도는 9.4%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 4구역 · 1셀 · CNC 가공기 1: normal 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: Holdout 4구역 · 1셀 · CNC 가공기 1 위험 감지 건은 현재 생산 영향이 없음으로 분류되며, 20분 기준 약 0건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-005 · CNC-H05-L05-02

- Title: AI 검토 요약 · Holdout 5구역 · 5셀 · CNC 가공기 2 · warning
- Summary: Holdout 5구역 · 5셀 · CNC 가공기 2는 현재 warning 상태이며 예측 위험도는 58.8%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 5구역 · 5셀 · CNC 가공기 2: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 토크, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: Holdout 5구역 · 5셀 · CNC 가공기 2 위험 감지 건은 현재 생산 영향이 중간 수준으로 분류되며, 75분 기준 약 16건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 토크, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-006 · CNC-H06-L02-03

- Title: AI 검토 요약 · Holdout 6구역 · 2셀 · CNC 가공기 3 · warning
- Summary: Holdout 6구역 · 2셀 · CNC 가공기 3는 현재 warning 상태이며 예측 위험도는 64.2%입니다. 동력 전달 계통, 열 방산 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 6구역 · 2셀 · CNC 가공기 3: warning 알림. 주축 모터, 커플링, 동력 전달 하우징, 스핀들 냉각 라인 및 가공부 열 배출 경로에서 동력 전달 계통, 열 방산 계통을 확인합니다. 기계 동력, 토크, 공정·공기 온도 차이와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 주축 구동 커플링 키트, 냉각 팬 유닛입니다.
- Process manager: Holdout 6구역 · 2셀 · CNC 가공기 3 위험 감지 건은 현재 생산 영향이 중간 수준으로 분류되며, 90분 기준 약 19건 손실 가능성이 있습니다. 모델 근거는 기계 동력, 토크, 공정·공기 온도 차이이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 22일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-007 · CNC-H07-L05-01

- Title: AI 검토 요약 · Holdout 7구역 · 5셀 · CNC 가공기 1 · 데이터 품질 보류
- Summary: Holdout 7구역 · 5셀 · CNC 가공기 1는 데이터 품질 보류 상태라 위험 등급과 예측 위험도를 확정하지 않습니다. 근거 공백이 있어 확정 판단보다 데이터 보강과 이력 조회가 우선입니다.
- Field operator: Holdout 7구역 · 5셀 · CNC 가공기 1: 데이터 품질 보류 알림. 연결된 점검 위치에서 의심 계통을 확인합니다. 패킷 근거와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 이 패킷에 없습니다.
- Process manager: Holdout 7구역 · 5셀 · CNC 가공기 1는 데이터 품질 보류 상태라 생산 영향과 추정 물량 손실을 확정하지 않습니다. 유사 이력은 아직 전용 이력 계약 미연결 상태입니다. 점검 승인 여부는 데이터 보강과 이력 조회 후 검토해야 합니다.
- Automated gold: `1.0` · PM: `1.0`

### HGS-008 · CNC-H08-L04-02

- Title: AI 검토 요약 · Holdout 8구역 · 4셀 · CNC 가공기 2 · warning
- Summary: Holdout 8구역 · 4셀 · CNC 가공기 2는 현재 warning 상태이며 예측 위험도는 86.9%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: Holdout 8구역 · 4셀 · CNC 가공기 2: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: Holdout 8구역 · 4셀 · CNC 가공기 2 위험 감지 건은 현재 생산 영향이 중간 수준으로 분류되며, 210분 기준 약 46건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 토크이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.
- Automated gold: `1.0` · PM: `1.0`

## Reviewer worksheet

| Case | Usable without edit (Y/N) | Incorrect required fact | Awkward Korean | Role mismatch | PM boundary check | Heuristic agreement (Y/N) | Comment |
|---|---|---|---|---|---|---|---|
| HGS-001 |  |  |  |  |  |  |  |
| HGS-002 |  |  |  |  |  |  |  |
| HGS-003 |  |  |  |  |  |  |  |
| HGS-004 |  |  |  |  |  |  |  |
| HGS-005 |  |  |  |  |  |  |  |
| HGS-006 |  |  |  |  |  |  |  |
| HGS-007 |  |  |  |  |  |  |  |
| HGS-008 |  |  |  |  |  |  |  |

## Reviewer disposition

- Completed rows: `__/8`
- Usable without edit: `__/8`
- Incorrect required facts: `__`
- Awkward Korean cases: `__`
- Role mismatch cases: `__`
- PM boundary failures: `__`
- Human gate: `not_measured / passed / failed`
- Reviewer rationale:

>

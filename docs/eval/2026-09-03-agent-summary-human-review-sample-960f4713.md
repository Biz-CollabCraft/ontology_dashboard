# Agent Summary Human Review Sample

## Review identity

- Campaign run ID: `decision-support-final-20260903-960f4713`
- Candidate SHA: `960f4713`
- Provider/model: `openai-compatible / gpt-4o-mini`
- Source artifact: `tests/eval/results/agent_summary_llm_eval_live_120_20260903_960f4713.json`
- Selection rule: each Gold case's accepted output at `iteration=1`
- Review status: **not_measured**
- Reviewer/date: `________________ / ________________`

This review is an independent human gate. Automated `usefulness_candidate` and
`korean_quality_candidate` scores do not determine the answers below.

## Decision rule

For every case, record:

1. **Usable without edit**: yes only if the copy can be shown to its intended role unchanged.
2. **Incorrect required fact**: quote the incorrect fact, or write `none`.
3. **Awkward Korean**: quote the phrase, or write `none`.
4. **Role mismatch**: describe information or action assigned to the wrong role, or write `none`.
5. **Heuristic agreement**: whether the automated usefulness/Korean pass agrees with the human judgment.

The human gate passes only when all eight rows are completed and the reviewer explicitly
records the disposition. Any accepted-with-edit case remains useful evidence, but does not
count as `usable without edit`.

## Selected outputs

### GS-001 · CNC-S01-L01-01

- Title: AI 검토 요약 · 1구역 · 1셀 · CNC 가공기 1 · normal
- Summary: 1구역 · 1셀 · CNC 가공기 1는 현재 normal 상태이며 예측 위험도는 11.6%입니다. 동력 전달 계통, 열 방산 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 1구역 · 1셀 · CNC 가공기 1: normal 알림. 주축 모터, 커플링, 동력 전달 하우징, 스핀들 냉각 라인 및 가공부 열 배출 경로에서 동력 전달 계통, 열 방산 계통을 확인합니다. 기계 동력, 토크, 공정·공기 온도 차이와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 주축 구동 커플링 키트, 냉각 팬 유닛입니다.
- Process manager: 1구역 · 1셀 · CNC 가공기 1 위험 감지 건은 현재 생산 영향이 없음이며, 45분 기준 약 0건 손실 가능성이 있습니다. 모델 근거는 기계 동력, 토크, 공정·공기 온도 차이이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 22일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-002 · CNC-S04-L04-01

- Title: AI 검토 요약 · 4구역 · 4셀 · CNC 가공기 1 · warning
- Summary: 4구역 · 4셀 · CNC 가공기 1는 현재 warning 상태이며 예측 위험도는 82.5%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 4구역 · 4셀 · CNC 가공기 1: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: 4구역 · 4셀 · CNC 가공기 1 위험 감지 건은 현재 생산 영향이 중간 수준이며, 120분 기준 약 25건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 토크이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-003 · CNC-S01-L04-03

- Title: AI 검토 요약 · 1구역 · 4셀 · CNC 가공기 3 · warning
- Summary: 1구역 · 4셀 · CNC 가공기 3는 현재 warning 상태이며 예측 위험도는 60.2%입니다. 열 방산 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 1구역 · 4셀 · CNC 가공기 3: warning 알림. 스핀들 냉각 라인 및 가공부 열 배출 경로, 주축 모터, 커플링, 동력 전달 하우징에서 열 방산 계통, 동력 전달 계통을 확인합니다. 공정·공기 온도 차이, 토크, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 냉각 팬 유닛, 주축 구동 커플링 키트입니다.
- Process manager: 1구역 · 4셀 · CNC 가공기 3 위험 감지 건은 현재 생산 영향이 중간 수준이며, 150분 기준 약 32건 손실 가능성이 있습니다. 모델 근거는 공정·공기 온도 차이, 토크, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 24일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-004 · CNC-S04-L02-03

- Title: AI 검토 요약 · 4구역 · 2셀 · CNC 가공기 3 · critical
- Summary: 4구역 · 2셀 · CNC 가공기 3는 현재 critical 상태이며 예측 위험도는 90.8%입니다. 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 4구역 · 2셀 · CNC 가공기 3: critical 알림. 주축 모터, 커플링, 동력 전달 하우징에서 동력 전달 계통을 확인합니다. 기계 동력, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름에는 점검 요청이 요청됨 상태로 접수되어 있습니다. 참고 부품 후보는 주축 구동 커플링 키트입니다.
- Process manager: 4구역 · 2셀 · CNC 가공기 3 위험 감지 건은 현재 생산 영향이 높은 수준이며, 240분 기준 약 51건 손실 가능성이 있습니다. 모델 근거는 기계 동력, 과부하 지표, 토크이고 작업 처리 흐름에는 점검 요청이 요청됨 상태로 접수되어 있습니다. 최근 유사 이력은 7월 22일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-005 · CNC-S03-L01-03

- Title: AI 검토 요약 · 3구역 · 1셀 · CNC 가공기 3 · warning
- Summary: 3구역 · 1셀 · CNC 가공기 3는 현재 warning 상태이며 예측 위험도는 77.2%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 3구역 · 1셀 · CNC 가공기 3: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: 3구역 · 1셀 · CNC 가공기 3 위험 감지 건은 현재 생산 영향이 낮은 수준이며, 100분 기준 약 18건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-006 · CNC-S02-L02-02

- Title: AI 검토 요약 · 2구역 · 2셀 · CNC 가공기 2 · attention
- Summary: 2구역 · 2셀 · CNC 가공기 2는 현재 attention 상태이며 예측 위험도는 29.5%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 2구역 · 2셀 · CNC 가공기 2: attention 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 토크, 기계 동력와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: 2구역 · 2셀 · CNC 가공기 2 위험 감지 건은 현재 생산 영향이 낮은 수준이며, 60분 기준 약 13건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 토크, 기계 동력이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-007 · CNC-S04-L05-01

- Title: AI 검토 요약 · 4구역 · 5셀 · CNC 가공기 1 · 데이터 품질 보류
- Summary: 4구역 · 5셀 · CNC 가공기 1는 데이터 품질 보류 상태라 위험 등급과 예측 위험도를 확정하지 않습니다. 근거 공백이 있어 확정 판단보다 데이터 보강과 이력 조회가 우선입니다.
- Field operator: 4구역 · 5셀 · CNC 가공기 1: 데이터 품질 보류 알림. 연결된 점검 위치에서 의심 계통을 확인합니다. 패킷 근거와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 이 패킷에 없습니다.
- Process manager: 4구역 · 5셀 · CNC 가공기 1 위험 감지 건은 현재 생산 영향이 낮은 수준이며, 40분 기준 추정 물량 손실 가능성이 있습니다. 모델 근거는 패킷 근거이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 유사 이력은 아직 요약 가능한 기록이 없습니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

### GS-008 · CNC-S04-L04-02

- Title: AI 검토 요약 · 4구역 · 4셀 · CNC 가공기 2 · warning
- Summary: 4구역 · 4셀 · CNC 가공기 2는 현재 warning 상태이며 예측 위험도는 82.5%입니다. 공구/마모 계통, 동력 전달 계통 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다.
- Field operator: 4구역 · 4셀 · CNC 가공기 2: warning 알림. 공구 매거진 및 스핀들 공구 체결부, 주축 모터, 커플링, 동력 전달 하우징에서 공구/마모 계통, 동력 전달 계통을 확인합니다. 공구 마모, 과부하 지표, 토크와 알람, 사진, 관측값을 기록해 정비/생산 관리자에게 전달합니다. 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 참고 부품 후보는 카바이드 절삭 인서트 1개, 주축 구동 커플링 키트입니다.
- Process manager: 4구역 · 4셀 · CNC 가공기 2 위험 감지 건은 현재 생산 영향이 중간 수준이며, 120분 기준 약 25건 손실 가능성이 있습니다. 모델 근거는 공구 마모, 과부하 지표, 토크이고 작업 처리 흐름은 아직 연결된 요청 상태가 없습니다. 최근 유사 이력은 7월 18일 1건으로 확인됩니다. 점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다.

## Reviewer worksheet

| Case | Usable without edit (Y/N) | Incorrect required fact | Awkward Korean | Role mismatch | Heuristic agreement (Y/N) | Comment |
|---|---|---|---|---|---|---|
| GS-001 |  |  |  |  |  |  |
| GS-002 |  |  |  |  |  |  |
| GS-003 |  |  |  |  |  |  |
| GS-004 |  |  |  |  |  |  |
| GS-005 |  |  |  |  |  |  |
| GS-006 |  |  |  |  |  |  |
| GS-007 |  |  |  |  |  |  |
| GS-008 |  |  |  |  |  |  |

## Reviewer disposition

- Completed rows: `__/8`
- Usable without edit: `__/8`
- Incorrect required facts: `__`
- Awkward Korean cases: `__`
- Role mismatch cases: `__`
- Human gate: `not_measured / passed / failed`
- Reviewer rationale:

>

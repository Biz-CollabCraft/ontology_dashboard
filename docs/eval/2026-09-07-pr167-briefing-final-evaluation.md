> 과거 실험 기록: 작성 당시 코드·프롬프트·입력·채점 조건의 결과입니다. 현재 demo의 검증 결과나 모델 선정으로 해석하지 않습니다. 개인 경로는 당시 산출물 위치이며 새 체크아웃에 포함되지 않을 수 있습니다. [흡수 범위와 재실행](evaluation-experiments-absorption-20260908.md)

# PR167 역할별 브리핑 구현·평가 공식 보고서

- 작성일: 2026-09-07
- 상태: **Verified within scope — 구현·로컬 회귀·합성 시간축 및 실제 provider fixture 비교 완료. 운영/실제 DB 브리핑 E2E는 미검증**
- 작업: DevSpace `ws_707a33a2b6`, `/Users/hb/.devspace/worktrees/ontology-dashboard-727ac25b`
- 브랜치: `codex/pr167-ai-briefing-optimization-plan`
- 확인 HEAD: `8a5c50d8daf8285b07b59f655673d0d0f6e97186`; 기반 `7d6d79f6` ancestor 확인.
- 기존 dirty 작업을 보존했다. 이 작업에서 발표 HTML/대본을 편집하지 않았으며 커밋·푸시하지 않았다.
- 보고서의 완료는 아래 범위에 한정된다. 발표 편집상의 완료 가정을 실행 증거로 사용하지 않았다.

## 1. 구현과 확인 범위

| 범위 | 결과와 근거 |
|---|---|
| 3역할 계약 | process_engineer / maintenance_technician / process_manager, summary v1.1. 과거 v1.0 계약 보존 및 consumer 공통 prose 호환 테스트 통과. |
| 자연어 편집 경계 | 공통 system prompt + 역할 priority, title/summary/role quote만 편집. 구조적 근거·source_ref·시점은 deterministic envelope 유지. |
| 선별 근거 전달 | 실제 provider prompt 구성에 tool-selected evidence 전달. production lookup은 non-hold의 생산 맥락이 있을 때 위험 등급과 별도로 적용. |
| 숫자와 grounding | confidence_label, 조건부 생산 영향, 손실 수량과 0 보존, 잘못된 손실 숫자 거절/fallback 테스트 통과. |
| 조회/생성 분리 | GET는 저장 결과 조회만 수행. 명시 refresh는 생성 경로. exact key라도 현재 packet·scope·version·context·prose를 다시 검증. |
| 변경 중 생성 | 저장 직전 현재 binding 재검사, 동시 요청/DB reservation/lease recovery 회귀 통과. 다중 worker 전체 원자적 snapshot transaction을 새로 구현한 것은 아니다. |
| Hybrid 선별 | 같은 근거에서 failure_probability만 최대 0.005 변할 때 선제 생성 유예. 의미 판단은 마지막 성공 생성 packet과 비교하므로 작은 변화가 누적되어 임계폭을 넘으면 생성. |
| 안전 우선순위 | schema/명시 stale·expiry 부적격 입력을 먼저 차단. 모델/프롬프트/스키마/범위/관측시각 변경, 위험 등급·생산 손실·정비 이력·기타 알 수 없는 변경은 재생성. 확률이 모델 threshold를 통과해도 생성. |
| 유예와 재사용 분리 | changed key를 유예해도 INELIGIBLE이며 GET는 pending. 과거 prose를 복사하거나 최신 packet으로 rebind하지 않는다. refresh로 현재 값 생성 가능. |

추가한 선별 기준은 좁은 범위의 첫 정책이다. 운영상 “중요하지 않음”이 검증된 일반 분류기가 아니다. 기본 Always를 유지한다. Hybrid의 마지막 성공 입력은 서비스 프로세스 메모리의 scheduling baseline으로만 보관하며 재시작 시 보수적으로 다시 생성한다. DB의 summary·원 생성 근거·key는 유지하고, 메모리 baseline은 조회의 source가 되지 않는다. authoritative TTL이 없는 입력의 만료 시간을 추정하지 않는다.

## 2. 같은 시간축의 정책 평가

**Evidence: measured_policy_simulation. 실제 운영 조회 준비율·provider 호출 감소율은 not_measured.**

80 snapshots = 기존 8 fixture × 10변화. 개발 GS-001~004 40개, 고정 최종 GS-005~008 40개. 기존에 알려진 fixture를 나눈 것이므로 독립 현장 표본/맹검 holdout이 아니다. 확률 임계폭 0.005를 v3 결과 실행 전에 고정했고 결과를 보고 조정하지 않았다.

동일 변화 간격 20초, watcher 5초, 각 변화 후 1/12/19초에 조회(240회), 182초 명시 refresh, 종료 220초. 개발 지연 8초; 최종 지연 12/18/8/25초. 지정 시점 첫 시도 실패, 10초 backoff, key당 2회 한도. 변경 → 완료 → watcher → refresh → 조회 순서. 오래된 key의 완료는 폐기한다. 성공 candidate의 prose 검증은 시뮬레이션 가정이며 실제 모델 검증률이 아니다.

v3는 기존 v2의 schema 밖 임의 필드를 실제 schema 필드로 대체했다. 조회 시각은 generation key 밖의 generated_at으로 모델링했다. 따라서 v2의 Always 65회와 v3의 57회를 직접 정책 개선 수치로 비교하면 안 된다.

| 지표 | Click | Always | Hybrid |
|---|---:|---:|---:|
| 중요 변화 생성 결정 | 0/40 | 40/40 | 40/40 |
| 중요 변화 잘못된 재사용 | 0/40 | 0/40 | 0/40 |
| 배경 생성 시작 | 0 | 57 | 51 |
| 명시 refresh 추가 시작 | 8 | 5 | 5 |
| 실패 / 재시도 | 0 / 0 | 9 / 9 | 9 / 9 |
| stale 완료 폐기 | 0 | 4 | 4 |
| 전체 조회 준비 | 11/240 | 141/240 | 112/240 |
| 전체 조회 준비율 | 4.58% | 58.75% | 46.67% |
| 중요 변화 구간 조회 준비 | 0/120 | 51/120 | 51/120 |

- **Always 대비 Hybrid 배경 생성 감소: 10.53% (57→51)**. refresh 포함 전체 시작은 62→56, **9.68%** 감소.
- 중요한 변화의 생성 결정 coverage는 100%지만 중요 변화 구간 조회 준비는 **42.5%**다. 서로 다른 지표다.
- 전체 조회 준비율은 **12.08%p 하락**한다. 작은 변화의 옛 문장을 제공하지 않기 때문에 생기는 유예 비용이다.
- 개발 Always/Hybrid 조회 준비: 84/120 (70%) / 64/120 (53.33%). 중요 변화는 두 정책 모두 20/20 결정, 32/60 조회 준비.
- 고정 최종 Always/Hybrid: 57/120 (47.5%) / 48/120 (40%). 중요 변화는 두 정책 모두 20/20 결정, 19/60 조회 준비.
- 따라서 “Hybrid가 모든 면에서 우수” 또는 “운영 비용 10.53% 절감”이라고 주장할 수 없다. 중요 변화 coverage를 지키며 비중요 구간의 준비율을 희생하는 제한된 합성 결과다.

## 3. 모델 비교 등록과 현재 실행 상태

고정 후보:
1. gpt-4o-mini-2024-07-18 (기존 설정 계열 기준)
2. gpt-4.1-mini-2025-04-14
3. gpt-4.1-nano-2025-04-14

8 동일 fixture × 2반복 × 3모델 = 48시도. 순서를 교차 회전하고 concurrency=1, temperature=0, timeout=30초, 같은 system/payload/schema 사용. 품질 하한 0.80, 기준 모델 대비 허용 하락 0.05, 전체 시도 직접 통과율 하한 100%. 등록은 2026-09-07T10:29:14.682038+00:00이며 첫 연결 시도보다 앞선다.

3역할 gold는 `gold_answers_three_role_v2.json`. 위험 사실/확인 포인트/역할별 위치와 검토 표현을 점검하는 **자동 포함 점수**다. exhaustive 의미 정확도, 현장 유용성, 결정 시간 개선, 한국어 품질의 사람 평가를 대신하지 않는다. 역사적 field_operator gold는 덮어쓰지 않았다.

원출력 자동 점수, 전체 시도 직접 통과율, accepted 출력, fallback 제공 점수를 분리 집계한다. 모든 후보가 하한을 만족할 때에만 등록된 비용 우선·p95 지연 차선 규칙으로 선택한다. 결과를 보고 하한이나 반복 횟수를 바꾸지 않는다.

실제 provider 비교는 사용자 전송 승인 후 **2026-09-07T11:02:18.364986Z~11:06:47.068679Z**에 완료했다. 48/48 응답에 실제 usage가 있으며 transport/provider 오류는 0회였다. 앞선 로컬 ConnectError 48회는 별도 환경 실패 run으로 보관하고 이 비교의 분모와 섞지 않는다. 자동 승인 거절 이후 사용자에게 입력/목적지/유료 호출 범위를 명시해 승인을 받았고 그 범위만 실행했다.

| 모델 (고정 snapshot) | 원출력 자동 점수 | 직접 통과 / 전체 | fallback 후 제공 점수 | p50 / p95 응답시간 | 16회 usage 기반 추정 비용 |
|---|---:|---:|---:|---:|---:|
| GPT-4o mini | 0.909722 | 16/16 | 0.909722 | 4.918 / 6.609초 | $0.019776 |
| GPT-4.1 mini | 0.920139 | 16/16 | 0.920139 | 5.476 / 6.022초 | $0.0504032 |
| GPT-4.1 nano | 0.871528 | 5/16 | 0.927083 | 6.009 / 6.915초 | $0.0138564 |

**선정 모델: gpt-4o-mini-2024-07-18.** 사전 등록 하한을 통과한 두 모델 중 비용이 낮았다. 현재 서비스 환경설정이나 운영 기본 모델을 수정한 것은 아니다. 전체 48회 추정 합계 **$0.0840356**. 4o mini의 1회 평균 추정 비용은 $0.001236이다. 지연은 transport와 provider 내부 schema retry를 포함한 호출 시간이며 사용자 판단 시간은 아니다. p95는 기존 harness의 유한표본 percentile 구현을 사용하며 16개 표본의 장기 tail 보장이 아니다.

모든 모델의 입력 토큰 합계는 각각 101,252였다. 출력은 4o mini 7,647 / 4.1 mini 6,189 / nano 9,328이다. nano의 거절 11회는 raw editable JSON 계약 실패다. 자동 점수가 0.871528이어도 직접 통과 하한을 만족하지 못하므로 선택에서 제외했다. nano의 fallback 후 점수 0.927083을 모델 품질로 제시하지 않는다. 원출력 보관은 prose와 역할 라벨로 한정되어, 허용 표면 밖의 provider 임의 필드는 보관하지 않는다.

직접 통과는 **비교 harness의 raw editable schema + merge 후 grounding 계약** 기준이다. 제품 provider의 merge는 구조 필드를 deterministic envelope로 보존하며, 평가의 raw 표면 검사는 추가로 엄격한 실험 gate다. 이를 배포된 provider의 실운영 직접 통과율로 일반화하지 않는다.

개발/고정 최종 자동 점수:
- 4o mini: 0.923611 / 0.895833, 각각 8/8 직접 통과.
- 4.1 mini: 0.944444 / 0.895833, 각각 8/8 직접 통과.
- nano: 0.826389 / 0.916666, 각각 1/8 / 4/8 직접 통과.

전체 역할별 포함 점수(engineer / technician / manager)는 4o mini **1.0 / 0.75 / 0.4375**, 4.1 mini **0.84375 / 0.5625 / 0.875**다. 전역 자동 점수가 높아도 역할별 표현 포함 편차가 있으며, 역할별 하한이나 사람의 선호까지 통과했다는 의미가 아니다. 다음 반복에서는 역할별 기준을 별도 등록하고 실제 사용자 확인을 받는 것이 필요하다. 이번 결과를 보고 기준을 소급 변경하지 않았다.

단가는 공식 모델 문서 기준이며 1M input/output token당 USD:
- GPT-4o mini: 0.15 / 0.60 — https://developers.openai.com/api/docs/models/gpt-4o-mini
- GPT-4.1 mini: 0.40 / 1.60 — https://developers.openai.com/api/docs/models/gpt-4.1-mini
- GPT-4.1 nano: 0.10 / 0.40 — https://developers.openai.com/api/docs/models/gpt-4.1-nano

사용량 기반 추정은 uncached list price이며 실제 청구 대사/할인·cache·reasoning tier를 측정한 것이 아니다. **모델×정책 통합 비교:** 별도 `model-policy-projection.json`은 모델별 사례당 실제 2회 응답시간 중 최댓값을 초 단위 올림하여 같은 시간축을 재생한다. 이는 **실측 지연을 넣은 시뮬레이션**이다. 변경된 packet은 provider에 추가 전송하지 않았으며, 검증 성공/실패·retry는 모델 가정을 따른다. nano는 품질 gate 미달로 제외했다.

| 모델 | 정책 | 전체 시작 | 조회 준비 | 중요 변화 조회 준비 | 투영 비용 |
|---|---|---:|---:|---:|---:|
| 4o mini | Click | 8 | 15/240 (6.25%) | 0/120 | $0.009888 |
| 4o mini | Always | 65 | 162/240 (67.5%) | 58/120 | $0.080340 |
| 4o mini | Hybrid | 58 | 128/240 (53.33%) | 58/120 | $0.071688 |
| 4.1 mini | Click | 8 | 16/240 (6.67%) | 0/120 | $0.0252016 |
| 4.1 mini | Always | 63 | 165/240 (68.75%) | 62/120 | $0.1984626 |
| 4.1 mini | Hybrid | 56 | 130/240 (54.17%) | 62/120 | $0.1764112 |

4o mini 배경 시작 57→50 (12.28%), refresh 포함 65→58 (10.77%). 이 값은 2절의 고정 지연 모델 결과 10.53%와 다른 실험이다. 비용은 평균 실제 usage×시작 수의 uncached 단가 투영이며 실제 정책 청구액이 아니다. 기본 Always를 유지하고 Hybrid를 선택 가능한 정책으로 제공한다.

## 4. 새 회귀 증거

| 실행 묶음 | 결과 |
|---|---|
| packet/summary/3역할/선별근거/grounding/watcher/operations/consumer readiness/기존 eval | 218 passed, 0 skipped (38.27s) |
| Context 계약/repository/evolution/read + packet eval + 정책/비교 | 133 passed, 22 skipped (22.45s) |
| standalone aiBrief + presentation consumer | 15 passed (2 files) |
| frontend TypeScript + Vite + initial bundle budget | 성공, initial JS 294.17 KiB / 310 KiB |
| diff whitespace | git diff --check 통과 |

22 skipped: disposable PostgreSQL unavailable 21개, PostgreSQL RLS only 1개. SQLite/fixture 결과를 PostgreSQL/RLS 검증으로 확대하지 않는다. 앞선 188/93 집중 실행은 중복이 있으므로 위 표와 합산하지 않는다. build의 기존 support.js 비모듈 경고와 큰 chunk 경고는 비차단이다. 실제 브라우저 사용자 E2E와 운영 DB에서의 생성·조회 및 실제 생산 시스템은 이번 결과로 검증되지 않았다. 팀 DB의 연결·RLS 범위 읽기는 아래 별도 inventory에서 확인했다.

## 5. 실제 DB 평가 가능성 확인

사용자 질문에 따라 기존 팀 DB 설정으로 **REPEATABLE READ + READ ONLY** 연결했다. RLS를 비활성화하거나 우회하지 않았고 기존 `scripts/connect_team_db.sh`와 같은 조직/프로젝트/workspace 범위를 사용했다. migration, seed, INSERT/UPDATE, LLM 전송은 0회다.

2026-09-07T11:10:57Z의 해당 범위 inventory:
- 결과 **181,741건 / 설비 100대**, 모델 `independent-logreg-v3.1`, provenance source_type `product_runtime_inference`.
- 관측시각 범위 2026-09-04~2026-10-28. 조회 시점 이전 38,730건, 미래 143,011건. 단순 최신순을 현재 상태로 사용하면 안 된다.
- Context source 14건: planning 8, maintenance_readiness 2, production 2, quality_delivery 2. 모두 **synthetic_demo_context**. binding 14건.
- 이 범위의 저장된 Agent Review Summary는 0건.
- 처음 scope 없이 읽은 0건은 RLS로 가려진 결과였으며 DB 전체가 비었다는 뜻이 아니었다. scoped 결과로 확인했다.

**실제 DB 평가는 유효한 다음 단계다.** 실제 관측시각 이전의 결과를 고정하고 source/context checksum·validity·binding을 확인한 뒤 읽기 전용 packet을 export하여 별도 평가 저장소에서 비교하는 것이 적절하다. 미래 자료는 별도 합성 시간축으로 다뤄야 한다. 실제 DB라는 저장 위치가 실제 공장 데이터·현장 운영 효과를 의미하지 않는다. 이번에는 inventory까지 확인했으며 실제 DB의 briefing packet 생성/LLM 비교/consumer E2E는 아직 실행하지 않았다. 이번 승인된 외부 호출은 8개 fixture 범위에 한정했다.

근거: `database-readiness-scoped.json` (SQL·scope·시각·read_only·RLS flags 포함). 이 팀 DB 확인이 disposable PostgreSQL 전용 22 skipped 테스트를 대체하지 않는다.

## 6. 보관·재현

원본 실행 보관: `/private/tmp/pr167-final-20260907`. 장기 전달용 사본과 해시 manifest는 현재 Codex 작업의 `outputs/pr167-evaluation`에 보관한다. Git 밖 raw 제외는 폐기가 아니며 입력/prompt/schema/gold, 원출력 또는 오류 종류, 수락/거절 이유, usage, 시작/완료 시각, source hashes를 함께 보관한다. 비밀값은 산출물에 넣지 않는다.

핵심 코드:
- systems/backend/app/operations/agent_review_summary_generation_policy.py
- systems/backend/app/operations/service.py
- scripts/evaluate_agent_review_generation_policy.py
- scripts/compare_agent_review_summary_models.py
- scripts/run_pr167_registered_comparison.py
- tests/test_agent_review_material_change.py
- tests/fixtures/agent_review_packets/gold_answers_three_role_v2.json

재현:
```sh
python3 scripts/evaluate_agent_review_generation_policy.py --output /private/tmp/pr167-final-20260907/temporal.json
# 아래 --prepare는 새 실험 등록용이다. 기존 등록을 덮어쓰지 말고 새 output-dir 사용.
python3 scripts/run_pr167_registered_comparison.py --prepare --output-dir /private/tmp/pr167-new-run
# 외부 전송 승인 후, 기존 키 파일을 출력하지 않고 이용:
python3 scripts/run_pr167_registered_comparison.py --output-dir /private/tmp/pr167-new-run --env-file /Users/hb/Documents/final/ontology-dashboard/.env
```

8 fixture 기준 외부 3모델 비교·등록 기준 모델 선정·실제 호출 지연/usage와 단가 기반 비용 추정은 완료했다. 실제 DB packet/consumer E2E, 운영상 임계폭 적정성, 사람의 유용성, disposable PostgreSQL/RLS 테스트, 실운영 조회 준비율/청구 비용 절감은 남아 있다.

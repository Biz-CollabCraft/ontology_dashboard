# Decision Agent post-fix 최종 평가 — 2026-09-15

이번 평가는 `396c5f76`의 근거 고정·저장 직전 재검증·모호 측정 분류 fail-closed 수정 이후 다시 실행했다. 결론은 두 가지다. **구조 도입은 정답률 우위가 아니라 실행 경계의 안정성으로 설명해야 한다.** 모델 선택은 draft gold agreement 기준에서 **Luna가 4o-mini보다 안정적이었다.**

이 문서는 면접·PR 설명에 사용할 수 있는 범위를 고정하기 위한 기록이다. 현장 정확도, 실제 정비 성과, 배포 환경 성능, 사람 검수 완료 gold 성능으로 해석하지 않는다.

## 변경 후 다시 확인한 경계

수정 후 DecisionSession은 실행 시작 시점의 packet을 안정화해 evidence binding을 만들고, 도구 조회도 그 packet에 묶는다. 결과를 저장하기 직전에는 같은 identity로 현재 packet을 다시 읽어 binding이 바뀌었는지 확인한다. 중간에 같은 Evidence ID의 내용이 바뀌면 결과 저장을 막는다.

텍스트 해석에서는 `measurement_status=required`가 나오려면 `meaning=new_measurement`여야 한다. `record_review`와 `required`가 같이 나오면 해석 불일치로 보고 추천을 보류한다. 이 경계는 모델 점수가 아니라 안전한 계약이다.

## 구조효과 재평가

입력과 프로토콜은 실행 전에 등록했다. 오프라인 평가는 합성 tool response와 고정 해석 provider를 사용했다. 실제 DB·네트워크 지연이나 현장 도구 성능은 측정하지 않았다.

| 방식 | 실행 | 기대 결과 일치 | 도구 시도 | 불필요 도구 | 누락 필수 도구 | unsafe result |
|---|---:|---:|---:|---:|---:|---:|
| bulk | 27 | 27 | 48 | 6 | 0 | 0 |
| sequential | 27 | 27 | 42 | 0 | 0 | 0 |
| LangGraph | 27 | 27 | 42 | 0 | 0 | 0 |

LangGraph는 이 세트에서 sequential보다 판단 정답률이 높지 않았다. 같은 결정 정책과 같은 해석 경계를 쓰면 결과는 같았다. 따라서 “LangGraph라서 판단 품질이 올랐다”고 말하지 않는다.

확인된 구조 효과는 다른 쪽이다. 현재 구조는 병렬 조회, durable 저장, 재시작 복구, stale writer 차단, retry 예산, tool 결과 재사용, 최초 근거 고정, 저장 직전 근거 변경 차단을 하나의 실행 경계로 묶었다. bulk 방식은 같은 기대 결과를 냈지만 불필요한 도구 조회가 6건 있었다. sequential 방식은 이번 세트에서 같은 결과를 냈지만 durable/resume 경계 자체를 검증한 운영 구조가 아니다.

면접에서는 이렇게 말하는 것이 안전하다.

> LangGraph 도입 효과를 정답률 상승으로 주장하지 않았습니다. 같은 판단 결과를 유지하면서, 중간 실패·재시작·동시 실행·근거 변경 상황에서 결과를 안전하게 저장하거나 보류하는 실행 경계를 검증했습니다.

## draft gold 모델 비교

v1.1 후보셋은 48건이며 구조 검증 오류는 0이었다. evaluation split 24건 중 unresolved 4건은 제외했고, 제안 라벨이 있는 20건만 모델별 1회 비교했다. 이 라벨은 사람 검수 완료 gold가 아니라 draft/proposed label이다.

| 모델 | exact flags | unresolved conflict FP | measurement required FN/FP | human review missed | API calls | tokens | 평균 batch latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| gpt-4o-mini | 16/20 | 4 | 0/0 | 0 | 3 | 5,082 | 3.840초 |
| gpt-5.6-luna | 20/20 | 0 | 0/0 | 0 | 3 | 5,499 | 7.209초 |

이번 기준에서는 Luna가 더 안정적이었다. 특히 4o-mini는 충돌이 아닌 16건 중 4건을 충돌로 과잉 판정했다. Luna는 그 false positive가 없었다. 두 모델 모두 측정 필요성 누락·과잉과 사람 검토 필요 케이스 누락은 없었다.

다만 이 결과는 현장 정확도나 범용 모델 우위를 뜻하지 않는다. 동일 합성 후보셋, 동일 구조화 출력 schema, 동일 프롬프트, 동일 evaluation split에서 관찰한 draft label agreement다. Luna는 더 느리고 토큰도 조금 더 썼다.

## live PostgreSQL smoke

로컬 PostgreSQL 환경에서 durable DecisionSession 저장소 테스트 2건을 실행했다. 두 테스트 모두 통과했다. 이는 현재 저장소 경로에서 durable 상태 저장과 재사용이 동작한다는 smoke evidence다. 제품 배포 환경의 DB 성능이나 장애 복구 SLA를 측정한 것은 아니다.

## 최종 검증 명령과 결과

- Decision 계열: `157 passed, 2 skipped`
- 구조/Gold/모델 비교 계약: `23 passed`
- live PostgreSQL durable smoke: `2 passed`
- 아키텍처 검사: `PASS`
- diff whitespace 검사: 통과

PostgreSQL 2건은 기본 전체 테스트에서는 환경변수가 없으면 skip된다. 이번에는 실행 중인 로컬 PostgreSQL 포트를 지정해 별도 통과를 확인했다.

## 현재 말할 수 있는 성과

- Decision Agent는 read-only tool, deterministic Policy Guard, 사람 승인 경계를 유지했다.
- 같은 Evidence ID의 내용이 실행 중 바뀌는 경우를 결과 저장 전에 차단한다.
- 모델이 “기록 검토”와 “새 측정 필요”를 모순되게 분류하면 추천하지 않고 보류한다.
- post-fix 구조평가에서 LangGraph는 bulk 대비 불필요 도구 조회 없이 같은 기대 결과를 냈다.
- draft gold agreement에서 Luna는 20/20, 4o-mini는 16/20이었다.

## 말하지 말아야 하는 것

- LangGraph가 판단 정확도를 높였다고 단정하지 않는다.
- draft gold agreement를 사람 검수 완료 gold 성능으로 말하지 않는다.
- synthetic fixture 결과를 실제 공장 운영 성과나 실시간 backend 성능으로 말하지 않는다.
- 토큰·지연을 운영 비용 절감이나 SLA로 환산하지 않는다.

## 증거 파일

- `artifacts/decision-structure-postfix-2026-09-15/registration.json`
- `artifacts/decision-structure-postfix-2026-09-15/offline.json`
- `artifacts/decision-model-comparison-postfix-2026-09-15/registration.json`
- `artifacts/decision-model-comparison-postfix-2026-09-15/comparison.json`
- `tests/test_decision_durable_runner.py`
- `tests/test_decision_text_measurement_boundary.py`
- `tests/test_decision_durable_postgresql.py`

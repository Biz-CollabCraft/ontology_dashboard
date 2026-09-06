# Live 120-Run Sample Rationale

작성일: 2026-09-05

## 결론

120회 평가는 발표에서 사용할 수 있다. 다만 의미는 "운영 전체 정확도 검증"이 아니라 "정해진 8개 gold case에서 live LLM 요약이 반복 호출 중에도 구조, 근거, 역할 분리, 금지 주장 경계를 유지했는지 확인한 release-gate"로 제한한다.

## 왜 120회인가

120회는 임의의 큰 숫자가 아니라 다음 구조다.

- 8개 gold case
- case당 15회 반복
- 총 8 x 15 = 120회 live provider 호출

8개 case는 normal, attention, warning, critical, data-quality hold, SOP present/absent, grounded source refs, closed-loop read-only boundary를 포함한다. 즉 케이스 수는 도메인 폭을 대표하려는 최소 gold set이고, 반복 수는 같은 입력에서 LLM 출력이 흔들리거나 provider 호출 중 형식 실패/fallback이 생기는지 보기 위한 안정성 확인이다.

## 확인된 것

- 8개 case 모두 15/15 accepted
- 전체 120/120 accepted
- fallback 0
- contract error 0
- missing required points 0
- must-not-claim violations 0
- grounding rate 1.0
- live LLM p50 3,906 ms, p95 5,788 ms

## 타당한 해석

- "정해진 gold fixture에서는 반복 호출해도 요약 형식과 근거 경계가 안정적이었다"는 말은 가능하다.
- "8개 대표 위험/경계 시나리오를 case당 15회 반복해 총 120회 live 평가했다"는 말은 가능하다.
- "출시 전 회귀 게이트로는 충분히 의미 있는 반복 수였다"는 말은 가능하다.
- 0/120 failure는 단순 독립 시행으로 보면 실패율 상한을 낮게 보는 참고 근거가 될 수 있지만, 실제로는 같은 8개 fixture 반복이므로 운영 모집단 전체의 통계 보장으로 말하지 않는다.

## 말하지 말아야 할 것

- "120회라서 실제 공장 전체 정확도가 검증됐다."
- "운영 환경에서 장애가 0%다."
- "실제 비용 절감이나 정비 성과가 검증됐다."
- "사람 검토 없이도 유용성이 확정됐다."
- "MES/CMMS/WMS/QMS 연동 효과가 검증됐다."

## 발표용 표현

"평가는 8개 gold 시나리오를 각각 15번 반복해 총 120회 실행했습니다. 여기서 보려던 것은 공장 전체 통계가 아니라, 같은 근거를 여러 번 넣어도 AI 요약이 정해진 형식, 출처 근거, 역할별 표현, 금지 주장 경계를 안정적으로 지키는지였습니다. 결과는 120/120 accepted, fallback 0, 금지 주장 위반 0이었습니다. 그래서 이 수치는 운영 KPI가 아니라 live LLM 요약의 반복 안정성 확인으로 해석했습니다."

## 더 강하게 만들려면

- provider_reported token 기준으로 120-run을 재실행한다.
- holdout/paraphrase를 8 x 3에서 더 늘려 문장 변형 내성을 확인한다.
- 사람 리뷰를 완료해 유용성/한국어 품질의 자동 점수 한계를 보완한다.
- 실제 runtime DB/watcher/UI consumer 경로와 분리된 live provider 평가라는 점을 계속 표시한다.

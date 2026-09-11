# AI 브리핑 판단 유용성 블라인드 에이전트 예비평가

3 agent blind judges over 8 anonymized A/B briefing samples; agents received case context and decision tasks but not condition labels; not a substitute for human operator evaluation

| 조건 | 선호 표 | 비율 |
|---|---:|---:|
| Pipeline | 17/24 | 70.8% |
| Direct | 7/24 | 29.2% |

에이전트 평가는 Pipeline/Direct 라벨을 숨긴 상태에서 X/Y 브리핑 중 다음 조치 판단에 더 유용한 쪽을 고르게 했다. 표본은 8개 케이스에서 1회차씩 뽑은 예비 샘플이다.

사용 가능한 발표 문장: 같은 A/B 출력을 라벨 없이 에이전트 3명이 평가했을 때, Pipeline 브리핑이 24표 중 17표(70.8%)에서 더 유용하다고 선택됐다.

한계: 실제 보전/공정/생산 담당자의 사용자 평가가 아니며, 케이스 context와 기대 상태가 제공된 조건의 예비 판단이다.

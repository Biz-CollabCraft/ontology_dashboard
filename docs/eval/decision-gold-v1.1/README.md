# 골드 초안 v1.1 — 두 라벨의 일관성 보강

48개 원문을 기존 정의와 대조했다. **정보 누락 라벨은 그대로 유지하고, 측정 상태 라벨 5건을 수정했다.** 원문·정책·행동 제약·프롬프트는 바꾸지 않았다. assistant 검토이며 사람 검수 승인이 아니다.

- [정의와 경계](rubric-and-protocol.md)
- [기존 모델 응답의 두 항목 불일치 전체 기록](disagreement-review.md)
- 데이터: `tests/fixtures/decision_gold/v1.1/candidates.json`
- 파일 SHA256: `fbfb8c6be3ecd69bd047b9d59a821ca181f55868ac92a97e67544fff0d0395bc`
- 원본 v1 SHA256: `a65b3dd75543e7e93601d0a5ce0346cef2736bb412f76d3ba6f9fe26c48ab284`

변경 사례는 D03-04, D06-04, H03-04, H04-04, H06-04다. 작업 대상/종류를 특정할 수 없는 현재 지시의 measurement_status를 not_stated에서 unclear로 통일했다. 같은 원리를 개발용 H04-04에도 적용했다. unclear는 측정 요구를 새로 만드는 값이 아니다. 이 5건은 이미 uncertain=true이므로 사람 검토/진단 행동 제약은 달라지지 않는다.

정보 누락은 기록이나 값이 없거나 확인되지 않았다는 원문 진술에만 붙인다. 새 측정 필요, 의견 충돌, 기록 조회, 불분명한 지시만으로는 true로 만들지 않는다. optional과 not_required는 선택 가능한 측정의 존재 여부로 구분한다. 새 측정을 하지 말고 기존 기록을 보라고 정정하면 not_required다.

원본 v1, 기존 점수와 실행 증거는 유지했다. v1.1은 결과를 보고 기준을 정리했으므로 독립 평가셋으로 주장하지 않고 개발/회귀에만 사용한다. 44개 제안·4개 미정·48개 검수 대기를 유지한다. 새 모델 호출·수정 라벨 재채점·프롬프트 조정은 하지 않았다. 후보의 model_calls_on_this_dataset는 작성 스냅샷 값이며 원문 일부는 v1에서 이미 평가됐다.

```sh
python3 scripts/validate_decision_gold.py tests/fixtures/decision_gold/v1.1/candidates.json
# 사람 검수가 없으므로 다음 명령은 실패해야 한다.
python3 scripts/validate_decision_gold.py tests/fixtures/decision_gold/v1.1/candidates.json --release-check
```

## 에이전트 검수

[두 에이전트의 검수 결과와 의견 차이](agent-review.md)를 기록했다. 제안 44건에서 확정적 기준 위반은 발견하지 못했지만 복합 지시 표현 공백과 미정 사례 처리 의견 차이가 남아 있다. 사람 검수 상태는 변경하지 않았다.

## 프롬프트 보강

[의미 해석 프롬프트 v4](prompt-v4.md)에 검수에서 합의한 일반 기준을 반영했다. 데이터 라벨은 유지하며 [v4 회귀 평가](prompt-v4-evaluation-2026-09-14.md)를 완료했다. 정보 누락 일치는 개선됐지만 의미 분류와 일부 보류 판단의 회귀가 남았다.

## 기준 모델 선택

사용자 승인으로 [Luna + v4 기준과 한계](../../operations/decision-agent-luna-v4-baseline.md)를 기록하고 대상 worktree의 로컬 설정을 적용했다. 기본 provider 실제 호출·메모리 세션 재조회까지 확인했으며 서버 배포 반영을 뜻하지 않는다.

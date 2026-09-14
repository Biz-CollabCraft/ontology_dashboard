# 두 항목 불일치 검토 기록

기존 응답을 읽어 분류한 기록이며 새 모델 호출·재채점은 하지 않았다. 정보 누락 제안 라벨은 모두 유지했다. measurement_status 5건만 변경했다. human review는 48개 모두 pending이다.

| 사례 | 항목 | 모델 | 반복 | 기존 제안 → 응답 | 검토 결과 |
|---|---|---|---|---|---|
| D03-04 | measurement_status | gpt-4o-mini | 1 | not_stated → unclear | draft_label_inconsistency |
| D05-01 | measurement_status | gpt-4o-mini | 1 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| D03-01 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| D05-02 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-01 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-02 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-02 | measurement_status | gpt-5.6-luna | 1 | not_required → not_stated | model_disagrees_with_explicit_text_rubric |
| D06-04 | measurement_status | gpt-5.6-luna | 1 | not_stated → unclear | draft_label_inconsistency |
| H03-04 | measurement_status | gpt-5.6-luna | 1 | not_stated → unclear | draft_label_inconsistency |
| H05-02 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-04 | measurement_status | gpt-4o-mini | 1 | not_stated → unclear | draft_label_inconsistency |
| H03-01 | measurement_status | gpt-4o-mini | 1 | not_stated → unclear | model_disagrees_with_explicit_text_rubric |
| H03-04 | measurement_status | gpt-4o-mini | 1 | not_stated → unclear | draft_label_inconsistency |
| H05-01 | measurement_status | gpt-4o-mini | 1 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| H06-01 | information_missing | gpt-5.6-luna | 1 | False → True | model_disagrees_with_explicit_text_rubric |
| H06-04 | measurement_status | gpt-5.6-luna | 1 | not_stated → unclear | draft_label_inconsistency |
| D03-01 | information_missing | gpt-5.6-luna | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| D05-02 | information_missing | gpt-5.6-luna | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-01 | information_missing | gpt-5.6-luna | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-02 | measurement_status | gpt-5.6-luna | 2 | not_required → not_stated | model_disagrees_with_explicit_text_rubric |
| D03-04 | measurement_status | gpt-4o-mini | 2 | not_stated → unclear | draft_label_inconsistency |
| D05-01 | measurement_status | gpt-4o-mini | 2 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| H03-04 | measurement_status | gpt-4o-mini | 2 | not_stated → unclear | draft_label_inconsistency |
| H05-01 | measurement_status | gpt-4o-mini | 2 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| H03-04 | measurement_status | gpt-5.6-luna | 2 | not_stated → unclear | draft_label_inconsistency |
| H05-02 | information_missing | gpt-5.6-luna | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| H06-04 | information_missing | gpt-5.6-luna | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| H06-04 | measurement_status | gpt-5.6-luna | 2 | not_stated → unclear | draft_label_inconsistency |
| H06-04 | information_missing | gpt-4o-mini | 2 | False → True | model_disagrees_with_explicit_text_rubric |
| D03-04 | measurement_status | gpt-4o-mini | 3 | not_stated → unclear | draft_label_inconsistency |
| D05-01 | measurement_status | gpt-4o-mini | 3 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| D03-01 | information_missing | gpt-5.6-luna | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| D05-02 | information_missing | gpt-5.6-luna | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-01 | information_missing | gpt-5.6-luna | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-02 | information_missing | gpt-5.6-luna | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-02 | measurement_status | gpt-5.6-luna | 3 | not_required → not_stated | model_disagrees_with_explicit_text_rubric |
| H03-04 | measurement_status | gpt-5.6-luna | 3 | not_stated → unclear | draft_label_inconsistency |
| H05-02 | information_missing | gpt-5.6-luna | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| D06-04 | measurement_status | gpt-4o-mini | 3 | not_stated → unclear | draft_label_inconsistency |
| H03-01 | measurement_status | gpt-4o-mini | 3 | not_stated → unclear | model_disagrees_with_explicit_text_rubric |
| H03-04 | measurement_status | gpt-4o-mini | 3 | not_stated → unclear | draft_label_inconsistency |
| H05-01 | measurement_status | gpt-4o-mini | 3 | optional → not_required | model_disagrees_with_explicit_text_rubric |
| H06-04 | information_missing | gpt-4o-mini | 3 | False → True | model_disagrees_with_explicit_text_rubric |
| H06-04 | measurement_status | gpt-5.6-luna | 3 | not_stated → unclear | draft_label_inconsistency |

draft_label_inconsistency는 일관성이 부족했던 초안 라벨을 수정했다는 뜻이다. model_disagrees_with_explicit_text_rubric는 원문 명시 기준과 응답이 맞지 않는다는 뜻이며 실제 공장 사실의 오류 판정은 아니다. 새 기준에서 남는 불일치도 사람 검수가 필요하다.

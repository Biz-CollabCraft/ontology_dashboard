# always 경로의 생성 누락·중복 호출 원인

기준: PR #171 병합 이후 demo dd2f4a52. 기존 demand 실험과 분리해 always 소비 경로를 검토했다. 개인 로컬 리뷰 기준과 저장소 docs/ai-code-review-context.md의 사실/표현/권한 경계를 적용했다. 과거 docs/mentoring-mvp-2026-08/README.md 경로는 이 체크아웃에 없다.

## 원인과 수정

1. **후보 범위 고정 — Verified, 수정 방향 Pass.** watcher는 always여도 전달받은 후보만 생성한다. 실행 스크립트의 기본 limit는 10이며, 서비스→AssetDetailViewModel→DB adapter 경로가 항상 offset=0을 조회했다. 고정된 후보 집합에서는 뒤쪽 설비가 계속 제외된다. 범위별 프로세스 내부 순회 위치를 보관하고 offset을 기존 저장소 조회까지 전달하도록 수정했다. 마지막 페이지나 데이터 감소로 인한 빈 페이지에서는 처음으로 돌아온다. fixture 조회는 live 순회 위치를 소비하지 않는다.
2. **최초 생성과 강제 재생성 혼동 — Verified, 수정 방향 Pass.** standalone 화면은 ‘생성’과 ‘다시 생성’ 모두 ui_manual_regeneration으로 전송했다. 빈 결과를 조회한 뒤 watcher가 생성해도 첫 클릭이 force=true로 exact 저장본을 다시 생성할 수 있었다. 저장된 설명이 없는 ‘생성’은 manual_materialization, 표시된 설명을 바꾸는 ‘다시 생성’만 ui_manual_regeneration으로 구분했다.
3. **정책 기본값과 실행 상태 혼동.** run_local_live.sh의 ENABLE_AGENT_SUMMARY_WATCHER 기본값은 0이다. always는 실행된 watcher의 정책이지 scheduler 활성화 설정이 아니다. 운영에서 실제 실행 중인지 이번 검증만으로 단정하지 않는다. 공급자·DB·watcher 활성화 설정은 변경하지 않았다.

## 검증

- 고정 설비 3대·회당 2대의 실제 서비스/로컬 저장소 테스트: 수정 전 생성 수 [2,0,0], 수정 후 [2,1,0]. 공급자 호출은 총 3회이고 세 번째 순회는 2개 exact 저장본을 재사용한다. 후보·공급자는 테스트 대역이며 운영 DB 지표가 아니다.
- 내부 read port→DB adapter→repository 전달에서 scope/version/offset/limit 보존 검증. 데이터 감소 시 처음으로 돌아오기, scope별 커서 분리와 fixture 순회 영향 없음 검증.
- 인증된 selected-event HTTP 경로: GET은 생성하지 않음→watcher 생성 1회→최초 생성 POST 추가 호출 0→명시 재생성 POST 추가 호출 1. 실제 서비스·로컬 DB와 테스트 공급자를 사용했다.
- UI 버튼 문구와 전송 trigger 계약 검증. 브라우저 전체 E2E 또는 실제 Luna 호출을 새로 실행한 것은 아니다.
- 백엔드 회귀 152 passed (36.98초), 프런트엔드 18 passed, tsc -b 통과. 기존 watcher read-port 기대값은 새 offset=0 계약에 맞춰 갱신했다.

## 경계와 남은 한계

기존 producer Artifact→저장 payload→read model→packet 경로를 유지한다. 원시 센서/fixture를 UI에 새로 전달하지 않으며 hidden/evaluation truth를 추가하지 않는다. LLM은 표현만 생성하고 source refs·권한·상태·exact binding 검증은 유지한다. HTTP/schema 응답 형태는 바뀌지 않고 내부 read port의 offset은 기본값 0인 선택 인수다. 미보고 사용량이나 운영 비용을 추정하지 않는다.

순회 커서는 메모리에 있으므로 프로세스 재시작 시 처음부터 시작한다. 여러 worker 사이에 공유되지 않는다. 후보 정렬은 위험 확률 순이라 연속 변화 중에는 중복 방문/방문 지연이 가능하며 엄격한 완료시간을 보장하지 않는다. 모델 호출은 여전히 순차 실행이므로 전체 순회 시간은 호출 지연·후보 수·간격에 영향을 받는다. 안정된 후보 집합의 영구적인 첫 페이지 고정 문제를 해결한 것이지 운영 가용성이나 비용 절감을 입증한 결과가 아니다.

기본 always 및 demand 선택 옵션은 변경하지 않았다. 운영 DB 쓰기·외부 LLM 전송·배포 없음.

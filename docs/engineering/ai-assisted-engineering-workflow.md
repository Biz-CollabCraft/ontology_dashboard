# AI-Assisted Engineering Workflow

이 문서는 AI/에이전트를 많이 사용하는 개발에서 구현 속도와 인간의 엔지니어링 판단을 함께 보존하기 위한 공통 작업 규칙이다.

## 1. 작업 시작 계약

구현 전에 다음을 기록한다.

- **Observed problem**: 실제 코드, 사용자 흐름, 로그, 수치에서 관측된 문제.
- **Human hypothesis**: 사용자가 현재 가장 가능성이 높다고 보는 원인 또는 설계 판단.
- **Prediction**: 실험 전에 사용자가 예상한 관측 결과.
- **Stop condition / Budget**: 종료 기준과 허용된 실험 범위·시간·반복 예산.
- **Falsification condition**: 어떤 결과가 나오면 위 가설을 수정하거나 폐기할지.
- **Decision required**: 이번 작업에서 증거를 본 뒤 사용자가 직접 내려야 하는 결정.
- **Unknowns**: 아직 확인되지 않은 사실.

AI는 Human hypothesis를 더 그럴듯하게 꾸며서 확정하지 않는다. 사용자가 명시하지 않은 경우에는 `unrecorded`로 남기고, AI가 만드는 원인 후보는 **AI/challenger hypotheses**로 분리한다.

## 2. 구현 전 판별

바로 기능을 추가하지 않는다. 가능한 경우 최소 두 선택지를 두고 가장 작은 판별 실험을 먼저 설계한다.

각 실험은 다음을 갖는다.

- baseline
- challenger
- invariant
- discriminating experiment
- workload / fixture
- metric
- adoption or rejection gate
- expected downside

단순하고 되돌리기 쉬운 변경, 명백한 버그 수정처럼 대안 실험의 가치가 낮은 작업은 예외로 할 수 있으나 이유를 짧게 남긴다.

## 3. AI와 사람의 역할

AI/에이전트가 맡아도 되는 일:

- 저장소/공식 문서 조사
- 원인 후보와 반례 생성
- 대안 설계
- 테스트/benchmark 초안과 실행
- 구현
- 반복 검증
- 증거 압축과 skeptical review

사람이 소유하는 일:

- Human hypothesis의 원문
- 제품/아키텍처에서 중요한 Decision required
- trade-off를 받아들일지 여부
- 최종 채택/보류/기각
- **Changed belief**: 증거 때문에 자신의 판단이 어떻게 바뀌었는지

AI는 사람 소유 항목을 사용자 대신 사후적으로 지어내지 않는다.

## 4. 완료 계약

기능이 동작하는 것만으로 작업을 완료 처리하지 않는다. 중요한 설계/성능/안정성 변경은 다음을 남긴다.

1. 재현 가능한 problem/evidence
2. initial Human hypothesis 또는 `unrecorded`
3. 대안과 판별 실험
4. 실행한 test/benchmark와 revision/environment
5. 결과와 limitation
6. Human decision
7. Changed belief
8. follow-up 또는 남은 unknown

측정하지 않은 개선 효과는 결과로 쓰지 않는다.

## 5. 계획서 최소 템플릿

```md
## Problem framing
- Observed problem:
- Human hypothesis:
- Prediction:
- Stop condition / Budget:
- Falsification condition:
- Decision required:
- Unknowns:

## Alternatives
- Baseline:
- Challenger:
- Invariants:

## Discriminating experiment
- Fixture/workload:
- Metrics:
- Adoption/rejection gate:

## Implementation
...

## Outcome
- Evidence:
- Result:
- Human decision:
- Changed belief:
- Limitations:
- Follow-up:
- Stop condition met / Reason:
- Source decision/evidence paths:
```

## 6. 병렬 에이전트 규칙

병렬성은 동일 결론을 여러 번 생성하는 데 쓰기보다 관점을 분리하는 데 사용한다.

권장 역할은 baseline, challenger, adversarial test, performance/evaluation, skeptical review다. 서로 다른 worker가 같은 성공 기준을 임의로 바꾸지 않는다. 통합 전에는 같은 fixture와 invariant를 기준으로 비교한다.

## 7. 기록 원칙

계획서는 미래 의도를 기록하고, Evidence/Decision은 실제 실행 결과를 기록한다. 오래된 계획의 가설을 현재 사용자의 생각인 것처럼 역으로 고쳐 쓰지 않는다. 과거 중요한 판단을 복원할 때는 당시 근거가 확인되는 범위와 사후 해석을 구분한다.

## 8. Engineering loop와 종료

중요한 설계·성능·안정성 작업은 다음 순서로 기록한다.

1. **Problem**: 어떤 조건에서 무엇이 기대와 다르게 동작하는지, 이번에 풀 대표 문제를 좁힌다.
2. **Human hypothesis / Prediction**: 사람의 원인 가설과 실험 전 예상 결과를 기록한다. AI 후보는 별도로 표시한다.
3. **Falsification condition**: 어떤 관측이면 가설을 기각하거나 수정할지 미리 정한다.
4. **Experiment**: baseline, fixture/workload, invariant, 판별 지표, 실행 예산을 정하고 허용된 범위에서 실행한다.
5. **Evidence**: 실제 결과, 재현 명령, revision과 미커밋 변경 여부, 환경, 원시 결과 경로, 한계와 미측정 영역을 남긴다.
6. **Human decision**: 사람의 결과 해석, 채택/보류/기각과 trade-off를 기록한다.
7. **Changed belief**: 증거로 사람의 판단이 어떻게 바뀌었는지 기록한다.
8. **Stop condition**: 시작 전에 정한 종료 조건·예산의 충족 여부와 종료 이유를 확인한다. 실패/불충분도 명시하고 다음 문제를 자동으로 시작하지 않는다.

사람이 말하지 않은 예측·해석·결정·판단 변화는 `unrecorded` 또는 `pending human decision`으로 남긴다. AI 제안이나 테스트 통과를 사람의 최종 결정으로 바꾸지 않는다. 이미 승인된 범위의 조사·구현·검증은 진행할 수 있지만, 미결 판단을 완료로 표시하지 않는다.

새 기능이나 하위 문제가 현재 대표 문제를 해결하는 데 필수인지 확인한다. 필수가 아니면 별도 backlog로 보낸다. 프로젝트별 기존 Human Gate, 실행 승인, 더 엄격한 종료 조건은 그대로 따른다.

## 9. 프로젝트 repo와 Career OS의 기록 경계

**코드·실험·결정의 source of truth는 해당 프로젝트의 로컬 repo다. Career OS는 인덱스·요약·역량 연결과 커리어 재사용 상태를 관리한다.**

| 기록 | 원본 위치와 역할 |
| --- | --- |
| 상시 규칙 | 루트 `AGENTS.md` |
| 상세 작업 방법 | 이 문서 |
| 앞으로 할 일 | `docs/plans/` |
| 선택·판단·Changed belief | `docs/decisions/YYYY-MM-DD-*.md` |
| 실제 실행 결과·한계·원시 증거 참조 | `docs/evidence/YYYY-MM-DD-*.md` |
| 경험 인덱스·역량 연결·재사용 상태 | Career OS |

decision은 evidence를 링크하고, evidence는 실행 코드·fixture·원시 결과를 참조한다. 동일 내용을 양쪽에 전문 복사하지 않는다. 기존 `docs/architecture/`, `docs/eval/`, 실험 디렉터리 등의 원본은 이동하거나 복제하지 않고 참조한다. 대용량·민감 산출물은 기존 보관 정책을 따르고 repo에는 재현 정보와 안전한 참조를 유지한다.

Career OS에는 다음 항목만 적재한다.

- **원본 링크**: repo 식별자, decision/evidence 경로, 참조 commit/revision. 미커밋이면 그 사실과 확인 시점을 표시하고 존재하지 않는 commit 링크를 만들지 않는다.
- **요약**: 문제, 실제 결과, 사람의 결정 또는 미결 상태, 검증 범위와 제한.
- **역량 증거 연결**: 어떤 역량을 어떤 repo 증거가 뒷받침하는지. 미측정 성능·운영 규모·학습 효과는 추가하지 않는다.
- **포트폴리오 재사용 상태/위치**: 기존 상태 체계를 사용해 후보·검토 중·반영·보류 등을 표시하고, 재사용한 이력서/포트폴리오 위치를 연결한다. engineering decision과 재사용 상태는 구분한다.

원본 repo를 먼저 기록·수정한 뒤 Career OS의 링크와 요약을 갱신한다. 요약에는 원본 revision과 확인 시점을 남긴다. 원본 변경이나 불일치가 확인되면 요약을 오래된 상태/재검토 필요로 표시하고 원본 확인 후 갱신한다. 원본을 읽지 못하면 확인 불가로 남기며 요약으로 원본을 역으로 덮어쓰지 않는다.

Career OS 자체 개발의 decision/evidence도 `career-os` repo가 원본이다. Career OS의 기존 canonical state·ingestion·승인 경계는 유지한다. 이 기록 원칙은 자동 동기화나 새 적재 기능을 추가하라는 지시가 아니다.


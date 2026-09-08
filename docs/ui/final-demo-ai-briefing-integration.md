# 최종 시연 AI 브리핑 통합

2026-09-08 · `codex/demo-ai-briefing-placement` → `demo`

기존 demo 화면을 보존하면서 **입력 → 근거 패키지 → ViewModel/화면 → 검증된 AI 브리핑 → 엔지니어 확인**을 연결했다. 화면은 `http://127.0.0.1:3318/demo-briefing.html`이며 기존 자연어 미리보기 주소도 이 화면으로 연결된다.

## 주요 변경

- 서버 기반 AI 브리핑은 3역할 계약 v1.1을 사용한다. v1.0 저장 결과 읽기 계약은 유지한다.
- 근거 선별·설비/사건/시간 경계, SOP 의미, 승인 기록과 착수/완료/재고 미확인, 계획 추정과 실제 손실을 구분한다.
- 생성 정책과 재사용 가능 여부를 분리한다. 정확히 일치하고 현재 근거로 검증된 저장 요약만 재사용하며 GET은 생성하지 않는다.
- 검증 실패로 저장한 `fallback`을 워크플로우가 성공으로 집계하던 결함을 수정했다. 이제 상위 결과도 `partial`이다.
- 기존 엔지니어·점검·생산 화면 위치를 유지한다. 문장 단위 표시, 핵심 키워드 볼드, 상대 날짜, 한국어 단위, 내부 코드·근거 번호 제거를 적용했다.
- 검증한 문장을 초기에만 점진적으로 표시하고 마지막 커서를 남긴다. 실제 토큰 스트리밍이 아니라 검증 완료 후 표시 효과다.
- 지연·중복 요청·응답 식별 불일치·화면 전환 경쟁·재시도·10초 응답 제한을 처리한다. 미확인 정지 영향은 0분으로 바꾸지 않는다.
- 엔지니어 확인은 화면의 읽음 확인이다. 작업요청 생성, 승인, 정비 실행을 수행하지 않는다.

## 실제 경로와 검증 범위

| 경로 | 확인한 내용 | 범위 |
|---|---|---|
| 발표용 replay | 보관 입력 해시 → 실제 근거 선별/검사기 → 실제 ViewModel → 기존 화면 | 8개 입력 × 3개 관점, 24/24 |
| 전체 연결 통합 | 실제 로컬 예측 → Result/Evidence → 패키지 → 제공자 검사/재검사 → 워크플로우 → 임시 SQLite → 인증된 실제 조회 API → 화면 | 정상 24/24, 실패 응답 차단, 입력 변경 시 해당 1개만 갱신 |
| 오류 주입 | 연속 클릭, 지연, 손상, 연결 실패, 503, 재시도, 3개 화면 너비 | 16/16 |
| 팀 DB | 읽기 전용 트랜잭션, RLS 유지, 쓰기 0 | 연결·저장 출처 확인만 수행 |

전체 연결 통합에서 예측은 실제 `HeuristicPredictor`이며 외부 LLM 전송만 통제 응답으로 대체했다. 운영 모델 artifact는 현재 실행 설정에 주입되지 않았다. 팀 DB에는 `independent-logreg-v3.1` 예측 기록이 있지만 그 모델을 이번에 다시 실행한 것은 아니다. DB 조회 시점에 미래 관측이 포함되어 있었고 운영 문맥은 합성 데모 데이터였다. 조회 범위의 저장 AI 요약은 없었다.

사용자 승인 후 최신 v3.4 프롬프트로 실제 gpt-5.6-luna 호출을 확인했다. 2개 입력 모두 최초 응답 검사에서 문제를 찾아 각 1회 재생성한 뒤 최종 통과했다. 새 응답 6개 역할의 화면 포맷터 검사도 통과했다. 이는 작은 호출 점검이며 기존 A/B 성과를 갱신하지 않는다. [실제 LLM 결과와 전송 제약](final-demo-live-llm-verification.md)을 참고한다. 운영 모델·live DB부터 화면까지의 전체 연결과 배포 검증은 수행하지 않았다.

## 최종 검증

- 승인 후 실제 LLM: 최초 통과 0/2 → 재검사 후 2/2. 신규 응답의 역할별 포맷터 6/6.

- 서버 브리핑·생성 정책·평가·전달·replay·전체 연결·화면 준비 회귀: **331 passed**.
- 기존 Operations API·권한·기록 연결 회귀: **68 passed** (`APP_ENV=test`, 규칙 기반 예측 명시). 엔지니어가 작업요청을 만들고 매니저가 판단 기록을 남기는 실제 역할 순서를 테스트에 반영했다.
- 프론트 formatter/aiBrief/presentation/NaturalBriefing/기존 요청 목록: **34 passed**.
- 프론트 TypeScript·Vite 빌드 및 초기 JS 용량 검사: 통과. 기존 classic `support.js` 번들 경고는 남아 있다.
- 실제 브라우저 replay 24/24, 전체 연결 24/24와 실패 차단, 오류 주입 16/16: 통과. 실행 오류 0.
- 입력→화면 제공 코드 계약 40/40, 근거·시간·전달 32/32, 워크플로우 경계 24/24는 각 테스트 내부의 계약 수다. 화면 조합 수나 pytest 함수 수와 합산하지 않는다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=systems/backend:tests:. python3 -m pytest -p no:cacheprovider tests/test_agent* tests/test_final_briefing_demo_replay.py tests/test_operations_presentation_readiness.py tests/eval/test_agent* -q
cd systems/frontend
npm exec vitest run src/standalone/briefFormat.test.js src/standalone/aiBrief.test.js src/standalone/presentation.test.js src/features/operations/overview/NaturalBriefing.test.tsx src/features/operations/overview/MaintenanceRequestList.test.tsx
npm run build
```

## 시연 실행

저장소 의존성이 설치된 Python 환경과 프론트 의존성이 필요하다. 별도 터미널에서 실행한다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/serve_final_briefing_demo.py
```

```sh
cd systems/frontend
npm run dev -- --port 3318
```

`?view=maintenance`는 점검·작업 준비, `?view=production`은 생산 영향으로 시작한다. 역할 이름을 브리핑 본문에 덧붙이지 않는다. 근거 날짜는 실제 보관 시각을 유지하며 현재 시각에 맞춰 상대 표시만 바꾼다.

```sh
node scripts/verify_final_briefing_demo.mjs
node scripts/verify_final_briefing_stability.mjs
```

전체 연결 테스트 서버와 실행법은 [예측부터 화면까지 검증](prediction-to-screen-chain-verification.md)에 있다. replay 지원 코드는 `tests/briefing_demo_replay_support.py`에 격리했으며 운영 앱은 테스트 데이터 경로에 의존하지 않는다.

## 성과와 한계

화면의 접힌 성과 영역에는 입력→화면 제공 안정성 40/40, 내용 검사 통과 후보 반환율 20.8% → 80.8% (+60.0%p), 블라인드 에이전트 선호율 17/24 (70.8%)를 표시한다.

기존 Direct 25/120과 생성·검증 흐름 97/120은 내용 검사 통과 후보 반환율이다. 모든 표현의 정확도, 실제 현장 사용자 효용, 운영 KPI가 아니다. 자동 판단 유용성 평가는 0/120 대 18/120이며 블라인드 선호 평가는 에이전트 3개 × 사례 8개다. 현재 화면은 보관 응답 중 검증을 통과한 사례를 재생하므로 이 8개로 120개 성과를 재계산하지 않는다.

[로컬 브랜치 흡수 검토](final-demo-branch-review.md) · [브라우저 안정성](final-demo-browser-stability.md) · [실행 산출물](../eval/final-demo-evidence-20260908/)

## 원격 회귀 기대값 정리

원격 검사에서 남은 두 Closed-loop 테스트를 현재 계약에 맞췄다. 제품 구현과 권한은 변경하지 않았다.

- 정비 권고 점검 결과는 요청을 `approved`로 유지한다. 정비 후 예측 결과가 생겨도 원래 점검 요청을 암묵적으로 종료하지 않는다. 목록에서 요청 ID·원래 사건·승인 상태·담당자와 점검 결과 보존을 검증한다.
- 요청 수락의 표시 담당자는 `maintenance_technician / 보전팀`이다. 화면 구성 테스트의 기존 엔지니어 기대값을 갱신했다.
- 로컬 화면 구성 회귀는 32개 통과했다. PostgreSQL 연계 1개는 로컬 서버 부재로 건너뛰었으며 PostgreSQL 서비스가 있는 PR CI에서 실행한다. 최신 CI 결과는 PR 검사 상태를 따른다.

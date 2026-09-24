# 개발 작업 규칙

- 설계·성능·안정성에 영향을 주는 작업은 `docs/engineering/ai-assisted-engineering-workflow.md`를 먼저 따른다.
- `Human hypothesis`, `Decision required`, 최종 채택/보류/기각, `Changed belief`는 사용자 소유다. 사용자가 명시하지 않은 과거/현재 가설을 AI가 대신 만들어 확정하지 않는다.
- AI가 제안한 원인과 대안은 `AI/challenger hypotheses`로 구분하고, 가능하면 구현 전에 falsification condition과 가장 작은 판별 실험을 둔다.
- 기존 계획서의 과거 판단을 현재 생각처럼 덮어쓰지 않는다. 새 active slice와 실제 outcome부터 이 규칙을 적용한다.

# 로컬 서버와 LLM 설정

- 로컬 브리핑 서버를 실행하거나 재시작하기 전에 [실행 점검표](docs/operations/local-briefing-environment.md)를 따른다.
- `.env` 파일이 존재한다고 서버가 이를 읽는 것은 아니다. `scripts/run_local.sh`는 파일을 로딩하지만, 직접 실행하는 `uvicorn`은 `--env-file`을 명시해야 한다.
- 기존 설정 파일과 실행 프로세스에 전달된 설정을 구분한다. 모델·키가 있는 파일을 확인하지 않고 사용자에게 키가 없다고 단정하거나 재입력을 요청하지 않는다.
- 키 값이나 전체 환경변수는 로그·대화에 출력하지 않는다. 모델명, endpoint 호스트, 키 설정 여부만 확인한다.
- 픽스처 검사에 쓰는 빈 LLM 환경변수를 실제 화면 검증 서버에 재사용하지 않는다. 명령별 환경변수 설정은 다른 프로세스에 자동 반영되지 않는다.
- `.env` 로딩 전에 검증용 DB와 APP_ENV를 명시한다. 화면 검증은 격리 DB를 사용하며 운영 DB 설정을 따라가지 않는다.
- `/health` 성공은 LLM 연결 성공이 아니다. 승인된 데이터로 생성 → 저장 → 재조회를 확인하고 ProviderUnavailable과 응답 검증 실패를 구분해 보고한다.
- 현재 작업의 가정 설비 센서값·점검 메모를 OpenAI API(api.openai.com, gpt-4o-mini)로 보내 생성 검증하는 것은 사용자가 승인했다. 이 승인은 다른 데이터나 전송 대상으로 확대하지 않는다.

## Engineering loop and source of truth

중요한 설계·성능·안정성 작업은 [AI-assisted engineering workflow](docs/engineering/ai-assisted-engineering-workflow.md)에 따라 기록한다.

- Problem → Human hypothesis (실험 전 Prediction 포함) → Falsification condition → Experiment → Evidence → Human decision → Changed belief → Stop condition 순서로 한 사이클을 닫는다. 종료 조건과 실험 예산은 시작 전에 정하고 마지막에 충족 여부를 확인한다.
- 문제 선택, 실험 전 예측, 결과 해석, 최종 결정과 종료 판단은 사람이 소유한다. AI는 조사·대안·구현·테스트·집계를 지원하며, 사용자 미진술 항목은 `unrecorded` 또는 `pending human decision`으로 남긴다.
- 새 기능이 현재 대표 문제 해결에 필수인지 먼저 확인한다. 필수가 아니면 backlog로 보내고, 기존 프로젝트별 Human Gate·실행 승인·종료 기준을 유지한다.
- 코드·실험·decision/evidence의 source of truth는 해당 프로젝트의 로컬 repo다. 루트에는 상시 규칙, `docs/plans/`에는 계획, `docs/decisions/`에는 판단, `docs/evidence/`에는 실행 결과와 원시 증거 참조를 둔다. 기존 원본 경로는 유지하고 링크로 연결한다.
- Career OS는 프로젝트 경험의 인덱스·요약·역량 연결을 담당한다. 원본 링크/참조 revision, 제한을 포함한 요약, 역량 증거 연결, 포트폴리오 재사용 상태/위치만 적재한다. decision/evidence 전문이나 원시 로그를 중복 관리하지 않는다.
- 원본을 먼저 갱신한 뒤 Career OS 요약을 갱신한다. 불일치하면 repo 원본을 확인하고 요약을 오래된 상태로 표시한다.

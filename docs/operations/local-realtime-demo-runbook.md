# 로컬 실시간 Closed-loop 시연 실행·초기화

이 문서는 Windows 개발 PC에서 PostgreSQL, Backend, Generator Runtime,
`gen_data`, Live Ingestor, Maintenance Replay Dispatcher, Frontend를 한 번에
실행하고 테스트 데이터를 안전하게 초기화하는 표준 절차입니다.

## 적용 범위

이 절차가 다루는 DB는 이 저장소의 `infra/docker-compose.yml`이 소유하는 로컬
Docker PostgreSQL의 `ontology_dashboard` 데이터베이스뿐입니다. Team DB,
Mac mini, Tailscale 주소를 사용하는 원격 DB에는 적용하지 않습니다.

## 최초 1회 준비

- Docker Desktop을 실행합니다.
- 저장소 루트에 `.venv`를 준비하고 Backend/ML 의존성을 설치합니다.
- `systems/frontend`에서 `npm install`을 완료합니다.
- `gen_data` 저장소를 `ontology_dashboard`와 같은 상위 폴더에 둡니다.
  다른 위치라면 `GEN_DATA_ROOT` 환경 변수에 절대 경로를 지정합니다.
- `gen_data/canonical/dataset/dataset_manifest.json`이 존재하는지 확인합니다.

기본 폴더 배치는 다음과 같습니다.

```text
CollabCraft/
├─ ontology_dashboard/
└─ gen_data/
```

## 한 번 클릭으로 실행

저장소 루트의 `START_LOCAL_REALTIME_DEMO.cmd`를 더블클릭합니다.

실행기는 다음 순서가 모두 끝난 뒤 브라우저를 자동으로 엽니다.

1. 로컬 Docker PostgreSQL 시작 및 마이그레이션
2. 데모 계정·기준 데이터 및 Canonical V3.1 Bootstrap
3. Backend와 Generator Runtime 시작
4. `gen_data`, Live Ingestor, Maintenance Dispatcher 시작
5. 과거 168시간, 즉 10분 간격 1008틱 생성·DB 적재 확인
6. 해당 세션 Product Result 생성 확인
7. Frontend 시작 및 로그인 화면 열기

기본값은 `168시간 이력 / 720시간 Run / 60배속`입니다. 창에 `ready`와 URL이
출력되기 전에는 브라우저가 열리지 않는 것이 정상입니다. 최초 모델 준비가 필요한
PC에서는 몇 분이 걸릴 수 있습니다.

옵션을 바꾸려면 명령 프롬프트에서 같은 파일 뒤에 runner 옵션을 붙입니다.

```bat
START_LOCAL_REALTIME_DEMO.cmd --history-hours 168 --simulation-hours 720 --speed 30
```

## 정상 종료

실행기 창에서 `Ctrl+C`를 한 번 누릅니다. Backend, Frontend와 worker 프로세스는
종료되지만 PostgreSQL 데이터는 다음 확인을 위해 보존됩니다. 창을 강제로 닫은
경우에는 Task Manager에서 Python/Node 프로세스가 남지 않았는지 확인한 뒤 DB를
초기화합니다.

## 테스트 후 DB 초기화

1. 통합 실행기를 `Ctrl+C`로 먼저 종료합니다.
2. 보존할 테스트 결과가 있다면 초기화 전에 별도로 백업합니다.
3. 저장소 루트의 `RESET_LOCAL_REALTIME_DB.cmd`를 더블클릭합니다.
4. 표시된 대상이 `postgres / ontology_dashboard`인지 확인합니다.
5. 확인 문구 `RESET ontology_dashboard`를 정확히 입력합니다.

초기화 스크립트는 Compose의 `postgres` 컨테이너 안에서 다음 작업만 수행합니다.

- 기존 연결 종료
- 로컬 `ontology_dashboard` DB 삭제
- 같은 이름과 owner(`ontology`)로 빈 DB 재생성

DB URL을 입력받지 않으므로 Tailscale이나 원격 Team DB로 대상을 바꿀 수 없습니다.
Docker named volume 자체와 모델 Artifact, 실행 로그,
`data_preprocessed/local-realtime/sessions`는 삭제하지 않습니다.

초기화 직후 DB는 비어 있습니다. 다음 시연 때 `START_LOCAL_REALTIME_DEMO.cmd`를
실행하면 마이그레이션, 데모 계정, Canonical Bootstrap, 새 Live Dataset과 1008틱이
다시 생성됩니다. 즉 표준 재시연 순서는 다음과 같습니다.

```text
통합 실행기 종료
  → RESET_LOCAL_REALTIME_DB.cmd
  → START_LOCAL_REALTIME_DEMO.cmd
  → 브라우저 자동 열림
  → Closed-loop 시연
```

## 초기화 대상과 보존 대상

DB를 통째로 재생성하므로 누적된 Observation, Product Result/Evidence, 작업요청,
점검표, 비용 분석, 정비안, WorkOrder/MaintenanceAction/Event, Activity, Outbox,
Idempotency 기록과 사용자별 Dataset 선택이 함께 제거됩니다. 테이블 일부만 지워
lineage 또는 외래 키가 남는 문제를 피하기 위한 방식입니다.

다음은 DB 밖에 있으므로 보존됩니다.

- Git 소스와 설정
- `models_store/local-realtime`의 검증된 모델 Artifact
- 과거 세션 로그와 생성 파일
- `gen_data` 원본 Canonical 패키지
- Docker PostgreSQL named volume 자체

디스크 공간까지 회수하기 위해 named volume이나 세션 폴더를 지우는 작업은 이
표준 초기화에 포함하지 않습니다. 그 작업은 다른 로컬 데이터까지 영향을 줄 수
있으므로 별도 확인 후 수행합니다.

## 실패 시 확인 순서

- `Docker Desktop is not running`: Docker Desktop을 완전히 시작한 뒤 재실행합니다.
- `.venv` 오류: 저장소 루트의 Windows 가상환경과 의존성을 다시 확인합니다.
- `gen_data was not found`: 인접 폴더명 또는 `GEN_DATA_ROOT`를 확인합니다.
- Frontend dependency 오류: `systems/frontend`에서 `npm install`을 실행합니다.
- 포트 충돌: 기존 통합 실행기와 개발 서버를 종료합니다. Python runner는 사용
  가능한 다음 포트를 선택하며 실제 URL을 콘솔에 출력합니다.
- 초기화 실패: 실행기를 먼저 종료했는지, Compose `postgres`가 정상인지 확인합니다.

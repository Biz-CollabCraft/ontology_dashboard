# gen-data Runtime Overlay 운영 연결 제안서

## 목적

Backend Closed-loop에서 발생한 `maintenance.started`,
`maintenance.completed`, `maintenance.replay_requested` 이벤트를 `gen_data`
Runtime Overlay가 소비하도록 운영 경로를 연결한다. `gen_data`가 생성한
`runtime_overlay.observations.available` 이벤트는 Backend Runtime Overlay reader가
다시 읽어 후속 Runtime Diagnosis, Product Result, Evidence 승격 작업으로 넘긴다.

이 문서는 운영 DB 직접 접근 권한 없이 수행 가능한 코드/파일 계약 검증 결과와,
운영 담당자가 배포 환경에서 설정해야 하는 항목을 분리한다.

## 현재 확인된 사실

- Backend에는 Closed-loop `maintenance.*` transactional outbox 이벤트를
  `maintenance-replay-v1` JSONL inbox로 append하는 dispatcher가 있다.
- `gen_data`는 `GEN_DATA_RUNTIME_OVERLAY_EVENT_FILE`로 지정된 JSONL inbox를 읽어
  대상 설비 Runtime Overlay branch를 생성할 수 있다.
- `gen_data`는 `GEN_DATA_OUTPUT_DIR/runtime_overlay/` 아래에 overlay observation과
  `observations_available.jsonl`을 append-only로 기록한다.
- Backend reader는 `runtime_overlay.observations.available` 이벤트와 storage
  reference를 검증해 다시 읽을 수 있다.
- 로컬 smoke에서 Backend handler -> `gen_data` Runtime Overlay -> Backend reader
  흐름을 파일 기반으로 확인했다.

## 권한과 검증 경계

이번 검증은 운영 DB에 접근하지 않았다. 따라서 다음 항목은 아직 운영 검증이 아니다.

- 운영 `transactional_outbox`에서 실제 row를 claim/drain하는 동작
- 운영 DB 계정의 scope/RLS/권한
- 운영 서버 또는 컨테이너 간 shared volume mount
- 운영 `simulation_session_id`가 Closed-loop event와 `gen_data` run에 동일하게
  바인딩되는지
- overlay observation을 Product Result/Evidence로 승격하는 후속 worker

현재 결론은 "코드와 파일 계약은 연결 가능하며, 운영 DB/배포 연결은 운영 권한을 가진
담당자가 확인해야 한다"이다.

## 운영 연결 방식

Backend dispatcher가 쓰는 JSONL 파일과 `gen_data`가 읽는 JSONL 파일을 같은 경로로
고정한다.

권장 경로 예시는 다음과 같다.

```text
/var/lib/biz-collabcraft/runtime-overlay/inbox/maintenance-events.jsonl
/var/lib/biz-collabcraft/runtime-overlay/output/runtime_overlay/observations_available.jsonl
```

Backend dispatcher와 `gen_data` runtime은 같은 inbox 파일을 공유해야 한다. Backend
Runtime Overlay reader는 `gen_data` output root를 읽을 수 있어야 한다.

## Backend dispatcher 실행 설정

`ontology_dashboard` Backend process 또는 별도 worker service에 다음 환경 변수를
주입한다.

```bash
export ONTOLOGY_DASHBOARD_OUTBOX_ORGANIZATION_ID=<운영 organization_id>
export ONTOLOGY_DASHBOARD_OUTBOX_PROJECT_ID=<운영 project_id>
export ONTOLOGY_DASHBOARD_MAINTENANCE_REPLAY_EVENT_FILE=/var/lib/biz-collabcraft/runtime-overlay/inbox/maintenance-events.jsonl
```

1회 drain 검증:

```bash
PYTHONPATH=systems/backend python3 -m app.maintenance_replay_dispatcher --drain
```

상시 worker 실행:

```bash
PYTHONPATH=systems/backend python3 -m app.maintenance_replay_dispatcher
```

운영에서는 이 worker를 Compose, systemd, launchd 또는 동일 수준의 프로세스 관리
단위로 등록한다.

## gen_data runtime 실행 설정

`gen_data` runtime process에 다음 환경 변수를 주입한다.

```bash
export GEN_DATA_RUNTIME_OVERLAY_EVENT_FILE=/var/lib/biz-collabcraft/runtime-overlay/inbox/maintenance-events.jsonl
export GEN_DATA_OUTPUT_DIR=/var/lib/biz-collabcraft/runtime-overlay/output
```

실행:

```bash
.venv/bin/python run.py
```

Runtime Overlay를 소비하려면 `source_kind=simulation` run에서
`simulation_session_id`가 Backend maintenance event의 `simulation_session_id`와 같아야
한다.

예시:

```bash
curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{
    "run_id": "SOURCE-RUN-001",
    "simulation_session_id": "DEMO-001",
    "start_at": "2026-08-18T01:00:00+00:00",
    "duration_hours": 2,
    "continuous": false,
    "publish_opcua": false
  }'
```

tick:

```bash
curl -X POST http://127.0.0.1:8000/api/runs/SOURCE-RUN-001/tick
```

## 운영 담당자 확인 항목

- 운영 DB에서 `transactional_outbox` pending row가 조회되고 dispatcher가 claim할 수
  있는가
- dispatcher 실행 계정에 필요한 organization/project/workspace scope가 주입되는가
- dispatcher와 `gen_data`가 같은 inbox JSONL 파일을 공유하는가
- `gen_data` output root를 Backend Runtime Overlay reader가 읽을 수 있는가
- dispatcher 재시작 또는 at-least-once redelivery 시 동일 `event_id`가 idempotent하게
  처리되는가
- 다른 payload가 같은 `event_id`로 들어오는 conflict가 dead-letter 또는 운영 알림으로
  드러나는가
- `simulation_session_id` mismatch 이벤트가 `gen_data` run에 잘못 적용되지 않는가

## 로컬 연결 검증

로컬에서는 운영 DB 대신 임시 SQLite DB와 shared JSONL 경로를 사용해 다음 흐름을
자동 smoke로 검증한다.

```text
SQLite transactional_outbox pending rows
  -> app.maintenance_replay_dispatcher --drain
  -> shared maintenance-events.jsonl
  -> gen_data Runtime Overlay
  -> runtime_overlay/observations_available.jsonl
  -> Backend Runtime Overlay reader
```

실행:

```bash
python3 scripts/smoke_runtime_overlay_local_bridge.py \
  --gen-data-root /Users/hb/Documents/final/gen-data
```

전제:

- `gen_data` checkout이 최신 main을 반영하고 있어야 한다.
- `gen_data/.venv`가 존재하고 `requirements-lock.txt` 의존성이 설치되어 있어야 한다.
- smoke는 운영 DB에 접근하지 않고 `/private/tmp/ontology-gen-data-full-local-bridge`
  아래에 임시 SQLite DB, shared inbox, `gen_data` output을 만든다.

성공 기준:

- dispatcher drain 결과: `processed=3`
- outbox 상태: `maintenance.started`, `maintenance.completed`,
  `maintenance.replay_requested` 모두 `processed`
- shared inbox line count: `3`
- gen_data health: `/health/live=200`, `/health/ready=200`
- gen_data tick: 5회 성공
- source/canonical rows: `495`
- 대상 장비 `CNC-S01-L01-01`은 canonical source stream에서 제외
- availability event:
  `OVERLAY-AVAILABLE:MAINT-LOCAL-BRIDGE-001:post:1`
- dispatcher 재실행 drain 결과: `processed=0`

최근 로컬 검증 산출물은 임시 경로
`/private/tmp/ontology-gen-data-full-local-bridge`에 생성했다. 해당 경로는 재실행 시
초기화된다.

## 운영 smoke 절차

1. 운영과 동일한 DB 또는 staging DB에서 Closed-loop maintenance action을 하나 만든다.
2. `transactional_outbox`에 `maintenance.started`, `maintenance.completed`,
   `maintenance.replay_requested`가 pending으로 쌓였는지 확인한다.
3. dispatcher를 `--drain`으로 1회 실행한다.
4. shared inbox 파일에 세 이벤트가 순서대로 append되었는지 확인한다.
5. 같은 `simulation_session_id`로 `gen_data` simulation run을 시작한다.
6. tick을 진행한다.
7. 대상 설비가 canonical source stream에서 제외되고 overlay branch 파일이 생성되는지
   확인한다.
8. `GEN_DATA_OUTPUT_DIR/runtime_overlay/observations_available.jsonl`에
   `runtime_overlay.observations.available` 이벤트가 생성되는지 확인한다.
9. Backend reader가 availability event와 storage reference를 읽고 검증하는지 확인한다.

## 후속 구현 범위

이 연결은 Runtime Overlay observation availability까지의 운영 연결이다. 다음 항목은
별도 backend 작업으로 남는다.

- overlay observation을 Runtime Diagnosis 입력으로 수신
- 현재 Model Artifact의 history requirement를 충족했는지 판정
- Threshold/Decision Policy 적용
- post-maintenance Product Result/Evidence 생성
- Dashboard ViewModel 및 Closed-loop 후속 trigger 반영

즉, 이 문서의 범위는 Closed-loop outbox와 `gen_data` Runtime Overlay의 운영 연결이며,
Product Result/Evidence 승격은 후속 backend 수신부 작업에서 완료한다.

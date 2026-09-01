# System Operations Control Plane

## 1. 문서 상태

본 문서는 `Biz-CollabCraft/ontology_dashboard`의 시스템 운영 Control Plane에 대한 **Target Architecture(목표 아키텍처 및 구현 명세)** 기준 문서이다.

| 항목 | 상태 | 설명 |
|---|---|---|
| **문서 상태** | **Current + Target Architecture** | Phase 1~3 현행 구현과 후속 운영 기능의 목표 설계 기준 |
| **기준 브랜치/커밋** | `main` (`94ba34d7c3ca5f4f99c445bb32d2783487b52502`) | 최신 `origin/main` 기준선 |
| **역할 경계** | 제안 확정 대상 | 시스템 관리자 책임과 비운영(사용자 관리 등) 책임 엄격 분리 |
| **Backend API** | SQLite Current / PostgreSQL Target | `systems/backend/app/system_operations/` 읽기·동기화 API 구현 |
| **Frontend UI** | Current (조회 전용) | `systems/frontend/src/features/systemOperations/` 운영 자산 목록·상세 화면 |
| **운영 자산 Registry** | SQLite Current / PostgreSQL Target | 파일 기반 자산 탐색·Registry 동기화·drift 추적 구현 |
| **Mapping 편집·발행** | Current | Backend Draft revision·Diff·검증과 Generator 불변 발행 구현 및 회귀 검증 완료 |
| **Pipeline Job Control** | 일부 기존 개별 기능 존재, 통합 미구현 | 공통 Job 추적 인터페이스 Target 정의 |
| **Generator·Backend 로그 통합** | 미구현 (Target) | E2E Timeline 통합 추적 설계 |
| **Model Artifact 자동 `latest.json`** | **현재 구현됨 (Current)** | Generator Training 성공 시 `latest.json` 자동 갱신 |
| **운영 선택 `selected.json`** | 미구현 (Target) | 시스템 관리자 명시적 선택 포인터 (Phase 8 검토 대상) |

```text
Baseline commit: 94ba34d7c3ca5f4f99c445bb32d2783487b52502
```

---

## 2. 목적

본 문서의 목적은 시스템 관리자 계정, 운영 자산(Operational Assets), 파이프라인(Pipeline Job), 시스템 로그 및 감사 감독 기능의 책임 경계와 단계별 구현 계약을 구체화하는 데 있다.

본 문서는 후속 Backend, Frontend, Contract 작업자가 동일한 책임 경계와 용어를 사용하도록 다음 사항을 정본(Source of Truth)으로 확정한다:
- 시스템 관리자의 명확한 책임과 비운영 업무의 엄격한 배제
- 운영 자산의 정의 및 버전·검증·발행·활성화 생명주기(Lifecycle)
- Generator, Backend, Control Plane 간의 단방향 책임 경계
- Pipeline Job 실행, 상태 전이 및 공통 추적 기준
- Generator·Backend 로그 및 감사 추적 표준
- Backend API 및 Frontend UI의 목표 정보 구조(IA)
- Model Artifact 포인터 정책 (`latest.json` vs `selected.json`)
- 단계별 10대 구현 로드맵 및 미결정 사항 목록

---

## 3. 현재 시스템 기준

현재 `main` 저장소에 존재하는 실제 코드 구조와 향후 구현될 시스템 운영 Control Plane 목표 상태의 기준선은 다음과 같다.

| 영역 | 현재 경로 | 현재 책임 | 시스템 운영 UI 연동 상태 |
|---|---|---|---|
| **Generator** | `systems/generator/` | Extraction, Preprocessing, Feature, Training, Runtime Pipeline 실행 | 통합 관리 UI 없음 (CLI/Internal API 중심) |
| **Backend** | `systems/backend/app/` | Prediction 수신, 멱등 Inbox, 이상 판정, 결과·Report·Dashboard 제공 | 통합 운영 로그 UI 없음 |
| **Identity** | `systems/backend/app/identity/` | 현재 사용자 인증 및 도메인 역할(Role) 관리 | 시스템 관리자 전용 운영 경계 미구현 |
| **기존 Admin UI** | `systems/frontend/src/features/admin/` | 별도의 사용자·역할·승인·감사 기능 | 본 Control Plane 범위 밖이며 시스템 운영 화면으로 확장하지 않음 |
| **MVP System UI** | `systems/frontend/src/features/mvp/system/` | 제한적인 런타임 실행 이력/상태 조회 | 운영 자산 관리 및 Job 제어 기능 없음 |
| **Governance** | `systems/backend/app/governance/` | Project, Dataset, Projection, Lineage 관리 | 시스템 운영 자산 관리와 분리된 비즈니스 거버넌스 |
| **Contracts** | `contracts/` | JSON Schema, Example, Vector 정본 | Control Plane API 전용 계약은 미구현 |

---

## 4. 시스템 관리자 책임

시스템 관리자는 시스템 실행 및 파이프라인 동작에 사용되는 **운영 자산과 시스템 상태를 감독하는 운영 전용 주체**이다.

### 4.1 핵심 원칙
1. 시스템 관리자는 Generator와 Backend가 남긴 구조화 상태와 로그를 바탕으로 작업 흐름 및 오류를 추적하고 감독한다.
2. 시스템 관리자는 공식적으로 검증된 절차를 통해서만 새로운 운영 자산 버전을 발행(Publish) 및 활성화(Activate)한다.
3. 시스템 관리자는 장시간 소요되는 Pipeline 작업을 Job 단위로 실행, 추적, 재시도, 복구한다.
4. 시스템 관리자는 이미 발행된 불변(Immutable) 자산을 직접 임의 수정하거나 삭제하지 않는다.

### 4.2 책임 대상
- **Static Mapping**: 센서 프로토콜 필드 매핑 정의
- **Preprocessing Plan**: 관측 데이터 전처리 및 역할 판정 계획 (`pp-{uuid}`)
- **Feature Schema & Label Schema**: 피처 명세 및 레이블 생성 규칙
- **History Requirement**: 설비별 런타임 추론 준비를 위한 최소 윈도우 요구조건
- **Training Config**: 모델 학습 하이퍼파라미터 및 데이터셋 분할 설정
- **Dataset Artifact**: 정규화된 Observation 및 Failure 정본 데이터셋
- **Feature Dataset Bundle**: 5개 불변 파일로 구성된 피처 번들
- **Model Artifact**: 학습 완료된 모델 바이너리 및 메트릭 패키지
- **Active Model Set**: 런타임 추론에 등록된 활성 모델 목록
- **Protocol Contract & Dataset Contract**: 정본 인터페이스 계약
- **Pipeline Checkpoint**: 스트리밍 추출 및 처리 체크포인트
- **Pipeline Job**: 장시간 배치 및 재구축 작업
- **Generator·Backend 구조화 로그**: 다차원 메타데이터 기반 운영 로그

---

## 5. 책임 범위 밖 (금지 사항)

시스템 관리자 계정 및 Control Plane의 책임 범위에서 다음 비운영성 업무 및 위험 행위를 명시적으로 배제하고 금지한다.

```text
[배제 대상 업무]
1. 일반 사용자 가입 승인 및 계정 관리
2. 일반 사용자 역할(Role) 및 권한 변경
3. 조직(Organization) 및 Workspace scope 관리
4. 비밀번호 및 일반 인증 정책 관리
5. 일반 Dashboard 사용자 개인화 설정
6. Tenant 관리자 UI 제공

[금지 행위]
1. 서버 전체 파일 시스템의 임의 탐색 (Root Directory Escape)
2. 허용되지 않은 임의 경로의 파일 생성 및 편집
3. 이미 발행(Published)된 불변 Artifact의 직접 수정 및 덮어쓰기
4. 운영에 참조 중인 운영 파일의 강제 삭제
5. 원본 대용량 센서 데이터의 무제한 화면 노출
6. 비밀번호, 토큰, API Key, Cookie 등 민감 보안 정보의 로그 노출
```

시스템 관리자 계정은 일반 사용자 UI를 통한 가입이나 권한 부여 대상이 아니며, 배포(Bootstrap), 환경 설정 또는 승인된 Identity Provider(IdP)의 사전 구성을 통해서만 프로비저닝된다.

### 5.1 접근 경계

본 문서가 상정하는 시스템 관리자는 일반 사용자 관리 역할의 확장이 아니라 사전에 구성된 독립 운영 계정이다. 초기 구현에서는 다음 권한 능력을 기준으로 Backend와 Frontend 접근을 분리한다.

```text
system.operations.access
system.assets.read
system.assets.create_version
system.assets.validate
system.assets.publish
system.assets.activate
system.assets.archive
system.jobs.read
system.jobs.execute
system.jobs.retry
system.jobs.cancel
system.logs.read
system.logs.export
system.health.read
system.audit.read
```

위 권한을 일반 사용자 관리 화면에서 부여·제거하거나 permission override로 우회 부여하는 기능은 목표 범위에 포함하지 않는다. 실제 인증 및 프로비저닝 방식은 Phase 1 진입 전에 별도 결정한다.

---

## 6. 운영 자산 분류

시스템 운영에 관여하는 자산과 운영 기록은 다음과 같이 9개 분류로 관리한다.

| 분류 | 자산명 | Producer | 주요 Consumer | 현재 계약 상태 |
|---|---|---|---|---|
| **입력 계약** | Protocol Contract, Dataset Contract | Contract 관리 절차 | `gen_data`, Generator | Current |
| **변환 계약** | Static Mapping, Preprocessing Plan | Generator 운영 절차 | Extraction, Preprocessing | Current (Mapping Draft·Diff·검증·불변 발행 포함) |
| **학습 계약** | Feature / Label / History Schema | Feature Pipeline | Training, Runtime Feature | Current |
| **학습 설정** | Training Config | 시스템 운영 절차 | Training | Current |
| **중간 산출물** | Canonical Dataset, Feature Dataset Bundle | Generator | Feature, Training | Current |
| **모델 산출물** | Model Artifact | Training | Runtime Prediction | Current |
| **실행 선택** | Active Model Set | Generator 운영 절차 | Runtime Prediction | Current (`selected.json`은 Planned) |
| **결과 추적** | Prediction Batch, Product Result, Evidence | Generator / Backend | Backend, Dashboard | Current |
| **운영 상태** | Job, Checkpoint, Log, Audit | Generator / Backend | 시스템 관리자 | Planned (통합 Registry) |

---

## 7. 운영 자산 Lifecycle

모든 항목에 동일한 상태 머신을 강제하지 않는다. 사람이 새 버전을 작성·검증하는 관리 자산, Pipeline이 생성하는 불변 산출물, 실행 중에 누적되는 운영 기록을 구분한다.

### 7.1 관리 자산 Lifecycle

Static Mapping, Preprocessing Plan, Schema, Training Config처럼 새 버전을 작성하고 운영에 적용하는 자산은 다음 Lifecycle을 목표로 한다.

```text
[Draft]
   ↓ (검증 요청)
[Validating] ────(검증 실패)───→ [Validation Failed]
   ↓ (검증 통과)
[Validated]
   ↓ (발행 요청)
[Publishing] ────(발행 실패)───→ [Publish Failed]
   ↓ (원자적 발행 완료)
[Published] (불변 확정)
   ↓ (활성화 요청)
[Activating] ───(활성화 실패)──→ [Activation Failed]
   ↓ (활성화 완료)
[Active] (운영 파이프라인 반영)
   ↓ (신규 버전 활성화)
[Superseded] (이전 활성 버전)
   ↓ (보관 정책에 따름)
[Archived]
```

### 7.2 생성 산출물 Lifecycle

Dataset Artifact, Feature Dataset Bundle, Model Artifact처럼 Pipeline이 생성하는 산출물은 사용자 편집용 `draft`를 거치지 않는다.

```text
[Staging]
   ↓ (파일·Schema·Checksum 검증)
[Validated]
   ↓ (원자적 디렉터리 발행)
[Published]
   ↓ (소비 포인터 또는 Registry 선택)
[Referenced / Active]
   ↓
[Superseded / Archived]
```

생성 산출물은 실패 시 `publish_failed` 상태와 staging 진단 정보를 남길 수 있지만, 검증되지 않은 staging 파일을 발행본으로 노출하지 않는다.

### 7.3 운영 기록 Lifecycle

Job, Checkpoint, Log, Audit은 버전 발행 자산이 아니다. 각 도메인의 append-only 또는 상태 전이 계약을 유지하고, Control Plane은 이를 조회·연결할 뿐 임의로 자산 Lifecycle에 편입하지 않는다.

### 7.4 Lifecycle 불변식 (Invariants)
1. **발행본 수정 금지**: `published` 상태에 도달한 자산 버전은 어떠한 경우에도 수정할 수 없다.
2. **발행본 삭제 금지**: 발행된 자산은 물리 삭제할 수 없으며, 상태 전이를 통해서만 관리된다.
3. **신규 버전 초안 생성**: 변경이 필요한 경우 항상 새로운 버전의 `draft`를 생성하여 절차를 시작한다.
4. **발행과 활성화의 분리**: 자산의 물리적 발행(`published`)과 실제 런타임 주입(`active`)은 별개의 독립적인 단계로 분리된다.
5. **의존성 사전 검증**: 자산 버전을 활성화하기 전, 하위 파이프라인 및 상위 계약과의 의존성과 영향 범위를 자동으로 확인한다.
6. **Checksum 무결성 검증**: 실제 파일의 SHA-256 Checksum과 Registry에 기록된 Checksum이 정확히 일치해야 한다.
7. **참조 자산 보호**: 다른 운영 자산이나 활성 파이프라인에서 참조 중인 자산은 보관(`archived`) 처리할 수 없다.
8. **버전 재발행 금지**: 동일한 자산 식별자와 버전 번호로의 중복 발행을 엄격히 차단한다.
9. **단계별 원자성**: Artifact 디렉터리 발행과 포인터(`latest.json` 등) 교체는 각각 원자적으로 수행한다. 두 단계를 하나의 파일시스템 트랜잭션으로 간주하지 않는다.
10. **부분 실패 보존**: Artifact 발행 후 포인터 갱신이 실패하면 발행된 불변 Artifact를 삭제하지 않고 `published=true`, `pointer_updated=false` 상태와 복구 가능한 오류를 기록한다.
11. **Fail-Closed 유지**: 검증·발행·활성화 실패 시 기존의 유효한 발행본과 런타임 활성 상태를 온전히 보존한다.

---

## 8. Generator·Backend 책임 경계

시스템 운영 Control Plane은 Generator와 Backend의 고유 책임을 침범하지 않으며, 다음과 같은 단방향 흐름과 감독 역할을 유지한다.

```text
Biz-CollabCraft/gen_data (Source Data Producer)
└─ SensorRecord v2 기반 append-only protocol 파일 생성
        ↓
systems/generator (ML/Data Pipeline Engine)
├─ gen_data 입력 소비 및 Protocol Extraction
├─ Preprocessing (Observation 분석 → Preprocessing Plan 불변 발행)
├─ Feature Engineering (Feature Dataset Bundle 불변 발행)
├─ Model Training (Model Artifact 불변 발행 및 latest.json 갱신)
├─ Runtime Feature 계산 및 Model Inference (raw score 추론)
└─ Prediction Result Batch 구성 및 Backend 송신
        ↓ (HTTP POST /internal/prediction-results)
systems/backend (Product Application & Decision Host)
├─ Prediction Result Batch 수신 및 Inbox 멱등 저장
├─ Threshold & Decision Policy 적용을 통한 이상 판정
├─ 센서값 및 설비 Metadata 결합
├─ Product Result Artifact, Evidence, Report 생성
└─ Dashboard API 제공 및 운영 로그 기록
        ▲                               ▲
        │ (상태 및 메트릭 조회)           │ (로그 및 결과 조회)
        └───────────────┬───────────────┘
                        │
┌───────────────────────┴────────────────────────┐
│        System Operations Control Plane        │
│                                               │
│  - Generator 운영 자산(Mapping/Plan/Model) 감독  │
│  - 장시간 Pipeline Job(Rebuild/Replay) 추적     │
│  - Generator·Backend 분산 로그 상관관계 분석      │
│  - 운영 감사(Audit Trail) 기록 및 조회          │
│  * 비즈니스 판정, 모델 계산, 데이터 수정은 미수행 *    │
└───────────────────────────────────────────────┘
```

시스템 운영 Control Plane은 Generator의 수치 계산이나 Backend의 제품 진단 판정을 재구현(Re-implement)하거나 대행하지 않는다.

---

## 9. Pipeline Job 관리

장시간 수행되는 배치 처리 및 파이프라인 재구축 작업은 비동기 Job 계약을 통해 관리된다.

### 9.1 목표 Job 유형
- `extraction`: 관측/고장 데이터 추출 작업
- `preprocessing`: 데이터셋 전처리 및 계획 수립
- `feature_build`: 피처 엔지니어링 및 번들 생성
- `training`: 모델 학습 및 평가
- `artifact_publish`: 모델 아티팩트 검증 및 정식 발행
- `asset_activation`: 신규 운영 자산 활성화
- `runtime_prediction`: 런타임 일괄 추론 실행
- `backend_delivery`: 백엔드 결과 전송 및 재전송
- `rebuild`: 매핑/피처 변경에 따른 전체 파이프라인 재구축
- `rollback`: 이전 자산/모델 버전으로의 롤백

### 9.2 목표 Job 상태
```text
[queued] → [running] ──(체크포인트)──→ [checkpointed]
               ├───────(성공)────────→ [succeeded]
               ├───────(실패)────────→ [failed]
               ├───────(취소)────────→ [cancelled]
               └───────(미지원)───────→ [not_implemented]
```

### 9.3 공통 추적 필드 규격
```json
{
  "job_id": "job-ext-20260911-001",
  "job_type": "extraction",
  "request_id": "req-8f12a3bc",
  "run_id": "run-44b2-910a",
  "status": "running",
  "input_asset_versions": {
    "mapping_id": "map-sensor-v1.2",
    "dataset_version": "ds-v3.1"
  },
  "output_asset_versions": {
    "observation_dataset": "obs-v3.1-001"
  },
  "checkpoint": {
    "last_source_offset": 1048576,
    "records_processed": 50000
  },
  "attempt_count": 1,
  "retryable": true,
  "error_code": null,
  "error_message": null,
  "started_at": "2026-09-11T09:00:00Z",
  "completed_at": null,
  "actor": "system-operator:<subject-id>"
}
```

---

## 10. 로그·추적·감사

### 10.1 다차원 로그 조회 기준
시스템 운영자는 다음 차원을 조합하여 분산 로그를 정밀 필터링한다:
- `service`: `generator`, `backend`, `control-plane`
- `domain`: `extraction`, `preprocessing`, `feature`, `training`, `runtime_pipeline`, `inbox`, `diagnosis`, `report`
- `severity`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- `error_code`: 표준 비즈니스/시스템 오류 코드
- `request_id` / `run_id` / `job_id`: 실행 단위 상관관계 식별자
- `asset_id` / `model_id`: 자산 단위 추적 식별자
- `event_id`: 이벤트 단위 추적 식별자
- `timestamp_range`: 시작/종료 조회 기간

### 10.2 E2E Timeline 상관관계 추적
Control Plane은 단일 원본 센서 데이터로부터 최종 대시보드 알림까지의 전체 흐름을 일관된 타임라인으로 추적할 수 있어야 한다:

```text
Source File / Record
  → Extraction (Observations & Checkpoint)
  → Preprocessing Dataset (Plan: pp-{uuid})
  → Feature Bundle (5-file Bundle)
  → Training Execution (Run ID)
  → Model Artifact Publish (Checksum)
  → Runtime Prediction (Raw Score)
  → Backend Inbox Delivery (Idempotency Key)
  → Product Result Artifact Generation
  → Evidence & Report Assembly
  → Dashboard Anomaly Alert
```

### 10.3 로그 보안 및 마스킹 원칙
1. 비밀번호, 인증 토큰, 세션 쿠키, API Key는 어떠한 로그에도 기록하거나 화면에 노출하지 않는다.
2. 기가바이트 단위의 원본 센서 스트림 전체를 로그에 덤프하지 않으며, URI, Checksum, 레코드 개수, 타임스탬프 범위를 중심으로 추적한다.
3. 상세 Stack Trace 조회 및 로그 파일 원본 Export는 시스템 관리자 전용 권한으로 엄격히 제한한다.
4. 모든 로그 Export 및 원본 조회 행위는 확정된 보존 정책에 따라 감사 로그에 기록된다.

### 10.4 감사 로그 (Audit Trail) 기록 대상
- 자산 조회, 다운로드 및 초안(Draft) 생성
- 자산 파일 첨부, 유효성 검증(Validation) 및 정식 발행(Publish)
- 활성 버전 지정(Activation) 및 롤백(Rollback)
- Pipeline Job 실행, 재시도 및 지원되는 Job의 취소
- Model Artifact 선택(`selected.json`) 변경
- 운영 로그 대량 Export
- 무결성 위반 및 보안 접근 거부(403/401) 이벤트

---

## 11. Backend API 현행 및 목표 구조

시스템 운영 기능은 기존 도메인 API와 엄격히 분리된 `systems/backend/app/system_operations/` 패키지에 구축된다.

### 11.1 목표 패키지 구조
```text
systems/backend/app/system_operations/
├── __init__.py
├── system_operation_router.py      # REST 엔드포인트 라우팅
├── system_operation_service.py     # 통합 오케스트레이션 서비스
├── system_operation_schema.py      # Pydantic DTO 스키마
├── system_operation_exception.py   # 전용 도메인 예외 정의
├── asset_registry_service.py       # 운영 자산 메타데이터 레지스트리
├── job_query_service.py            # 파이프라인 Job 조회 및 제어
├── log_query_service.py            # 다차원 로그 집계 및 조회
└── ports.py                        # 파일 시스템 및 외부 시스템 포트 인터페이스
```

### 11.2 REST API 엔드포인트
| 상태 | HTTP Method | API Path | 설명 |
|---|---|---|---|
| Current | `GET` | `/api/system/assets` | 운영 자산 목록 조회 및 필터 |
| Current | `GET` | `/api/system/assets/reconciliation/latest` | 마지막 Registry 동기화 결과 조회 |
| Current | `GET` | `/api/system/assets/{asset_id}` | 자산 상세 및 버전 이력 조회 |
| Current | `GET` | `/api/system/assets/{asset_id}/versions` | 자산 버전 이력 조회 |
| Current | `GET`, `POST` | `/api/system/mapping-drafts` | Mapping Draft 목록 조회 및 신규 초안 생성 |
| Current | `GET`, `PUT` | `/api/system/mapping-drafts/{draft_id}` | Mapping Draft 조회 및 revision 기반 수정 |
| Current | `GET` | `/api/system/mapping-drafts/{draft_id}/diff` | 기준 버전과 Draft 간 차이 조회 |
| Current | `POST` | `/api/system/mapping-drafts/{draft_id}/validate` | Generator의 실제 Mapping 계약 검증 수행 |
| Current | `POST` | `/api/system/mapping-drafts/{draft_id}/publish` | 검증된 동일 revision을 새 불변 버전으로 발행 |
| Implemented / Verification pending | `POST` | `/api/system/jobs/rebuild` | 발행 Mapping 기반 전체 source Replay Job 생성 |
| Implemented / Verification pending | `GET` | `/api/system/jobs` | Pipeline Job 목록 및 상태 조회 |
| Implemented / Verification pending | `GET` | `/api/system/jobs/{job_id}` | Job 진행·checkpoint·결과·오류 조회 |
| Implemented / Verification pending | `POST` | `/api/system/jobs/{job_id}/cancel` | queued Job 취소 또는 running Job 취소 요청 |
| Target | `GET` | `/api/system/access` | 현재 세션의 시스템 관리자 권한 확인 |
| Target | `GET` | `/api/system/overview` | 시스템 전체 운영 지표 요약 |
| Target | `GET` | `/api/system/health` | Generator 및 Backend 세부 서비스 헬스체크 |
| Target | `GET` | `/api/system/assets/{asset_id}/dependencies` | 자산 간 상/하위 의존성 및 영향 범위 조회 |
| Target | `GET` | `/api/system/jobs` | Pipeline Job 목록 조회 |
| Target | `GET` | `/api/system/jobs/{job_id}` | 특정 Job의 실행 진행률, 체크포인트 및 로그 조회 |
| Target | `GET` | `/api/system/logs` | Generator·Backend 통합 다차원 로그 조회 |
| Target | `GET` | `/api/system/audit` | 시스템 운영 감사 로그 조회 |

> **주의**: Static Mapping의 Draft 편집·검증·불변 발행은 Current이며, Extraction rebuild/replay Job은 구현 후 전체 회귀 검증 대기 상태다. Mapping 변경에 따른 Preprocessing·Feature·Training 자동 재구축, 일반 자산 편집 및 모델 선택은 후속 Target이다.

---

## 12. Frontend UI 현행 및 목표 구조

시스템 운영 UI는 기존 일반 사용자 Admin 화면과 분리된 독립된 피처 모듈로 구성된다.

### 12.1 목표 디렉터리 구조
```text
systems/frontend/src/features/systemOperations/
├── SystemOperationsApp.tsx          # 서브 라우터 및 Shell
├── SystemOverviewPage.tsx           # 시스템 종합 대시보드
├── OperationalAssetsPage.tsx        # 운영 자산 목록 및 필터링
├── OperationalAssetDetailPage.tsx   # 자산 버전, 의존성, Checksum 검증 상세
├── OperationJobsPage.tsx            # Pipeline Job 모니터링 및 제어
├── SystemLogsPage.tsx               # 다차원 통합 로그 뷰어
├── SystemHealthPage.tsx             # 시스템 헬스 및 서비스 상태
├── SystemAuditPage.tsx              # 운영 감사 로그 뷰어
├── api/                             # system-operations 전용 API 클라이언트
├── components/                      # 자산 상태 뱃지, 로그 뷰어, 타임라인 등 공통 컴포넌트
└── system-operations.css            # 전용 스타일시트
```

### 12.2 라우팅 경로
- Current: `/system/operations/assets` — 운영 자산 목록 및 필터
- Current: `/system/operations/assets/:assetId` — 자산 상세, 버전 및 목록형 의존성
- Current: `/system/operations/mappings/drafts` — Static Mapping Draft·검증·불변 발행
- Implemented / Verification pending: `/system/operations/jobs` — Mapping Rebuild/Replay Job 생성·조회
- Implemented / Verification pending: `/system/operations/jobs/:jobId` — 진행 상태·checkpoint·결과·오류 및 취소 요청
- Target: `/system/operations` — 시스템 종합 개요
- Target: `/system/operations/jobs` — Pipeline Job 실행 상태
- Target: `/system/operations/logs` — 통합 시스템 로그
- Target: `/system/operations/health` — 서비스 상태
- Target: `/system/operations/audit` — 운영 감사 기록

기존 사용자 관리 화면(`src/features/admin/`)을 재사용하거나 혼합하지 않으며, 공통 컴포넌트 라이브러리(Foundry 등)만 공유한다.

---

## 13. Model Artifact 포인터 정책

### 13.1 현재 기본 정책: `latest.json` (Current)
- **정의**: Generator Training 성공 시 가장 최근에 정상 발행된 Model Artifact를 가리키는 자동 포인터 파일.
- **소유권**: `systems/generator` 학습 파이프라인이 생성 및 갱신을 전담.
- **불변식**: 시스템 관리자나 외부 API가 `latest.json`을 직접 임의 수정하지 않는다.

### 13.2 운영 선택 목표 정책: `selected.json` (Target / Proposed)
- **정의**: 시스템 관리자가 모델 성능 평가 및 검증을 거친 후 명시적으로 선택한 특정 운영 모델 버전 포인터.
- **소비 우선순위 (Resolution Rule)**:
  ```text
  1. 유효하고 검증된 selected.json 포인터가 존재하면 → selected 모델 사용
  2. selected.json이 없거나 비활성 상태이면 → latest.json 모델 사용 (기본값)
  ```
- **불변식**:
  - `selected.json` 도입은 Phase 8 후속 과제이며 현재 구현으로 단정하지 않는다.
  - 선택 및 롤백 작업 시 대상 Model Artifact의 Checksum 재검증과 감사 기록이 필수적으로 수반된다.

---

## 14. 보안 및 무결성 원칙

Control Plane은 시스템의 신뢰성과 무결성을 보호하기 위해 다음 원칙을 강제한다:

1. **Root 디렉터리 격리**: 모든 자산 경로와 작업 파일은 사전에 정의된 허용 Root 디렉터리 내부로 제한되며, 상위 경로 탐색(`../`) 및 절대 경로 주입을 원천 차단한다.
2. **Schema & Checksum 2중 검증**: 모든 자산 파일은 정본 JSON Schema 검증과 SHA-256 Checksum 검증을 모두 통과해야 한다.
3. **Fail-Closed 정책**: 무결성 검증 실패, 스키마 불일치 또는 Checksum 오류 발생 시 시스템은 작업을 즉시 중단하고 안전 상태를 유지한다.
4. **원자적 임시 발행**: 파일 쓰기는 임시 디렉터리(`.tmp`)에서 완료 및 검증된 후, 단일 원자적 이름 변경(Atomic Rename)으로 정식 위치에 배치된다.
5. **동시성 제어**: 동일한 자산 또는 동일한 버전에 대한 동시 발행 시도는 상호 배제(Mutual Exclusion Lock)로 방어한다.
6. **장시간 작업의 멱등성**: 모든 비동기 Job은 고유한 `request_id`와 `run_id`를 기반으로 멱등성을 보장한다.
7. **최소 권한 접근**: 원본 센서 데이터와 중간 산출물에 대한 물리적 파일 시스템 접근 권한은 최소화된다.

---

## 15. 단계별 구현 계획 (Phased Roadmap)

| Phase | 단계명 | 핵심 산출물 및 구현 범위 | 선행 의존성 |
|---|---|---|---|
| **Phase 1** | 접근 경계 & 골격 | **Current** — `system_operator` 및 `system.assets.read` 독립 접근 경계 | - |
| **Phase 2** | 자산 Registry 기반 | **Current (SQLite)** — 운영 자산 Metadata Registry, 파일 기반 탐색·등록, 읽기 전용 API. PostgreSQL adapter는 후속 필요 | Phase 1 |
| **Phase 3** | 자산 조회 UI | **Current** — 자산별 버전, Checksum, 목록형 의존성, 런타임 사용 상태 조회 UI | Phase 2 |
| **Phase 4** | Mapping 버전 관리 | **Current** — Static Mapping 신규 버전 Draft, Diff, 실제 Generator 검증 및 불변 발행 | Phase 3 |
| **Phase 5** | Rebuild/Replay Job | **Implemented / Verification pending (SQLite)** — Mapping checksum별 Replay checkpoint, Extraction 재처리, 영속 Job worker 및 성공 후 원자적 활성화 | Phase 4 |
| **Phase 6** | 하위 영향 분석 | Mapping 변경 시 Preprocessing → Feature → Training 하위 데이터셋 영향 분석 및 선택적 재학습 | Phase 5 |
| **Phase 7** | 계약/설정 확장 | Preprocessing Plan, Feature Schema, Training Config 관리 기능 확장 | Phase 6 |
| **Phase 8** | 모델 운영 선택 | Model Artifact 및 Active Model Set 감독, `selected.json` 포인터 및 롤백 제어 | Phase 7 |
| **Phase 9** | 감사 & 로그 고도화 | 운영 감사 로그(Audit Trail) 정밀 추적, 오류 복구 가이드, 안전한 로그 Export | Phase 8 |
| **Phase 10** | E2E 통합 전환 | Sensor Source부터 Dashboard Alert까지 E2E Timeline 완성 및 정식 운영 전환 | Phase 9 |

---

## 16. 현재 상태와 목표 상태

| 기능 항목 | 현재 상태 (Current) | 목표 상태 (Target) | 구현 Phase |
|---|---|---|:---:|
| **Generator Pipeline** | 개별 CLI/API 기반 기능 존재 | 통합 Control Plane 운영 감독 | Phase 1~6 |
| **Backend 처리 로그** | 도메인별 개별 로그 출력 | 다차원 필터링 및 E2E Timeline 통합 | Phase 1, 9, 10 |
| **시스템 관리자 화면** | 없음 | 독립된 System Operations Control Plane UI | Phase 1 |
| **운영 자산 Registry** | SQLite 기반 구현 | PostgreSQL을 포함한 중앙화된 메타데이터 레지스트리 | Phase 2 |
| **운영 자산 조회 UI** | 목록·상세·버전·목록형 의존성 조회 구현 | 대규모 관계 그래프 및 운영 제어 확장 | Phase 3 |
| **Mapping 버전 편집** | Current | 버전 기반 초안 생성, 검증, 불변 발행 | Phase 4 |
| **Mapping Rebuild** | Implemented / Verification pending (SQLite Job Registry) | PostgreSQL adapter 및 고급 승인·취소 정책 확장 | Phase 5 |
| **하위 영향 분석** | 없음 | Dataset → Feature → Model 전파 추적 | Phase 6 |
| **Model 운영 선택** | `latest.json` 자동 갱신만 지원 | `selected.json` 명시적 선택 및 롤백 | Phase 8 |
| **통합 운영 감사** | 개별 로그 기록 | 자산·Job·조작 전수 감사(Audit Trail) | Phase 9 |

---

## 17. 완료 조건 (Definition of Done)

본 문서 작업의 완료 기준은 다음과 같다:
- [x] `docs/system-operations-control-plane.md` 상세 기준 문서가 신규 작성됨
- [x] 문서 첫 부분에 기준 `main` 커밋 SHA가 명시됨
- [x] 시스템 관리자 책임이 운영 자산, Pipeline Job, 로그 감독으로 한정됨
- [x] 사용자 가입, 역할 부여, 조직 관리 등 비운영 책임이 철저히 배제됨
- [x] 현재 코드(Current)와 목표 구조(Target)가 명확히 분리됨
- [x] 9개 자산·운영 기록 분류와 유형별 Lifecycle이 정의됨
- [x] Generator, Backend, Control Plane의 단방향 책임 분계선이 정의됨
- [x] Pipeline Job 상태 전이, 공통 필드 및 다차원 로그/감사 추적 기준이 수립됨
- [x] Backend API(`systems/backend/app/system_operations/`) 및 Frontend UI(`src/features/systemOperations/`)의 Current/Target 범위가 분리됨
- [x] Model Artifact 포인터 정책(`latest.json` vs `selected.json`)이 명문화됨
- [x] 10단계 구현 로드맵 및 선행 의존성이 수립됨
- [x] 미결정 사항이 별도 의사결정 목록으로 분리됨
- [x] `docs/architecture.md` 및 `docs/README.md`에 상위 원칙과 참조가 반영됨
- [x] 코드, Schema, Workflow 파일의 변경이 0건임을 보장함

---

## 18. 미결정 사항 (Decisions Pending)

다음 항목들은 현재 확정 구현으로 다루지 않으며, 후속 Phase 진입 전 공식적인 기술 의사결정을 통해 확정한다.

| 항목 | 상태 | 담당 | 선행 필요 Phase | 결정 기록 참조 |
|---|---|---|:---:|---|
| **시스템 관리자 인증 방식** (mTLS, 전용 IdP, 토큰) | Decision Required | DevOps / Security | Phase 1 | ADR-TBD-01 |
| **운영 로그 보존 기간** (Hot/Warm/Cold Storage) | Decision Required | Infra Team | Phase 1 | ADR-TBD-02 |
| **로그 Export 형식 및 최대 다운로드 용량 제한** | Decision Required | Backend Team | Phase 1 | ADR-TBD-03 |
| **운영 자산 Registry의 멀티 테넌트/Project Scope 지원 여부** | Decision Required | Architecture Team | Phase 2 | ADR-TBD-04 |
| **Draft 자산의 자동 정리(TTL) 만료 기간** | Decision Required | System Operations | Phase 4 | ADR-TBD-05 |
| **고위험 작업(Rebuild, Rollback) 승인 절차(2-man rule)** | Decision Required | Product Owner | Phase 5 | ADR-TBD-06 |
| **Pipeline Job 취소 가능 시점 및 롤백 정책** | Decision Required | Generator Team | Phase 5 | ADR-TBD-07 |
| **Mapping 변경 시 과거 Replay 데이터 전체 Rebuild 범위** | Decision Required | Data Team | Phase 5 | ADR-TBD-08 |
| **`selected.json` 도입 여부 및 우선순위 정책 확정** | Decision Required | ML Team | Phase 8 | ADR-TBD-09 |
| **운영 선택 모델의 만료(Expiration) 정책** | Decision Required | ML Team | Phase 8 | ADR-TBD-10 |
| **과거 Model Artifact의 보관(Archive) 및 영구 삭제 주기** | Decision Required | Infra Team | Phase 8 | ADR-TBD-11 |
| **Control Plane을 통한 원본 파일 다운로드 허용 범위** | Decision Required | Security Team | Phase 9 | ADR-TBD-12 |

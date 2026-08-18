# AI 코드 리뷰 컨텍스트 — ontology_dashboard

이 문서는 `Biz-CollabCraft/ontology_dashboard`의 자동 코드 리뷰가 단순 diff 요약이 아니라
프로젝트의 실제 제품·아키텍처 계약을 기준으로 회귀를 판단하도록 하기 위한 리뷰 계약이다.

자동 리뷰는 **PR head가 아니라 base branch에 존재하는 이 문서**를 우선 신뢰 기준으로 사용한다.
PR이 이 문서를 수정하는 경우 변경 내용 자체는 일반 PR diff처럼 검토 대상이며, 같은 PR의 새로운
내용을 자기 정당화 근거로 사용하지 않는다.

## 1. 프로젝트 목적

이 저장소는 제조 설비 예지보전(PdM)을 위한 온톨로지 기반 제품 애플리케이션이다.

핵심 제품 흐름은 source observation을 semantic/model pipeline으로 처리한 뒤, 현재 observation에
대한 runtime inference와 Evidence를 생성하고 역할별 Dashboard/Report에서 의사결정에 사용하는 것이다.

```text
Biz-CollabCraft/gen_data
Source Data Producer / Canonical V3.1 source-reference baseline
        ↓
systems/generator
semantic mapping / topology / feature / training
→ immutable versioned Model Artifact
        ↓ MODEL_ARTIFACT_URI
systems/backend/app/diagnosis
current observation + Model Artifact
→ runtime inference
→ Product Result Artifact / Evidence
        ↓
API / systems/frontend / Report
```

## 2. 시스템 책임 계약

### `Biz-CollabCraft/gen_data`

- raw / simulation / synthetic sensor data의 Source of Truth
- Canonical V3.1 물리·생성 기준과 source/reference/test fixture 소유
- seed 기반 재현성과 source package validation 소유
- 과거 `model_contract`, `model_metrics`, `prediction_snapshot`, `prediction_factor`,
  `prediction_timeline`, `result_artifact`는 reference/regression/migration fixture일 수 있으나
  제품 runtime의 운영 SoT가 아니다.

### `systems/generator`

- extraction / normalization
- ontology semantic mapping
- topology preparation
- feature engineering / materialization
- model training / evaluation
- immutable versioned Model Artifact publish

책임 끝점은 Model Artifact publish다. 사용자 요청 기반 runtime inference, Product Result Artifact,
최종 Evidence 생성은 generator 책임이 아니다.

### `systems/backend`

- 공식 FastAPI application host
- injected `MODEL_ARTIFACT_URI` provider를 통한 Model Artifact consume
- manifest/schema/checksum/compatibility 검증
- current observation runtime inference
- Product Result Artifact / Evidence 최종 생성
- API/application composition

`systems/backend/app/diagnosis`가 runtime prediction/Evidence의 canonical owner다.

### `systems/frontend`

- 공식 React + Vite 제품 application host
- Result Artifact / Evidence/API 소비
- Backend 도메인 폴더 구조와 기계적으로 1:1 매핑하지 않는다.
- Dashboard / Report / Evidence / Decision / Activity 등 사용자 workflow 중심 구조를 유지한다.

## 3. 절대 지켜야 할 Architecture Invariants

아래 위반은 일반적인 스타일 문제가 아니라 architecture regression으로 간주한다.

1. root `api/` 또는 root `web/`이 operational runtime host로 다시 생기면 안 된다.
2. `systems/backend`가 `systems.generator` 구현을 static/direct import하면 안 된다.
3. Backend가 sibling generator 디렉터리, `model_store`, `../generator/...` 물리 경로를 탐색하면 안 된다.
4. Generator/Backend 경계는 Python import가 아니라 versioned Model Artifact contract로 연결한다.
5. Backend가 `gen_data` prediction/result fixture를 최신 operational runtime result처럼 직접 읽으면 안 된다.
6. `systems/backend/ontology_dashboard/modeling`과 `ml/src/factory_signal_ml`은 compatibility port/adapter일 수
   있으나 semantic mapping, feature build, model training 또는 runtime inference의 canonical owner가 되면 안 된다.
7. Model Artifact의 실제 위치는 `MODEL_ARTIFACT_URI` 또는 동등한 injected provider로 전달해야 한다.
8. incompatible/corrupt Model Artifact를 임의 sibling file이나 heuristic으로 조용히 대체하면 안 된다.
9. `development`, `dev`, `deploy`, `staging`, `production`에서는 Model Artifact가 없을 때 heuristic fallback이
   기본 허용되면 안 된다. 명시적인 override가 없는 한 fail-fast가 기본이다.
10. `local`, `demo`, `test`에서만 compatibility 목적의 heuristic fallback을 기본 허용할 수 있다.
11. `systems/backend`와 `systems/frontend`는 독립 실행/배포 단위여야 한다. Backend image/runtime이
    Generator source checkout을 요구하면 안 된다.
12. migrations, Docker, CI, local/public scripts는 canonical `systems/backend` / `systems/frontend` 경로를
    사용해야 하며 legacy root runtime path와 동작이 갈리면 안 된다.
13. 이동/refactor 후 `Path(__file__).resolve().parents[n]` 같은 경로 계산은 repo root, migrations, fixture,
    docs/assets를 실제 실행 위치에서 올바르게 가리켜야 한다.
14. optional PostgreSQL/Redis/Neo4j integration은 해당 기능을 사용하지 않는 local/SQLite startup을
    불필요하게 막으면 안 된다. optional dependency는 기능 경계에서 fail해야 한다.
15. Feature의 rolling/diff/shift/ewm은 asset partition을 넘어가면 안 된다.
16. Feature 계산은 canonical timestamp 기준으로 결정적이어야 한다.
17. 동일 ontology node의 복수 source field가 Feature를 덮어쓰면 안 된다.
18. Label은 `binary_failure_within_horizon` 의미를 따라야 한다.
19. 고장 anchor 자체와 active failure interval을 예측 입력으로 사용하면 안 된다.
20. Model package는 하위 stacked PR의 prediction package를 참조하면 안 된다.
21. package facade가 ImportError를 None/빈 registry로 숨기면 안 된다.
22. Generator internal API는 training/publish까지만 담당한다.
23. runtime inference와 Result Artifact는 Backend diagnosis가 소유한다.
24. Closed-loop 상태 머신은 Backend Domain이 canonical owner이며 Frontend가 role/state 조합으로 별도 상태
    머신을 구현하면 안 된다.
25. Closed-loop Product Action은 Backend가 role + permission + object state + scope + lineage를 기준으로
    계산한 `available_actions`를 통해 노출한다.
26. 기존 Event API와 Activity key는 Closed-loop 확장 때문에 삭제·rename하지 않고 additive compatibility를
    유지한다.
27. `process_manager`는 system administrator가 아니라 생산 운영 의사결정자이며,
    `process_engineer`와 `maintenance_technician`은 각각 현장 엔지니어와 정비 작업자로 구분한다.
28. Closed-loop mutation 응답은 Persistence가 확정한 ID와 resulting state, replay 여부를 반환해 Frontend가
    운영 ID나 결과 상태를 추측하지 않게 한다.

15~19번은 `docs/mvp/generator-feature-label-contract.md`를 근거로 한다.

20·21번은 PR 단독 import 및 실행 가능성이라는 기존 코드 결함에 근거하며,
ADR 승인 여부와 무관하게 즉시 적용되는 merge blocker다.

22·23번은 ADR-001과 ADR-002를 근거로 한다.

> ADR-001/002는 현재 `Proposed` 상태다. 22·23번 목표 계약은 승인 및 관련
> 구현 PR 적용 전까지 현행 구현 계약을 대체하거나 자동 merge blocker로
> 사용하지 않는다.

24~28번은
[`closed-loop-product-consumption-contract.md`](./closed-loop-product-consumption-contract.md)를 근거로 하며,
Closed-loop Domain/API/UI를 변경하는 PR에서 적용한다.

## 4. Model Artifact / Result Artifact 구분

Model Artifact는 Generator가 만드는 학습/배포 산출물이고 Product Result Artifact/Evidence는 Backend가
현재 observation에 대해 runtime에서 만드는 제품 산출물이다.

검토 시 다음 혼동을 반드시 찾는다.

- training metric/feature importance를 Product Evidence로 오인
- reference fixture를 최신 prediction으로 사용
- dataset/model version provenance 유실
- artifact schema/checksum 검증 우회
- mutable `latest`만 기록하고 실제 immutable model version을 남기지 않는 경우
- generator가 Product Result Artifact를 최종 생산하거나 Backend가 training을 다시 소유하는 경우

## 5. 공식 MVP 제품 계약

공식 제품 Surface는 다음을 우선한다.

- 공식 진입점: `/app/projects/{project_id}/mvp`
- 공식 화면: Overview / Objects / Operations / Event Executive Brief
- 기본 설정: `VITE_WEEK2_MVP_ONLY=true`
- 핵심 흐름: 역할별 PdM view → 고위험 설비 확인 → Event 기반 Report/Evidence → 현장 엔지니어의
  점검·분석 근거 → 생산 운영 의사결정자의 Recommendation/Decision 판단 → 정비 필요 시 정비 작업자의
  WorkOrder/MaintenanceAction 실행 → Activity/lineage 확인
- Closed-loop 주요 RBAC 역할: `process_manager`, `process_engineer`, `maintenance_technician`
- 제품 표시 의미: 생산 운영 의사결정자, 현장 엔지니어, 정비 작업자
- 기존 `manager` / `engineer`는 Report/UI compatibility view alias이며 RBAC role code와 동일 enum이 아니다.
- Dataset / Governance / Modeling / Agent / Analysis / 전체 Ontology Workbench 및 실험 화면은
  보존할 수 있으나 공식 MVP Surface를 덮어쓰면 안 된다.

Closed-loop 상태·역할·Action·API 소비 기준은
[`closed-loop-product-consumption-contract.md`](./closed-loop-product-consumption-contract.md)를 사용한다.

Frontend 변경은 다음 regression을 우선 확인한다.

- 공식 MVP route가 사라지거나 다른 experimental surface로 redirect되는지
- role별 첫 화면/정보 우선순위가 깨지는지
- 고위험 설비 → Report/Evidence 흐름이 끊기는지
- 이동 후 asset/base path, Vite build, nginx history fallback, Playwright route가 깨지는지
- Backend API contract 변경을 Frontend adapter가 따라가지 못하는지

## 6. CI와 테스트를 해석하는 원칙

CI PASS는 supporting evidence이지 correctness의 증명이 아니다.

- 테스트가 PASS했다는 이유만으로 path/runtime/Docker/migration/dependency 변경을 옳다고 결론내리지 않는다.
- changed implementation 자체를 확인한다.
- 기존 baseline failure가 있더라도 **새 failure가 추가됐는지**를 구분한다.
- architecture verifier가 검사하지 않는 경계도 수동 검토한다.
- rename detection이 된 파일은 단순 이동 자체를 결함으로 보고하지 않고, 이동으로 인해 달라진 import/path/runtime
  의미를 검토한다.

## 7. Merge 전 반드시 답할 질문

자동 리뷰는 Ready to Merge를 선언하기 전에 아래 질문을 명시적으로 검토한다.

1. canonical Backend runtime host가 정확히 하나인가?
2. canonical Frontend runtime host가 정확히 하나인가?
3. Backend가 Generator source 없이 startup 가능한가?
4. local/SQLite 모드에서 optional PostgreSQL package 없이 startup 가능한가?
5. deploy/staging/production에서 Model Artifact 누락이 heuristic으로 조용히 대체될 수 있는가?
6. Backend가 sibling generator/model-store 위치를 알고 있거나 탐색하는가?
7. `gen_data` reference fixture가 operational runtime input으로 사용되는가?
8. scripts/Docker/CI가 legacy root `api/` 또는 `web/` 경로에 의존하는가?
9. file move 이후 `parents[n]` 또는 상대경로 계산이 실제 위치와 일치하는가?
10. migrations가 local/CI/container 모두 `systems/backend`에서 일관되게 로드되는가?
11. Frontend build/Playwright/nginx가 `systems/frontend`를 canonical host로 사용하며 route/assets를 유지하는가?
12. compatibility adapter가 새 canonical implementation copy로 다시 자라나 ownership 중복을 만들었는가?
13. Model Artifact → Result Artifact/Evidence provenance가 유지되는가?
14. 공식 MVP workflow와 role surface가 변경으로 인해 퇴행하는가?
15. PR branch 단독 import가 가능한가? (상위 stacked PR의 모듈을 참조하지 않고 독립적으로 import되는가)
16. `REGISTERED_MODELS`가 비어 있지 않은가? (`except ImportError`로 조용히 빈 registry가 되지 않는가)
17. Model Artifact publish/validate round trip이 가능한가? (Backend `artifact_provider.py`가 실제로 로드할 수 있는가)
18. Feature/Label schema version이 manifest에 기록되는가? (`feature_schema_version`, `label_schema_version`)
19. Closed-loop UI가 Backend Domain 상태 머신을 자체 재구현하는가?
20. Backend가 실제 role/permission/state/scope/lineage를 반영한 `available_actions`를 제공하는가?
21. Event/Activity API의 기존 key가 Closed-loop 추가로 삭제·rename되거나 shape-breaking 변경되는가?
22. `process_manager`, `process_engineer`, `maintenance_technician`의 제품 역할과 Action 경계가 섞이는가?
23. mutation 이후 Frontend가 ID나 resulting state를 합성·추측해야 하는 응답 계약인가?

## 8. 자동 리뷰 출력 형식

리뷰는 가능한 한 다음 구조를 따른다.

### Review Scope & Evidence

- 검토한 commit/base
- diff truncation 여부
- 추가로 확인한 critical file/context
- CI 결과를 알고 있다면 supporting evidence로만 표시

### Architecture Contract Matrix

다음 열을 가진 표를 사용한다.

`Contract | Result(PASS/FAIL/NOT PROVEN) | Evidence`

최소한 runtime host, Generator/Backend import boundary, Model Artifact injection, heuristic fail-fast,
Docker/CI path, optional dependency, migration path를 평가한다.

### MVP Regression Matrix

`MVP Contract | Result(PASS/FAIL/NOT PROVEN) | Evidence`

공식 route/surface, role workflow, Report/Evidence flow, frontend build/runtime path를 평가한다.

### Actionable Findings

실제 결함만 작성한다.

- `[P0]` 즉시 중단/심각한 보안·데이터 손실
- `[P1]` merge blocker 수준 correctness/runtime/deployment regression
- `[P2]` 후속 수정이 필요한 유의미한 문제
- `[P3]` 낮은 위험의 개선 사항

각 finding은 file path 또는 symbol, 근거, 실제 영향, 구체적 수정 방향을 포함한다.
근거가 부족하면 finding을 만들지 말고 `NOT PROVEN` 또는 Risk/Unknowns로 남긴다.

### Risk / Unknowns

diff/context만으로 증명할 수 없는 항목을 명확하게 분리한다.

### Merge Readiness

- Critical architecture invariant에 FAIL이 있거나 P0/P1 finding이 있으면 `Not Ready`.
- 중요한 항목이 `NOT PROVEN`이면 기본적으로 `Conditional`.
- 모든 critical invariant가 PASS이고 P0/P1이 없을 때만 `Ready to Merge`를 사용할 수 있다.

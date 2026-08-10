# Week 2 MVP 실행 코드 책임 재배치 기록

- 대상: PR #9 `feat/week2-mvp-implementation-import`
- 상위 계약: PR #8 저장소 책임, PR #10 시스템 아키텍처, `gen_data` PR #2 source/reference fixture 분류
- 목적: 개인 프로토타입에서 이관한 실행 코드를 팀의 장기 책임 경계에 맞추되 Week 2 MVP 화면과 API 호환성을 유지한다.

## 적용한 책임 경계

```text
Biz-CollabCraft/gen_data
Source Data Producer / Canonical V3.1 source-reference baseline
        ↓
systems/generator
extraction → ontology mapping → topology → feature → training/evaluation
→ versioned Model Artifact publish
        ↓ MODEL_ARTIFACT_URI
systems/backend/diagnosis
current observation + Model Artifact
→ runtime inference
→ Product Result Artifact / Evidence
        ↓
기존 FastAPI API → React/Report consumer
```

### `gen_data`

raw/simulation/synthetic sensor data, Canonical V3.1 물리·생성 기준, source/reference/test fixture와 seed 재현성의 Source of Truth다. `model_contract`, `model_metrics`, `prediction_snapshot`, `prediction_factor`, `prediction_timeline`, `result_artifact`는 삭제하지 않지만 compatibility/regression/migration fixture로만 취급한다.

### `systems/generator`

- source observation extraction/normalization
- ontology semantic mapping
- topology preparation
- feature engineering
- model training/evaluation
- immutable versioned Model Artifact publish

기존 확장 ML Validator/workbench가 `api/ontology_dashboard/modeling` 아래에서 직접 수행하던 semantic mapping, feature materialization, sklearn experiment/training 구현도 각각 `systems/generator/ontology_mapping`, `systems/generator/feature`, `systems/generator/model`로 이동했다. API에는 기존 화면·계약을 깨지 않기 위한 lazy compatibility port만 남겼다.

Model Artifact는 `model-artifact-v1.0` manifest로 publish하며 artifact type/schema, model/dataset/feature version, created time, training config, metrics, checksum, provenance, compatibility, artifact file 목록을 포함한다.

### `systems/backend/diagnosis`

- `MODEL_ARTIFACT_URI`로 주입된 Model Artifact의 manifest/checksum/compatibility 검증
- current observation runtime inference
- `result-artifact-v1.0` 의미와 호환되는 Product Result Artifact 생성
- 제품 Evidence 생성

기존 `api/ontology_dashboard/modeling/registry.py`가 수행하던 active model load/scoring/explanation 구현도 `systems/backend/diagnosis/model_registry.py`로 이동했고 API 경로에는 compatibility adapter만 남겼다.

Backend는 generator Python 구현이나 sibling `model_store` 경로를 import/탐색하지 않는다. Week 2 로컬 데모에서 Artifact가 주입되지 않은 경우에만 기존 deterministic heuristic을 명시적 compatibility fallback으로 유지한다.

ML authoring compatibility port는 generator-capable 개발/통합 배포에서만 실제 generator 구현을 지연 로드한다. 일반 Backend startup과 diagnosis runtime은 generator package 없이도 import 가능하도록 유지한다.

### API / Frontend / Report

기존 `api/`와 `web/`은 이번 PR의 대규모 import에서 안정화된 실행 host로 유지한다. Backend API의 실제 MVP Evidence 경로는 `systems/backend/diagnosis`를 호출하며, Frontend는 backend 도메인 폴더 구조와 1:1 재배치하지 않는다.

## 기존 `ml/` 처리

기존 `ml/src/factory_signal_ml`에는 training과 runtime prediction/Evidence가 한 패키지에 섞여 있었다. 구현은 각각 `systems/generator`와 `systems/backend/diagnosis`로 이동했고, 기존 import와 CLI를 깨지 않기 위한 compatibility adapter만 남겼다.

## 이번 PR에서 의도적으로 유지한 것

- 역할별 PdM view
- Event 기반 Report
- decision / note / activity 흐름
- manager / engineer 역할별 workflow
- 위험 설비와 Evidence 확인 흐름
- Dataset/Governance/ML Validator/Agent 등 확장 코드 자체

확장 화면의 대형 UX 재설계와 모든 기존 대형 service 파일 분해는 이번 책임 재배치의 범위를 넘으므로 후속 작업으로 둔다.

## 회귀 기준

`gen_data` PR #2의 Canonical V3.1 `model_outputs/*`는 운영 입력이 아니라 비교 기준이다. 새 runtime Result Artifact는 binary `failure_within_horizon` 의미, model/dataset provenance, factor 방향과 같은 의미 계약을 비교할 수 있지만 제품 실행이 해당 fixture JSONL을 최신 결과처럼 직접 읽지는 않는다.


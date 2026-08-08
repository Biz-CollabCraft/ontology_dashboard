# 프로젝트 아키텍처 — systems/ 및 도메인 구조

> 이 문서는 `docs/` 하위 문서로, 실제 코드 구조와 100% 일치해야 하는 살아있는 문서입니다.
> `.agents/`(에이전트 작업 규칙)와는 별개로, 팀원이 프로젝트 구조를 파악하기 위한 문서입니다.

---

## 1. 전체 원칙

- 실행 가능한 코드는 전부 `systems/` 하위에 격리한다. 프로젝트 루트에는 `.agents/`, `docs/`, `README.md`, `systems/`만 남긴다.
- `systems/` 하위 세 시스템(`generator`, `backend`, `frontend`)은 **대등한 축**이다. 실행 방식(배치 vs 실시간)이 다를 뿐 위계 관계(핵심/보조)는 아니며, 서로 파일 매개로만 연결하고 코드 레벨 결합은 만들지 않는다.
- 각 시스템 내부는 자기 생태계(Python, React)의 표준 레이아웃을 그대로 따른다. `.env`, `requirements.txt`(또는 `package.json`), `Dockerfile`은 각 시스템 루트에 위치하며 소스 코드 폴더(`app/`, `src/`) 밖에 둔다.
- 각 시스템 내부는 **계층(Router/Service/...) 우선이 아니라 도메인 우선(DDD 스타일)**으로 구성한다. 도메인 폴더 안에 그 도메인이 필요로 하는 모든 계층 파일을 둔다. `domains/` 같은 래퍼 폴더는 쓰지 않고, 도메인 이름을 최상위(`app/`, `src/` 바로 아래)에 둔다.
- 계층 파일명은 `{도메인}_{계층}.py` 형식을 따른다 (예: `equipment_service.py`, `report_generator.py`). 같은 이름의 계층 파일이 여러 도메인에 반복돼도 파일명만으로 구분 가능하도록 하기 위함이며, 이 컨벤션 덕분에 최상위 시스템명(`generator`)이 하위 계층 파일명과 겹치는 문제도 원천적으로 발생하지 않는다.
- 동일한 로직/컴포넌트가 **3개 이상의 도메인**에서 쓰이면 그때 `common/`으로 분리한다. 미리 공용화하지 않는다.
- 용어: `systems/` 하위 각 축(`generator`/`backend`/`frontend`)은 **"시스템"**이라고 부른다. **"서비스"**는 도메인 계층의 `*_service.py` 파일(과 그 역할)만을 가리킨다. 두 층위의 용어를 겹쳐 쓰지 않는다.

---

## 2. 전체 루트 구조

```text
project-root/
├── .agents/              ← 프로젝트 외부 영역 (에이전트 작업 규칙, 산출물 아님)
├── docs/                  ← 팀 공유 문서 (본 문서 포함)
├── README.md              ← 프로젝트 개요, 실행 방법, 구성원 소개
└── systems/                ← 실행 가능한 코드 전체를 격리하는 그루핑 폴더
    ├── generator/
    ├── backend/
    └── frontend/
```

`docs/`는 `systems/` 안에 포함되지 않는다. `systems/`가 "실행되는 코드"인 반면 `docs/`는 "사람이 읽는 프로젝트 지식"으로 성격이 다르기 때문에, 둘은 루트에서 나란한 별개 축으로 유지한다.

---

## 3. systems/generator — 데이터 재가공 및 모델 구성·보관

**책임**: 원본 파일을 읽어 필요한 형태로 재구성하고, 모델을 학습·구성해서 backend가 쓸 수 있는 형태로 만들어 보관하는 것까지 담당한다. 사용자 요청과 무관하게 독립적으로(배치/오프라인 성격) 동작한다. **실시간 추론이나 사용자 응답은 이 시스템의 책임이 아니다.**

> **명칭 결정 배경**: `pipeline`은 backend 내부(요청 처리 파이프라인 등)에서도 재등장할 수 있는 일반명사라 층위 충돌 우려가 있었고, `engine`/`foundry`/`refinery`도 후보로 검토됐으나 최종적으로 "모델과 backend가 실제로 소비할 산출 파일을 만들어낸다"는 역할을 가장 직접적으로 표현하는 `generator`로 확정했다. `report/report_generator.py`처럼 하위 계층에 동일 어근이 있어도, `{도메인}_{계층}.py` 컨벤션 덕분에 최상위 `generator`와 문자열이 겹치지 않아 혼동 소지가 없다.

```text
systems/generator/
├── extraction/
│   ├── extraction_agent.py       # 원본 구조 판별 → 추출 계획 (LLM 호출)
│   ├── extraction_service.py     # 계획대로 실제 추출 실행
│   └── extraction_cache.py       # 판별 결과 캐싱 (재실행 시 재호출 방지)
├── ontology_mapping/
│   ├── mapping_agent.py          # 컬럼 → 온톨로지 노드 의미 매핑
│   ├── mapping_service.py
│   └── mapping_cache.py
├── topology/
│   ├── topology_agent.py         # 설비 간 관계(위상) 추론
│   ├── topology_service.py
│   └── topology_cache.py
├── feature/
│   ├── feature_builder.py        # Feature 생성(.npy)
│   └── feature_catalog.py
├── model/
│   ├── model_training.py         # 모델 학습
│   ├── model_registry.py         # 등록/버전 관리
│   └── model_store/              # 최종 산출물 — backend가 읽기 전용으로 참조하는 지점
│       ├── independent-logreg-v3.1/
│       ├── lightgbm-v1/
│       ├── xgboost-v1/
│       └── randomforest-v1/
├── common/                        # 3개 이상 하위 도메인이 공유하는 것만
│   ├── agent_base.py              # "판단 단위 분리" 원칙(한 번 호출 = 한 판단)을 강제하는 공통 베이스
│   └── cache_base.py              # 3종 캐시(추출계획/매핑/위상)의 공통 fingerprint→결과 캐시 로직
├── .env
└── requirements.txt
```

### generator 내부 파이프라인 순서

```
Raw Data
  → extraction        (구조 판별 → 추출)
  → ontology_mapping   (컬럼 의미 매핑)
  → topology            (설비 간 관계 구성)
  → feature              (Feature 생성)
  → model                (학습 → model_store에 보관)
```

각 단계는 "판단 단위 분리" 원칙을 따른다 — 하나의 LLM 호출은 하나의 판단만 담당하며, 여러 판단을 한 프롬프트에 섞지 않는다.

---

## 4. systems/backend — 사용자와 맞닿는 부분

**책임**: 사용자 요청에 실제로 응답한다. `systems/generator/model/model_store`에 보관된 모델과 Feature를 가져다 써서 실시간 예측·리포트·대시보드 API를 제공한다. **학습 로직은 이 시스템에 존재하지 않는다.**

```text
systems/backend/
├── app/
│   ├── equipment/
│   │   ├── equipment_router.py
│   │   ├── equipment_service.py
│   │   ├── equipment_repository.py
│   │   ├── equipment_schema.py
│   │   └── equipment_exception.py
│   ├── diagnosis/                 # generator/model/model_store를 참조해 실시간 추론만 실행
│   │   ├── diagnosis_router.py
│   │   ├── diagnosis_service.py
│   │   ├── diagnosis_schema.py
│   │   └── diagnosis_exception.py
│   ├── report/                     # 예측 결과 기반 리포트 생성
│   │   ├── report_router.py
│   │   ├── report_service.py
│   │   ├── report_generator.py     # 리포트 문서/텍스트 산출 — 최상위 "generator"와 별개
│   │   └── report_schema.py
│   └── dashboard/                   # 다른 도메인 서비스를 조합/호출하는 조합 도메인
│       └── (동일 계층 패턴)
├── .env
├── requirements.txt
└── Dockerfile
```

### generator ↔ backend 연결 방식

파일 매개 디커플링을 원칙으로 한다. `backend`는 `systems/generator/model/model_store` 경로를 **읽기 전용**으로 참조하며, `generator`의 내부 구현(Agent 로직, 캐시 파일 등)을 몰라도 model_store 산출물만으로 동작할 수 있어야 한다. 코드 레벨의 직접 import는 하지 않는다. 이 원칙은 이전에도 AutoPdM↔Backend, gen_data↔ontology_dashboard 관계에서 반복적으로 적용해온 것과 동일하다.

---

## 5. systems/frontend — 사용자 화면

```text
systems/frontend/
├── src/
│   ├── equipment/
│   ├── diagnosis/
│   ├── report/
│   ├── dashboard/
│   └── common/          # 3개 이상 도메인에서 공용으로 쓰이는 컴포넌트/훅/API 모듈
├── .env
└── package.json
```

도메인 이름은 `backend`의 도메인 이름과 동일하게 맞춘다 — API 계약과 폴더명이 일치하면 유지보수에 유리하기 때문이다.

---

## 6. 세 시스템이 대등한 이유

`generator`를 `backend` 하위에 종속시키지 않고 `systems/` 아래 대등한 축으로 둔 이유:

1. **일관성**: AutoPdM↔Backend, gen_data↔ontology_dashboard와 마찬가지로 이 프로젝트는 성격이 다른 컴포넌트를 항상 파일 디커플링으로 대등하게 연결해왔다. 여기서만 하위 종속 구조로 바꾸면 이 원칙이 깨진다.
2. **배포 독립성**: `backend`는 상시 API 서버, `generator`는 배치/주기적 재학습이다. 하위 폴더로 묶으면 재학습(무거운 연산, 리소스 사용)이 API 서버 배포·재시작과 얽히기 쉽다.
3. **팀 소유 경계와의 일치**: 파이프라인/모델 담당자와 backend API 담당자가 이미 분리되어 있다. 폴더 구조가 이 소유 경계와 일치해야 탐색과 책임 소재가 명확하다.
4. **"backend"의 의미 보존**: backend 하위에 학습 로직까지 들어가면 "사용자와 맞닿는 부분"이라는 정의가 흐려진다.

---

## 7. 전체 데이터 흐름 요약

```
[systems/generator]                        [systems/backend]              [systems/frontend]
Raw Data
  → extraction
  → ontology_mapping
  → topology
  → feature
  → model (학습) → model_store  ──파일──▶  diagnosis (추론 실행)
                                          → report
                                          → dashboard (조합)  ──API──▶   화면 표시
```

`generator`는 "데이터가 준비되고 모델이 만들어지는 곳", `backend`는 "그 모델을 갖다 쓰는 곳"으로 책임이 명확히 나뉜다.

---

## 8. 아직 확정되지 않은 사항

| 항목 | 내용 |
|---|---|
| `report`가 `model`/`prediction` 결과에 의존하는 구체적 연결 방식 | generator의 model_store 산출물을 backend의 report 도메인이 어떤 형식(파일 vs 내부 서비스 호출)으로 소비할지 세부 계약 미정 |
| `systems/generator`의 재실행 주기(배치 스케줄) | 수동 트리거인지 주기적 자동 재학습인지 미정 |

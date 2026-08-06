# ontology_dashboard

CodeMap 프로젝트의 온톨로지 기반 설비 예지보전(PdM) 및 실시간 대시보드 저장소입니다.

---

## 1. 시스템 구조 개요

본 프로젝트는 4개의 독립된 시스템으로 구동되며, 파일 매개 방식을 통해 연동됩니다.

```text
USER
 ↕
Front (React)
 ↕
Back (FastAPI)
 ↑ file read
Result (json)
 ↑ file write
┌───────────────────────┐
│      Auto PdM         │
│         ↑             │
│    센서 데이터(file)   │
└───────────────────────┘
         ↑
  Azure PdM 데이터 증강기   → 별도의 repo로 분리
```

### 핵심 연동 원칙
1. **Back ↔ Auto PdM**: 직접 네트워크 통신 없이 `Result (json)` 파일로만 연동합니다.
2. **Auto PdM ↔ Augmenter**: `센서 데이터(file)` 갱신을 통해 단방향으로 연동합니다.

---

## 2. 개발 및 가이드라인 안내

프로젝트에 기여하거나 코드를 작성하기 전, 반드시 다음 운영 매뉴얼 및 개발 표준 문서를 참조하십시오:

- 에이전트 운영 매뉴얼: [.agents/AGENTS.md](file:///.agents/AGENTS.md)
- 시스템 아키텍처: [.agents/project/architecture.md](file:///.agents/project/architecture.md)
- 코딩 및 주석 표준: `.agents/standards/` 참조

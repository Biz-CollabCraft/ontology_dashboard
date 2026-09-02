# Schema and Diagram Documents

상태: 팀 문서 인덱스
기준: 2026-09-01

이 폴더는 사람이 읽는 DB 구조, 관계, 다이어그램 문서를 둔다. 기계 판독 JSON Schema의 정본은
저장소 최상위 [`contracts/schemas/`](../../contracts/schemas/)에 있다.

## 문서 목록

| 문서 | 역할 |
| --- | --- |
| [Workflow and Closed-loop DB Diagram](./db-diagram.md) | Workflow 화면과 Closed-loop가 참조하는 identity, activity/audit, Agent Review runtime, recommendation, work order, inspection, cost analysis, maintenance action/event, equipment state 테이블 관계를 정리한다. |

## 관리 원칙

- DB 다이어그램은 SQL migration과 실제 저장소 구조를 사람이 이해할 수 있게 설명한다.
- JSON Schema 계약은 `contracts/schemas/`를 수정하고, 이 폴더에는 중복 복사하지 않는다.
- 문서 첫 부분에 포함 범위와 제외 범위를 적어 다이어그램이 전체 DB를 대표하는 것처럼 보이지 않게 한다.

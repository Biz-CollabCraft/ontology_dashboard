# Decision Workspace 사건·관측 분리 검토 증거

- 작성일: 2026-09-14
- 기준 커밋: `99179fe0d61e04a1256c936fbb8c8b9221365f53`
- 브랜치: `codex/decision-workspace-integration`
- 목적: 버튼 복구 문제의 재현, 외부 제품의 확인 가능한 처리 방식, 설계 제안을 구분한다.
- 범위: 로컬 시뮬레이션 데이터와 공식 제품 문서. 현장 운용 성과·배포 검증·전문가 승인 증거가 아니다.
- 이번 문서 작성에서는 코드를 변경하거나 테스트를 재실행하지 않았다. 아래 실행 기록은 같은 대화의 선행 리뷰에서 수집한 결과이며, 작성 시 기준 HEAD와 작업 상태만 재확인했다.
- 상태 표기: Verified = 코드와 실행/계약 등 복수 근거 확인, Partially Verified = 일부 경로만 확인, Not Proven = 확인하지 않음. 제품의 운영 적합성은 별도 판단한다.

## 1. 내부 재현 기록

### E-01: 근거 신선도 판정과 추천 가능 여부 불일치 — Verified

대상:
- 설비: `CNC-S02-L04-01`
- 사건/예측 식별자: `RESULT#GEN-f8e740fb-037b-50b1-99f8-b69a52a4ae34`
- 프로젝트: `manufacturing-demo-project`
- 워크스페이스: `manufacturing-demo`
- dataset version: `dsv-8db96cf9-c174-5dfc-b17f-3fdf680b3825`
- 환경: 로컬 frontend 3101 / backend 8112 / PostgreSQL 시뮬레이션 데이터.

선행 리뷰에서 관측한 응답 필드의 최소 발췌다. 전체 원문 응답을 보관한 파일로 간주하지 않는다.

```json
{
  "detail": {
    "data_status": {
      "source": "canonical",
      "is_stale": true,
      "is_data_quality_hold": false,
      "last_updated_at": "2026-09-14T07:30:00+00:00"
    },
    "available_action": {
      "action_id": "request_inspection_work_order",
      "disabled_reason": null
    },
    "primary_action": {
      "owner_role": "process_engineer",
      "owner_label": "설비 엔지니어"
    }
  },
  "decision_session_create": {
    "http_status": 200,
    "status": "ready_for_review",
    "recommended_action": "REQUEST_INSPECTION",
    "execution_binding_present": true
  },
  "decision_session_read": {
    "http_status": 200,
    "same_session_id": true
  }
}
```

재현 절차:
1. 생산 관리자 테스트 계정으로 로그인한다. 인증 정보는 증거 파일에 저장하지 않는다.
2. 위 scope/event/dataset을 지정해 `GET /api/objects/{asset_id}/detail-view`를 조회한다.
3. 동일 artifact ID와 observed_at을 사용해 `POST /api/objects/{asset_id}/decision-sessions`를 호출한다.
4. 반환된 session ID로 GET 재조회한다.
5. `is_stale`, 추천 상태, 실행 연결 유무를 비교한다. WorkOrder 생성/승인은 하지 않는다.

코드 근거:
- `systems/backend/app/infra/db/asset_detail_read_adapter.py:data_status`: 저장 행 created_at이 15분 이상 지났으면 is_stale.
- `systems/backend/app/operations/decision_session_service.py:_validate_packet_identity`: asset/artifact/as-of 정합성 확인. 이 검증 자체가 위 15분 판정과 같은 것은 아니다.
- `systems/frontend/src/features/operations/decision/decisionWorkspaceModel.ts:workflowActions`: detail stale이면 업무 액션 차단.
- `systems/frontend/src/features/operations/decision/DecisionProposalPanel.tsx:useDecisionProposal`: stale이면 추천 API 호출 전 차단.

해석의 정정:
- 불일치는 확인됐다. 그러나 “서버도 모든 오래된 사건을 차단”이 근본 해결이라는 결론은 철회한다.
- 관측 신선도, 증거 정합성, 업무 상태, 액션별 필요 근거를 분리한 정책이 우선이다.
- 이 결과만으로 무권한 mutation이나 실제 작업 실행이 가능하다고 주장하지 않는다.

### E-02: 재판단이 같은 만료 사건을 반복 조회 — Verified

사용자 탭에서 다음 상태를 직접 읽고, ‘다시 판단’을 눌러 같은 안내가 지속되는 것을 확인했다.

```text
다음 판단
최신 근거와 담당 역할을 확인해 주세요.
다시 판단

업무 처리
점검 요청
최신 근거를 확인한 뒤 진행해 주세요.
```

- `DecisionWorkspaceApplication.tsx`의 onRetry는 목록 갱신과 decisionRevision 증가를 수행한다.
- CaseLoader는 선택된 event ID로 detail을 다시 읽는다.
- 최초 prediction/event가 그대로이면 저장 시각 기반 만료는 조회로 해소되지 않는다.
- 새 사건 이동 버튼은 기존 사건에 최신 관측을 연결하는 기능과 다르다.
- 따라서 정상 사건의 최초 진입 성공은 장시간 진행 중인 사건의 복구 성공을 증명하지 않는다.

### E-03: 요청 권한과 업무 담당 표시 불일치 — Verified

- `systems/backend/app/maintenance/service.py:decision_context`: 점검 요청은 process_manager + events.decision 기준.
- `systems/backend/app/operations/asset_detail_view_model.py:_ACTION_OWNER_BY_ID`: request_inspection_work_order의 표시 담당은 process_engineer.
- UI의 ‘설비 엔지니어’는 primaryAction.ownerLabel이며 로그인 계정 역할의 증거가 아니다.
- URL의 role 파라미터도 인증된 principal 권한의 증거가 아니다.
- 앞서 해당 문구만으로 사용자 권한 부족을 단정한 설명은 정정한다.

### E-04: 이미 수정한 범위와 남은 한계 — Partially Verified

기준 커밋에 포함:
- 현재 사건의 owner 점검/정비 이력을 DecisionSession 입력에 연결.
- 예측 observed_at과 별도 workflow_as_of를 사용하고 이력 변경 시 이전 추천 무효화.
- 충돌 수치 planning_minutes / maintenance_minutes를 UI에 보존.
- 기본 실시간 실행에서 accelerated simulation 허용을 끔.
- 미래 관측 안내와 재판단 시 목록 재조회.

이 변경은 stable case ID, 다중 관측 연결, 액션별 신선도 정책을 구현한 것이 아니다. 미래 관측을 새로 받지 않도록 한 설정이 이미 저장된 미래 행을 삭제하거나 보정하지도 않는다.

선행 실행 결과:
| 검증 | 기록된 결과 | 입증 범위 / 한계 |
|---|---|---|
| 프론트 전체 | 315 tests passed | 당시 단위·컴포넌트 계약. 사건 장기 복구 E2E 증거 아님 |
| 관련 백엔드 최종 범위 | 39 tests passed | live ingestion, workflow overlay, session/API 회귀 |
| 빌드 | 통과 | TypeScript/Vite. 런타임 의미적 정합성은 별도 |
| 이전 fixture E2E | 2 passed | 1440/768/390, 추천→검토→기존 양식. 실제 owner 업무 변경 아님 |
| 이전 live E2E | 유효한 CMP 사건 1 passed | 실제 DB/API 조회와 양식 진입. 최종 mutation 없음 |
| 오래된 사건 실제 UI | 복구 실패 재현 | E-02 |
| 실제 업무 생성→점검 완료→정비 추천 전환 | Not Proven | 격리 DB 전체 흐름 검증 필요 |
| 판단 시간·클릭 수 개선 | Not Proven | 기준값과 개선 후 값 모두 미측정 |

## 2. 외부 레퍼런스

확인일: 2026-09-14. 다음은 공식 문서의 기능 설명을 요약한 것이다. 개별 제조 현장의 설정·운영 결과를 실증한 자료가 아니다. 문서 전체 복제 대신 원문 링크와 검토에 필요한 사실만 남긴다.

### R-01 IBM Maximo Monitor
- [Maximo Monitor overview](https://www.ibm.com/docs/en/masv-and-l/maximo-monitor/cd?topic=overview-maximo-monitor)
- 확인: 현재/과거 추세, 이상 감지, 경보를 Monitor에서 다루고 경보에서 Maximo Manage 서비스 요청을 연다.
- 시사점: 관측/경보와 후속 업무를 구분해 연결할 수 있다.
- 입증하지 않는 것: 모든 경보가 사람이 승인한 WorkOrder로만 연결된다는 보편 규칙, 우리 시스템에 별도 Case 테이블이 반드시 필요하다는 주장.
- 열람 한계: 검색에서 제공된 공식 문서 본문을 확인했으며 직접 open은 도구 오류가 발생했다.

### R-02 SAP Asset Performance Management
- [Creating a Monitoring Rule](https://help.sap.com/docs/SAP_APM/8c95dca44fda4d56a17f6494f421758d/baff10b05ab94ad1860abbe7ce5f2825.html)
- [What's New 2506–2508](https://help.sap.com/docs/SAP_APM/278625c0097f482e80b5c1f36db3afde/6c080da9d0cf4970ae91e053e1426b4c.html)
- 확인: 규칙 출력으로 alert/notification을 선택하고 서로 연결한다. 중복 억제 설정을 적용하며 반복 경보 횟수를 표시하는 기능도 문서화돼 있다.
- 시사점: 센서 이벤트마다 새 업무를 만들지 않고 반복을 묶는 규칙이 필요하다.
- 열람 한계: Help Portal 본문은 검색 결과를 통해 확인했으며 직접 open에서는 본문이 비어 있었다.

### R-03 SAP Predictive Asset Insights — 버전 한정 참고
- [Alerts, 2312](https://help.sap.com/docs/SAP_PREDICTIVE_ASSET_INSIGHTS/f50a0b24de8e4968a683e6f926bf1563/2e8aec125a5a40ca87dd957ee93195eb.html?version=2312)
- [Alert Deduplication, 2403](https://help.sap.com/docs/SAP_PREDICTIVE_ASSET_INSIGHTS/f50a0b24de8e4968a683e6f926bf1563/73602f49a91842ff9061da2af82f0407.html?locale=en-US&state=PRODUCTION&version=2403)
- 확인: 같은 설비/경보 유형의 중복 억제, 최초·최근 발생 시각, 억제 기간 종료 또는 완료 후 새 경보 생성. notification 완료에 따른 alert 자동 완료는 설정 조건이 있다.
- 한계: 과거 제품 버전의 동작을 최신 SAP APM 전체에 그대로 일반화하지 않는다.
- 시사점: 정상 관측과 업무 완료를 동일 사건으로 취급하는 자동 규칙은 별도 설계가 필요하다.

### R-04 Microsoft Dynamics 365 Asset Management
- [Create work orders from maintenance requests](https://learn.microsoft.com/en-us/dynamics365/supply-chain/asset-management/manage-maintenance-requests/create-work-order-from-a-maintenance-request)
- [Asset lifecycle states](https://learn.microsoft.com/en-us/dynamics365/supply-chain/asset-management/setup-for-objects/object-stages)
- 확인: maintenance request와 work order를 구분한다. 요청 하나는 작업지시 하나에 연결되지만 여러 요청이 하나의 작업지시에 포함될 수 있다. 작업지시 상태와 자산/정비 요청 상태 연동은 설정할 수 있다.
- 시사점: 업무 객체의 상태 전이는 명시적으로 관리하며 관측 건수와 작업 건수가 반드시 같을 필요는 없다.

## 3. 근거에서 도출한 제안과 트레이드오프

제품 공통의 보편 표준으로 확인된 것은 아니다. 우리 제안은 “관측 흐름과 업무 연속성을 분리하고 관계를 남긴다”이다.

| 대안 | 이점 | 비용/위험 | 판단 |
|---|---|---|---|
| 예측 1건=사건 1건 유지 | 단순한 identity 추적 | 반복 사건, 업무 분절, 시간 경과 후 복구 곤란 | 현 문제 해결에 부족 |
| 최소 이상 건 + 관측 참조 | 기존 WorkOrder 유지, 같은 건 재판단 | 잘못 묶음, 상태/버전 관리 추가 | 제안 |
| 복합 사건 상관분석 엔진 | 복합 고장 처리 가능 | 규칙·평가·운영 비용 증가 | 이번 범위 제외 |

- 같은 설비/유형만으로도 다른 부위 이상을 잘못 묶을 수 있다. 부위와 규칙 ID가 있는 경우 구분하고, 불명확하면 자동 병합하지 않는다.
- 관측 갱신마다 추천을 갈아끼우면 검토가 흔들린다. 선택 근거를 고정하고 중요한 변화만 재검토 사유로 표시한다.
- 오래된 관측을 이유로 모든 업무를 차단하지 않는다. 대신 액션별 필요한 근거를 서버 정책으로 명시해야 한다.
- 사람이 완료하면 안전한 확인 절차를 둘 수 있지만 미완료 건 관리 부담이 남는다.
- 사건 연결과 mutation 권한 판단은 deterministic backend 책임이다. Agent가 사건을 임의 병합하거나 업무를 자동 승인하지 않는다.

다음 작업: [최소 개선 계획](../plans/2026-09-14-decision-case-observation-separation-plan.md).

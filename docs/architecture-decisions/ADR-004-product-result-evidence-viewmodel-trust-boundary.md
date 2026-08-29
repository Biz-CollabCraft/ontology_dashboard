# ADR-004: Product Result / Evidence / ViewModel 신뢰 경계

- **상태**: Proposed (제안)
- **날짜**: 2026-08-29
- **결정자**: 팀 확인 필요
- **관련 문서**:
  - [`ADR-003-generator-runtime-prediction-result-and-backend-decision-ownership.md`](./ADR-003-generator-runtime-prediction-result-and-backend-decision-ownership.md)
  - [`../plans/ai-workflow/2026-08-29-002-product-result-evidence-materialization-plan.md`](../plans/ai-workflow/2026-08-29-002-product-result-evidence-materialization-plan.md)

---

## 1. 맥락 (Context)

ADR-003은 Generator가 runtime prediction batch를 만들고, Backend가 Product Result / Evidence /
Report / 사용자 알림 같은 product-facing 판단을 소유한다고 결정했다. 후속으로 필요한 것은 raw
prediction이 Backend에 도착한 뒤 화면과 Closed-loop가 어떤 신뢰 경계를 통해 소비하는지 명시하는
것이다.

AI Solutions Engineer / AI Data Integration / MLOps 계열 JD는 데이터 파이프라인, API 통합, 운영화,
모니터링, 비기술 이해관계자 커뮤니케이션을 반복해서 요구한다. 이 요구를 현재 프로젝트에 적용할 때
핵심은 대규모 DB 플랫폼 재설계가 아니라, AI 예측 결과가 업무 화면에서 신뢰 가능한 판단 근거로
쓰이도록 검증/승격/소비 경계를 고정하는 것이다.

---

## 2. 의사결정 (Decision)

Backend는 Generator raw 산출물을 화면이나 Closed-loop에 직접 노출하지 않는다. AI 결과는 다음
경계를 통과한 뒤 product-facing 화면에서 소비한다.

```text
Generator raw 산출
  -> Backend Diagnosis validation / promotion
  -> Product Result Artifact
  -> Evidence Projection / Evidence Package
  -> AssetDetailViewModel
  -> UI
```

세부 결정은 다음과 같다.

1. **Raw prediction과 Product Result 분리**
   - Generator batch, raw score, raw JSONL은 화면과 Closed-loop의 직접 입력이 아니다.
   - Backend Diagnosis가 schema, scope, checksum, lineage, model/dataset version을 검증한 뒤
     Product Result Artifact로 승격한다.

2. **Product Result와 Evidence의 shared lineage 보존**
   - Product Result Artifact는 `failure_probability`, `status_grade`, `top_factors`,
     `recommended_action` 같은 product-facing 판단을 소유한다.
   - Evidence Projection은 Product Result Artifact에서 파생되며 `artifact_reference`,
     `assessment`, `report_projection`, `provenance`, `limitations`를 보존한다.
   - `evaluation_truth`와 `hidden_truth`는 dashboard/API/LLM/Evidence 입력으로 사용하지 않는다.

3. **ViewModel은 read model composer로 유지**
   - `AssetDetailViewModel`은 저장 이벤트를 듣는 materialized table이 아니라 화면용 composer다.
   - UI는 raw payload를 직접 조합하지 않고 Backend가 구성한 typed ViewModel을 소비한다.
   - 결측 또는 미연결 근거는 `null`, `gap`, `warning`, `근거 부족`으로 표현하고 정상값으로 보정하지
     않는다.

4. **Transactional outbox는 후속 처리 요구가 있을 때만 적용**
   - Product Result / Evidence 저장 원자성이 필요한 경우 Backend repository transaction으로 묶는다.
   - 검색 인덱스, 집계, report cache invalidation, audit projection 같은 후속 소비자가 생기면
     `diagnosis.product_result.materialized` outbox event를 별도 PR로 추가한다.
   - exactly-once delivery는 주장하지 않는다. outbox는 at-least-once를 전제로 consumer idempotency가
     필요하다.

---

## 3. JD 대응 관점의 적용

| JD 요구 | 프로젝트 적용 | 제한 범위 |
| --- | --- | --- |
| Data Pipeline | raw 산출물을 검증 후 Product Result/Evidence로 승격 | 범용 ETL/ingestion framework 구축 제외 |
| API Integration | UI는 `AssetDetailViewModel` API를 소비하고 Closed-loop는 Product Result/Evidence 기준으로 진입 | Frontend raw payload 조합 금지 |
| MLOps / LLMOps | `model_version`, `dataset_version`, `source_sha256`, evidence reference로 판단 lineage 추적 | 모델 학습/배포 플랫폼 재구축 제외 |
| Operational Monitoring | `validation_status`, `rejection_reason`, `data_status`, `evidence.gaps`로 상태 표시 | full observability stack 제외 |
| Stakeholder Communication | 확률/feature를 위험도, 확인 이유, 권장 조치, 근거 부족으로 화면 언어화 | 내부 DB/outbox 용어의 사용자 노출 최소화 |

---

## 4. 결과 및 영향 (Consequences)

- AI 예측값이 곧바로 사용자 판단값이 되는 경로를 차단한다.
- Backend Diagnosis가 product-facing 판단과 Evidence lineage의 소유자로 남는다.
- UI는 raw Generator 산출물 대신 `AssetDetailViewModel`을 소비하므로 화면 문구와 근거 표시를 더
  일관되게 유지할 수 있다.
- Closed-loop mutation은 raw score가 아니라 Product Result / Evidence / RecommendationDecision
  기반으로 진입한다.
- DB/outbox/idempotency 세부는 면접 또는 설계 리뷰에서 심화 근거로 사용할 수 있지만, 기본
  포지셔닝은 “AI 결과를 업무 화면에 신뢰 가능하게 연결한 통합 설계”로 제한한다.

---

## 5. 한계와 후속 확인

- 이 ADR은 제안 상태다. 구현 완료, 테스트, 배포, 운영 검증을 의미하지 않는다.
- Product Result / Evidence 저장 원자성은 후속 repository 구현과 rollback 테스트가 필요하다.
- ViewModel은 여러 read source를 조합하므로 완전한 동일 시점 snapshot 보장은 별도 `as_of` 또는
  `snapshot_basis` 정책이 필요하다.
- Outbox 기반 후속 projection은 실제 consumer가 생긴 뒤 별도 PR에서 다룬다.
- 외부 JD 레퍼런스는 역할 요구를 해석하기 위한 참고이며, 프로젝트 구현 완료 증거가 아니다.

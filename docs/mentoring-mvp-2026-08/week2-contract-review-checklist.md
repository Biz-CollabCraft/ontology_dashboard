# Week 2 계약 검토 체크리스트

## 1. 목적

이 문서는 화면, 데이터·API와 LLM 담당자가 공통 계약의 미확정 항목을 같은
형식으로 검토하고 결정하기 위한 체크리스트다.

검토 기준:

- [요구사항 명세 초안](./week2-requirements-specification.md)
- [공통 스키마 정의서](./week2-schema-definition.md)
- [Canonical V3.1 필드 검증표](./v3.1-field-validation.md)
- [프로토타입 Gap 분석](./prototype-mvp-gap-analysis.md)

## 2. 답변 방법

각 항목에 다음 정보를 기록한다.

| 항목 | 작성 내용 |
|---|---|
| 선택 | 권장안 수락 또는 대안 |
| 변경 내용 | 필드·enum·화면·API가 달라지면 구체적으로 작성 |
| 근거 | 구현 제약, 사용자 요구 또는 데이터 계약 |
| 결정자 | 합의한 팀원 이름 |
| 결정일 | `YYYY-MM-DD` |

미응답 항목은 확정 계약으로 선언하지 않는다.

## 3. 공통 결정

### DEC-COM-01 — 개발 기준 저장소

- 권장안: `Biz-CollabCraft/ontology_dashboard`를 제품 문서와 구현의 기준
  저장소로 사용한다.
- 비교 프로토타입은 참고 구현으로만 사용한다.
- 영향 문서: 전체
- 상태: `결정 필요`

결정:

```text
선택:
변경 내용:
근거:
결정자:
결정일:
```

### DEC-COM-02 — MVP 사용자 명칭

- 권장안: 제품 계약은 `현장 담당자`, `생산 관리자`를 사용한다.
- 프로토타입의 엔지니어·관리자·임원 명칭은 최종 역할에 매핑한다.
- 영향 문서: 요구사항, 기능, 화면, API, 보고서
- 상태: `결정 필요`

결정:

```text
선택:
역할 매핑:
근거:
결정자:
결정일:
```

### DEC-COM-03 — 쓰기 기능 범위

- 권장안: Week 2 필수 흐름은 조회 중심으로 제한한다.
- Decision/Note는 구현 자산이 있더라도 `MVP 데모 Action` 또는 후속 범위로
  표시하고 자동 Work Order와 설비 제어는 제외한다.
- 영향 문서: 요구사항, 기능, API, 화면
- 상태: `결정 필요`

결정:

```text
선택: 조회 전용 / Decision 유지 / Note 유지 / 둘 다 유지
저장 여부:
권한:
결정자:
결정일:
```

## 4. 팀원1 — 화면 계약

### SCR-01 — 화면별 실제 필드

- 권장안: `AssetPredictionSummary`, `AssetDetail`, `OverviewSummary`를 화면
  공통 입력으로 사용한다.
- 확인 요청:
  - Overview 카드와 Top N 필드
  - Objects 목록·상세 필드
  - Operations 생산·정비 필드
  - Executive Report 필드
- 반영 위치: 스키마, 기능, API, MVP 설계
- 상태: `확인 필요`

답변:

```text
누락 필드:
제외 필드:
화면 전용 계산값:
담당자:
결정일:
```

### SCR-02 — 상태 명칭과 표현

- 권장안:
  - `normal` → 정상
  - `attention` → 관심
  - `warning` → 경고
  - `critical` → 심각
- `주의`, `위험`을 같은 enum의 다른 이름으로 혼용하지 않는다.
- 색상과 텍스트를 함께 사용한다.
- 반영 위치: 스키마, 기능, MVP 설계
- 상태: `확인 필요`

답변:

```text
선택: 권장안 수락 / 대안
대안 문구·색상:
담당자:
결정일:
```

### SCR-03 — 필터·정렬·이동

- 권장안:
  - 필터: `site_id`, `cell_id`, `asset_type`, `status_grade`, 기간
  - 위험 목록: 등급 우선 후 `failure_probability` 내림차순
  - 화면 이동: `asset_id`와 필터 조건 유지
- 반영 위치: 기능, API, MVP 설계
- 상태: `확인 필요`

답변:

```text
추가·삭제 필터:
정렬 기준:
URL/상태 유지 방식:
담당자:
결정일:
```

### SCR-04 — 화면 상태

- 권장안: `loading`, `empty`, `error`, `stale`, `permission`을 구분한다.
- fallback 사용 시 정상 Canonical 결과처럼 보이지 않도록 경고한다.
- 반영 위치: 기능, API, MVP 설계
- 상태: `확인 필요`

답변:

```text
상태별 문구:
재시도 동작:
fallback 표시:
담당자:
결정일:
```

## 5. 팀원3 — 데이터·API 계약

### API-01 — API 구조

- 권장안: 화면마다 중복 API를 새로 만들기 전에 목록·상세·집계 책임을 다음과
  같이 고정한다.
  - 전체/필터 목록
  - 자산 상세
  - 센서 history
  - Operations 생산·정비 목록
  - Executive Report용 검증 집계
- 기존 구현 API가 있으면 경로를 유지하고 응답 계약만 보강한다.
- 반영 위치: API, 기능, MVP 설계
- 상태: `확인 필요`

답변:

```text
목록 경로:
상세 경로:
History 경로:
Operations 경로:
Report 입력 경로:
담당자:
결정일:
```

### API-02 — 목록 pagination

- 권장안: `page`, `size`와 `total`을 사용하는 page 방식으로 시작한다.
- 최대 `size`와 기본 정렬을 API 명세에 고정한다.
- 반영 위치: 스키마, API
- 상태: `확인 필요`

답변:

```text
방식: page / cursor
기본 크기:
최대 크기:
기본 정렬:
담당자:
결정일:
```

### API-03 — 위험등급 산출 책임

- 권장안: API가 임계값을 재계산하지 않고 Result Artifact의 `status_grade`를
  그대로 소비한다.
- 임계값 비교 기능은 별도 Analysis 화면 없이 후속 모델링 계약으로 관리한다.
- 반영 위치: 스키마, API, 기능
- 상태: `확인 필요`

답변:

```text
산출 주체:
현재 임계값:
버전 표기 방식:
담당자:
결정일:
```

### API-04 — 기준시각과 stale

- 권장안:
  - 목록과 집계는 하나의 latest Artifact snapshot을 기준으로 한다.
  - 자산별 센서는 `observed_at <= snapshot as_of`인 최신 관측을 사용한다.
  - stale 허용 시간은 관측 주기와 replay 정책을 기준으로 팀원3이 확정한다.
- 반영 위치: 스키마, API, 기능
- 상태: `확인 필요`

답변:

```text
snapshot 기준:
센서 결합 기준:
stale 임계시간:
시간대:
담당자:
결정일:
```

### API-05 — 결합 필드와 provenance

- 권장안:
  - `site_id`, `cell_id`는 Asset 결합값으로 표시한다.
  - `dataset_version`, `model_version`은 Artifact provenance에서 가져온다.
  - 원본 `provenance`는 상세·보고서 입력에서 보존한다.
- 반영 위치: 스키마, API, 보고서
- 상태: `확인 필요`

답변:

```text
중첩/평탄화 방식:
목록 provenance 범위:
상세 provenance 범위:
담당자:
결정일:
```

### API-06 — fallback

- 권장안: Canonical을 기본으로 사용하며 fallback은 데모 복구 상황에만
  허용한다. 응답에 source와 warning을 반드시 포함한다.
- 반영 위치: 스키마, API, 기능, 보고서
- 상태: `확인 필요`

답변:

```text
fallback 허용 여부:
발동 조건:
응답 필드:
화면 경고:
담당자:
결정일:
```

## 6. 팀원4 — LLM 보고서 계약

### RPT-01 — 입력 JSON

- 권장안: LLM에는 검증된 집계, 상위 위험 설비, 관련 Result Artifact와
  provenance만 전달한다.
- Canonical 원천 전체와 evaluation truth는 입력하지 않는다.
- 반영 위치: 스키마, 보고서, API
- 상태: `확인 필요`

답변:

```text
입력 객체명:
필수 필드:
선택 필드:
최대 설비 수:
담당자:
결정일:
```

### RPT-02 — 출력 JSON

- 권장안: 자유 문자열 하나가 아니라 섹션별 구조화 JSON을 반환한다.
- 최소 섹션 후보:
  - 보고 기준
  - 전체 상태 요약
  - 상위 위험 설비
  - 주요 위험 요인
  - 생산·정비 영향
  - 권장 조치
  - 주의사항과 한계
- 반영 위치: 스키마, 보고서, API, 화면
- 상태: `확인 필요`

답변:

```text
출력 schema:
필수 섹션:
근거 참조 필드:
담당자:
결정일:
```

### RPT-03 — 문장 규칙

- 권장안:
  - 고장 확정, 인과 확정, 자동 실행을 표현하지 않는다.
  - `근거`, `후보`, `가설`, `점검 필요` 표현을 사용한다.
  - 입력에 없는 비용, 손실, 절감액과 수치를 생성하지 않는다.
  - 상태·확률·버전을 변경하거나 반올림으로 왜곡하지 않는다.
- 반영 위치: 보고서, 기능, 테스트
- 상태: `확인 필요`

답변:

```text
추가 금지 표현:
필수 고지 문구:
수치 표시 규칙:
담당자:
결정일:
```

### RPT-04 — 실패 대체 응답

- 권장안: `LLM → deterministic summary → template` 순서로 fallback한다.
- fallback 결과도 입력 provenance와 생성 방식을 표시한다.
- 반영 위치: 스키마, 보고서, API, 화면
- 상태: `확인 필요`

답변:

```text
fallback 단계:
오류 응답:
화면 표시:
담당자:
결정일:
```

## 7. 검토 완료 조건

- 모든 `확인 필요` 항목에 결정자와 결정일이 있다.
- 변경된 필드가 `week2-schema-definition.md`에 반영된다.
- 화면 필드와 API JSON key가 일치한다.
- API와 LLM이 같은 Result Artifact 의미를 사용한다.
- 결정 결과가 기능·API·보고서·MVP 설계 명세의 입력으로 연결된다.


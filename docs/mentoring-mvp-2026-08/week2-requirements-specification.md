# Week 2 요구사항 명세 초안

## 기준

이 문서는 Canonical V3.1 기반 예지보전 대시보드의 제품 방향 초안이다.
필드 근거는 [V3.1 검증표](./v3.1-field-validation.md), 프로토타입과의 차이는
[Gap 분석](./prototype-mvp-gap-analysis.md)을 따른다.

## 사용자

- 현장 담당자: 위험 설비와 센서·예측 근거를 확인하고 점검 대상을 판단한다.
- 생산 관리자: 설비 위험과 생산·정비 현황을 함께 보고 대응 우선순위를 판단한다.

프로토타입의 `실무 엔지니어`, `관리자·임원` 역할과 최종 대응 관계는 팀 합의가
필요하다.

## MVP 화면

1. Overview
2. Objects
3. Operations
4. Executive Report

## 공통 요구사항

| ID | 요구사항 | 완료 기준 |
|---|---|---|
| CM-01 | 모든 화면은 같은 자산 ID와 기준시각을 사용한다. | 같은 조건에서 화면 간 값이 일치한다. |
| CM-02 | 원천 데이터와 파생 Result Artifact를 구분한다. | provenance와 출처를 확인할 수 있다. |
| CM-03 | 위험 등급은 `normal`, `attention`, `warning`, `critical`만 사용한다. | 다른 enum을 반환하지 않는다. |
| CM-04 | 색상과 함께 정상·관심·경고·심각 문구를 표시한다. | 색상 없이도 상태를 식별할 수 있다. |
| CM-05 | 데이터·모델·Artifact schema 버전을 표시한다. | 화면 또는 상세에서 세 버전을 확인한다. |
| CM-06 | loading, empty, error, stale, permission 상태를 구분한다. | 상태별 UI와 오류 응답이 정의된다. |
| CM-07 | 평가 truth를 일반 화면/API에 노출하지 않는다. | 계약 테스트가 노출을 차단한다. |

## 화면별 요구사항

### Overview

- 기준시각과 데이터·모델 버전
- 전체·가동·비가동 설비 수
- 위험 등급별 설비 수
- 유형별 현황
- 상위 위험 설비
- 생산·정비 요약
- 선택 설비의 Objects 이동

등급별 합은 전체 설비 수와 같고, 같은 필터의 Operations 집계와 일치해야 한다.

### Objects

- 자산 ID·사이트·셀·유형·가동·위험 필터
- 자산 기본정보
- Compressor/CNC별 최신 센서와 추세
- 고장 확률, 등급, 신뢰도, 24시간 horizon
- Artifact Top-3 판단 근거
- 연결 topology
- 정비 이력
- 원천/파생 구분과 provenance

`predicted_failure_type`은 PWF/HDF/OSF/TWF 고장 모드로 표현하지 않는다.

### Operations

- 기간별 생산 작업과 완료 현황
- 제품·CNC·시작·완료·가공시간·공구마모 증가량
- 기간별 정비 이력과 공구 교체 여부
- 생산/정비 대상 자산의 현재 위험 등급
- 기간·사이트·셀·자산유형 필터
- 자산의 Objects 이동

프로토타입의 Event Queue, Decision, Note Activity를 MVP에 포함할지는 합의가
필요하다. 비용·손실·인과 효과는 근거 없이 생성하지 않는다.

### Executive Report

- 보고 기간·생성시각·버전
- 전체·가동·위험 설비와 생산·정비 건수
- 위험 등급 분포
- 상위 위험 설비와 정책 권고
- 데이터로 검증 가능한 시사점
- 합성 데이터와 예측 결과의 한계
- LLM 실패 시 deterministic/template fallback

동일 조건의 Overview, Objects, Operations와 수치가 일치해야 한다.

## 제외 또는 합의 필요

### 유지할 제외 범위

- Analysis, Agent, Admin, Modeling Workbench
- 자동 설비 정지와 자동 Work Order
- 자동 생산계획 변경
- 평가 truth의 운영 노출

### 팀 합의 필요

- 역할의 최종 명칭과 Decision/Note 권한
- 로그인·RBAC의 MVP 포함 여부
- Operations에서 생산·정비와 Event Activity의 우선순위
- 위험등급 임계값과 산출 책임
- API pagination·stale 기준·결합 필드
- LLM 입출력 JSON과 금지 표현
- Gold Fixture fallback 허용 정책

## 대표 흐름

1. Overview에서 전체 위험과 기준시각을 확인한다.
2. 위험 설비를 선택해 Objects에서 센서와 Top-3 근거를 확인한다.
3. Operations에서 관련 생산·정비 현황을 확인한다.
4. Executive Report에서 같은 집계와 한계를 확인한다.


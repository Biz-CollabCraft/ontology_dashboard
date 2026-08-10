"""
diagnosis_schema.py

담당 기능:
- 진단(diagnosis) 도메인의 API 입출력 Pydantic 스키마 모델을 정의한다.
  DiagnosisPredictRequest, DiagnosisPredictResponse, DiagnosisStatusResponse 모델이 속한다.

입력:
- 없음 (데이터 모델 명세).

출력:
- diagnosis_router.py 및 diagnosis_service.py에서 소비하는 Pydantic DTO.

의존 모듈:
- diagnosis_router.py, diagnosis_service.py

예외/경계 상황:
- 단독 실행이 성립하지 않는 데이터 구조 정의 파일이다.

설계 원칙과의 연결:
- docs/architecture.md 1장 컨벤션 {도메인}_{계층}.py 규칙을 따른다.
"""

import sys


class DiagnosisPredictRequest:
    """진단 요청 DTO 스켈레톤"""

    pass


class DiagnosisPredictResponse:
    """진단 응답 DTO 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] diagnosis_schema.py는 단독 실행 대상이 아닙니다. "
        "다른 모듈에서 import하여 사용하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

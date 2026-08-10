"""
diagnosis_router.py

담당 기능:
- 실시간 설비 진단(diagnosis) 및 고장 위험도 추론 엔드포인트를 제공한다.
  POST /api/v1/diagnosis/predict, GET /api/v1/diagnosis/status 등의 경로를 매핑하여
  요청 유효성을 검증한 후 diagnosis_service로 처리를 넘긴다.

입력:
- DiagnosisPredictRequest (설비 ID, 실시간 센서 파라미터 셋 등).

출력:
- DiagnosisPredictResponse (고장 확률, 잔여 수명 RUL 척도 등).

의존 모듈:
- diagnosis_service.py (추론 실행 위임)
- diagnosis_schema.py (입출력 DTO 정의)
- diagnosis_exception.py (도메인 예외 핸들링)

예외/경계 상황:
- 단독 실행이 성립하지 않는 라우터 모듈이다.

설계 원칙과의 연결:
- docs/architecture.md 4장의 'diagnosis' 도메인 역할을 담당한다.
"""

import sys
from fastapi import APIRouter

router = APIRouter(prefix="/diagnosis", tags=["Diagnosis"])


class DiagnosisRouter:
    """Diagnosis 라우터 클래스 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] diagnosis_router.py는 단독 실행 대상이 아닙니다. "
        "app.main:app 컨텍스트에서 실행하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

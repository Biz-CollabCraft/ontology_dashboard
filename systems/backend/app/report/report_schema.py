"""
report_schema.py

담당 기능:
- 리포트 도메인 요청/응답 Pydantic 스키마 정의 (ReportGenerateRequest, ReportResponse).

입력:
- 데이터 명세.

출력:
- DTO 클래스들.

의존 모듈:
- report_router.py, report_service.py

예외/경계 상황:
- 단독 실행 비대상 파일이다.

설계 원칙과의 연결:
- docs/architecture.md 1장 명명 규칙 준수.
"""

import sys


class ReportGenerateRequest:
    """리포트 생성 요청 DTO 스켈레톤"""

    pass


class ReportResponse:
    """리포트 응답 DTO 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] report_schema.py는 단독 실행 대상이 아닙니다. "
        "다른 모듈에서 import하여 사용하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

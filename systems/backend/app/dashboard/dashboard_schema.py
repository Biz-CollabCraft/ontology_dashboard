"""
dashboard_schema.py

담당 기능:
- 대시보드 도메인 요청/응답 Pydantic 스키마 (DashboardSummaryResponse 등).

입력:
- 데이터 명세.

출력:
- DTO 모델들.

의존 모듈:
- dashboard_router.py, dashboard_service.py

예외/경계 상황:
- 단독 실행 비대상 파일이다.

설계 원칙과의 연결:
- docs/architecture.md 1장 명명 규칙 준수.
"""

import sys


class DashboardSummaryResponse:
    """대시보드 요약 응답 DTO 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] dashboard_schema.py는 단독 실행 대상이 아닙니다. "
        "다른 모듈에서 import하여 사용하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

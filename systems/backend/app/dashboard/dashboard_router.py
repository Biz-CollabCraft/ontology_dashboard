"""
dashboard_router.py

담당 기능:
- 프론트엔드 대시보드 화면에 필요한 종합 설비 현황, 진단 요약, 알림 지표 API 엔드포인트를 제공한다.
  GET /api/v1/dashboard/summary 등의 통합 경로를 제공한다.

입력:
- HTTP Request (대시보드 필터 조건).

출력:
- DashboardSummaryResponse (조합된 대시보드 현황 데이터).

의존 모듈:
- dashboard_service.py (공개 application/query/read-model 결과를 조합)
- dashboard_schema.py

예외/경계 상황:
- 단독 실행 비대상 라우터 파일이다.

설계 원칙과의 연결:
- docs/architecture.md의 application/read-model composition 및 domain dependency rule을 지킨다.
"""

import sys
from fastapi import APIRouter

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class DashboardRouter:
    """Dashboard 라우터 클래스 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] dashboard_router.py는 단독 실행 대상이 아닙니다. "
        "app.main:app 컨텍스트에서 실행하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

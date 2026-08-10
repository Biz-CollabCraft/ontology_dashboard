"""
report_router.py

담당 기능:
- 진단 결과 기반 리포트 생성 및 조회 API 엔드포인트를 라우팅한다.
  GET /api/v1/report/{id}, POST /api/v1/report/generate 등을 다룬다.

입력:
- ReportGenerateRequest / HTTP 경로 파라미터.

출력:
- ReportResponse (리포트 본문 및 통계 템플릿 정보).

의존 모듈:
- report_service.py, report_schema.py

예외/경계 상황:
- 단독 실행 비대상 파일이다.

설계 원칙과의 연결:
- docs/architecture.md 4장의 'report' 도메인 역할을 적용한다.
"""

import sys
from fastapi import APIRouter

router = APIRouter(prefix="/report", tags=["Report"])


class ReportRouter:
    """Report 라우터 클래스 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] report_router.py는 단독 실행 대상이 아닙니다. "
        "app.main:app 컨텍스트에서 실행하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

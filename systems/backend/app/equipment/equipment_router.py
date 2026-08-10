"""
equipment_router.py

담당 기능:
- 설비(equipment) 마스터 정보의 조회/등록/수정 요청을 받아 처리하는 FastAPI APIRouter 엔드포인트를 정의한다.
  GET /api/v1/equipment, GET /api/v1/equipment/{id}, POST /api/v1/equipment 등의 경로를 바인딩하고
  요청 유효성 검증 후 equipment_service로 위임한다.

입력:
- FastAPI HTTP Request (Path parameter, Query parameter, EquipmentCreateRequest, EquipmentUpdateRequest).

출력:
- HTTP Response (EquipmentResponse, EquipmentListResponse Pydantic 모델 및 HTTP 상태 코드).

의존 모듈:
- equipment_service.py (비즈니스 로직 위임)
- equipment_schema.py (요청/응답 DTO 파싱)
- equipment_exception.py (도메인 예외 핸들링)

예외/경계 상황:
- 이 모듈은 FastAPI 라우터 정의 파일로서 uvicorn 및 app/main.py의 실행 컨텍스트가 필요하므로 단독 실행이 성립하지 않는다.

설계 원칙과의 연결:
- docs/architecture.md 4장의 'systems/backend/app/equipment' 도메인 레이아웃 및명명 컨벤션을 따른다.
"""

import sys
from fastapi import APIRouter

router = APIRouter(prefix="/equipment", tags=["Equipment"])


class EquipmentRouter:
    """Equipment 라우터 객체 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] equipment_router.py는 단독 실행 대상이 아닙니다. "
        "app.main:app 컨텍스트에서 실행하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

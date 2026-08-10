"""
equipment_schema.py

담당 기능:
- 설비(equipment) 도메인에서 API 요청/응답에 쓰이는 Pydantic 스키마를 정의한다.
  EquipmentCreateRequest(등록 요청), EquipmentUpdateRequest(수정 요청),
  EquipmentResponse(조회/응답)를 포함할 예정이다.

입력:
- 없음(이 모듈 자체는 실행 로직이 아니라 데이터 구조 정의).

출력:
- equipment_router.py, equipment_service.py가 import해서 사용하는 Pydantic 모델 클래스들.

의존 모듈:
- equipment_router.py(요청 파싱), equipment_service.py(비즈니스 로직 입출력 검증)에서
  소비된다.

예외/경계 상황:
- 이 모듈은 데이터 구조 정의만 담당하므로 단독 실행이 성립하지 않는다. 아래
  __main__ 블록은 실수로 직접 실행했을 때 이를 알리기 위한 것이다.

설계 원칙과의 연결:
- docs/architecture.md 1장 컨벤션에 따라 이 파일명은 {도메인}_{계층}.py 규칙을 따른다.

(실제 구현은 별도 작업에서 진행 예정)
"""

import sys


class EquipmentCreateRequest:
    """Equipment 생성 요청 DTO 스켈레톤"""

    pass


class EquipmentUpdateRequest:
    """Equipment 수정 요청 DTO 스켈레톤"""

    pass


class EquipmentResponse:
    """Equipment 응답 DTO 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] equipment_schema.py는 단독 실행 대상이 아닙니다. "
        "다른 모듈에서 import하여 사용하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

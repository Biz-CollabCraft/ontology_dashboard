"""
equipment_exception.py

담당 기능:
- 설비 도메인 내 비즈니스 로직 수행 중 발생할 수 있는 커스텀 예외 클래스들을 정의한다.
  EquipmentNotFoundError, EquipmentAlreadyExistsError, InvalidEquipmentStateError 등을 포함한다.

입력:
- 예외 상황 메시지 문자열 및 에러 코드.

출력:
- FastAPI 글로벌 예외 핸들러에서 캡처할 예외 인스턴스.

의존 모듈:
- equipment_service.py, equipment_repository.py 등 도메인 제반 계층에서 발생시킴.

예외/경계 상황:
- 단독 실행이 불가한 예외 구조 정의 파일이다.

설계 원칙과의 연결:
- .agents/standards/api.md 예외 규격 및 docs/architecture.md 명명 컨벤션을 적용한다.
"""

import sys


class EquipmentNotFoundError(Exception):
    """설비 없음 예외 클래스 스켈레톤"""

    pass


if __name__ == "__main__":
    print(
        "[ERROR] equipment_exception.py는 단독 실행 대상이 아닙니다. "
        "다른 모듈에서 import하여 사용하십시오.",
        file=sys.stderr,
    )
    sys.exit(1)

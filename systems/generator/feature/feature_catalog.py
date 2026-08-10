"""
feature_catalog.py

담당 기능:
- feature_builder에 의해 생성된 Feature들의 카탈로그 메타데이터를 관리한다.
  각 Feature 컬럼의 통계적 정의, 센서 출처, 버전 정보, 차원 정보 등을 명세화하여
  model_training 단계에서 올바른 Feature 조합을 선택하도록 지원한다.

입력:
- 등록할 Feature 메타데이터 딕셔너리 (`dict`) 및 카탈로그 쿼리 조건.

출력:
- Feature 메타데이터 명세 목록 (`FeatureCatalogEntry` 리스트).

의존 모듈:
- feature_builder.py에서 생성된 Feature의 스토리지 및 사양 정보 수용.

예외/경계 상황:
- 존재하지 않는 Feature ID를 조회할 경우 `FeatureNotFoundError`를 발생시킨다.

설계 원칙과의 연결:
- docs/architecture.md 3장의 'feature_catalog' 스펙을 적용한다.
"""


class FeatureCatalog:
    """Feature 메타데이터 카탈로그 관리 클래스 스켈레톤"""

    pass


def _self_test() -> None:
    """
    이 모듈을 단독 실행했을 때 수행되는 기능 테스트.
    실제 검증 로직은 이 모듈의 실제 구현 작업에서 채운다.
    """
    print("[SELF-TEST] feature_catalog.py - 아직 테스트 로직이 구현되지 않았습니다.")


if __name__ == "__main__":
    _self_test()

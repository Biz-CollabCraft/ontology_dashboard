"""
model_registry.py

담당 기능:
- 학습이 완료된 모델을 **versioned Model Artifact**로 publish하고 immutable 버전과 manifest를 관리한다.
- publish manifest는 최소 `artifact_type`, `artifact_schema_version`, `model_id`, `model_version`,
  `dataset_version`, `feature_schema_version`, `created_at`, `training_config`, `metrics`, `checksum`,
  `provenance`, `compatibility`, `artifact_files` 메타데이터를 갖는 계약을 따른다.
- `model_store/`는 local filesystem adapter의 예시일 뿐이며 Backend와의 시스템 경계 계약은 물리 경로가 아니라 manifest다.

입력:
- `TrainedModelArtifact` 및 모델 이름/버전 식별자 (`str`).

출력:
- publish 완료된 immutable Model Artifact 식별자/URI 및 manifest 메타데이터.

의존 모듈:
- model_training.py (학습 결과물 전달받음)

예외/경계 상황:
- 동일 immutable version을 덮어쓰려 하거나 checksum/manifest 생성이 실패하거나 publish target에 기록할 수 없으면 `ModelRegistryError`를 발생시킨다.
- incomplete artifact가 consumer에 노출되지 않도록 atomic publish 또는 동등한 보장을 사용한다.

설계 원칙과의 연결:
- docs/architecture.md의 versioned Model Artifact contract와 path-independent publish 원칙을 구현한다.
"""


class ModelRegistry:
    """모델 버저닝 및 저장소 등록 관리 클래스 스켈레톤"""

    pass


def _self_test() -> None:
    """
    이 모듈을 단독 실행했을 때 수행되는 기능 테스트.
    실제 검증 로직은 이 모듈의 실제 구현 작업에서 채운다.
    """
    print("[SELF-TEST] model_registry.py - 아직 테스트 로직이 구현되지 않았습니다.")


if __name__ == "__main__":
    _self_test()

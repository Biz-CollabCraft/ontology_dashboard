GUIDES = {
    "MAPPING_CHECKSUM_MISMATCH": ("Mapping checksum 불일치", ["발행된 Mapping checksum을 다시 확인합니다.", "검증된 신규 버전을 발행합니다."], False),
    "MANAGED_ASSET_CHECKSUM_MISMATCH": ("계약 자산 checksum 불일치", ["정본 파일과 Registry checksum을 비교합니다.", "손상된 버전을 활성화하지 않습니다."], False),
    "PIPELINE_JOB_CONFLICT": ("Pipeline Job 충돌", ["동일 작업의 실행 상태를 확인합니다.", "기존 작업 완료 후 다시 요청합니다."], True),
    "PIPELINE_JOB_NOT_CANCELLABLE": ("취소 불가능한 Job 상태", ["현재 Job 상태와 checkpoint를 확인합니다."], False),
    "MODEL_SELECTION_CONFLICT": ("모델 선택 충돌", ["현재 selected 포인터를 다시 조회합니다."], True),
    "ACTIVE_MODEL_SET_ACTIVATION_FAILED": ("Active Model Set 활성화 실패", ["대상 Artifact 무결성을 확인합니다.", "검증된 이전 revision으로 rollback합니다."], False),
    "MODEL_ARTIFACT_INTEGRITY_ERROR": ("Model Artifact 무결성 오류", ["Manifest와 파일 checksum을 확인합니다.", "손상된 버전을 선택하지 않습니다."], False),
    "SYSTEM_AUDIT_WRITE_FAILED": ("감사 기록 저장 실패", ["DB 쓰기 상태와 migration 적용 여부를 확인합니다."], True),
    "SYSTEM_LOG_EXPORT_LIMIT_EXCEEDED": ("Export 제한 초과", ["조회 기간 또는 필터 범위를 줄입니다."], False),
    "SYSTEM_LOG_EXPORT_FAILED": ("로그 Export 실패", ["Export 저장소 권한과 여유 공간을 확인합니다."], True),
}


def recovery_guide(error_code: str) -> dict:
    title, actions, retry = GUIDES.get(error_code, ("알 수 없는 운영 오류", ["요청 ID와 오류 코드를 보존하고 담당자에게 전달합니다.", "자동 복구를 추측하지 않습니다."], False))
    return {"error_code": error_code, "title": title, "operator_actions": actions,
            "automatic_retry_allowed": retry, "destructive_action_required": False,
            "related_resource_types": []}

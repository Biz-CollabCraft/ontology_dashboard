from .system_operation_exception import SystemOperationError


class MappingDraftError(SystemOperationError):
    pass


class MappingDraftNotFound(MappingDraftError):
    def __init__(self): super().__init__(404, "MAPPING_DRAFT_NOT_FOUND", "Mapping Draft를 찾을 수 없습니다.")


class MappingDraftConflict(MappingDraftError):
    def __init__(self, code="MAPPING_DRAFT_REVISION_CONFLICT", message="Mapping Draft revision이 변경되었습니다."): super().__init__(409, code, message)


class MappingDraftInvalid(MappingDraftError):
    def __init__(self, code: str, message: str): super().__init__(422, code, message)

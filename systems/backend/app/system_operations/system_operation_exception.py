class SystemOperationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class OperationalAssetNotFound(SystemOperationError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(404, "SYSTEM_ASSET_NOT_FOUND", f"운영 자산을 찾을 수 없습니다: {asset_id}")

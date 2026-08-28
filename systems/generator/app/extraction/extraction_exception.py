"""Domain exceptions for Generator Protocol Extraction."""

from __future__ import annotations

from typing import Any, Optional


class ExtractionError(Exception):
    """Base exception for all Extraction domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "EXTRACTION_ERROR",
        status_code: int = 500,
        details: Optional[list[dict[str, Any]]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []
        self.retryable = retryable


class ExtractionRequestInvalidError(ExtractionError):
    """Raised when extraction request payload fails schema or business validation."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_REQUEST_INVALID",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceNotFoundError(ExtractionError):
    """Raised when input source protocol file cannot be found."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_NOT_FOUND",
            status_code=404,
            details=details,
            retryable=False,
        )


class ExtractionSourcePathUnsupportedError(ExtractionError):
    """Raised when source_uri contains directory traversal, unsafe characters, or outside allowed root."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_PATH_UNSUPPORTED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceManifestRequiredError(ExtractionError):
    """Raised when source_run_manifest_uri is missing or empty."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_MANIFEST_REQUIRED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceManifestInvalidError(ExtractionError):
    """Raised when source run manifest fails schema or content validation."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_MANIFEST_INVALID",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceNotFinalizedError(ExtractionError):
    """Raised when source run manifest status is not finalized/completed."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_NOT_FINALIZED",
            status_code=409,
            details=details,
            retryable=True,
        )


class ExtractionSourceDescriptorMismatchError(ExtractionError):
    """Raised when source file SHA-256, size, or role does not match manifest descriptor."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_DESCRIPTOR_MISMATCH",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceIncompleteError(ExtractionError):
    """Raised when source file is actively being written or last line is incomplete/torn JSONL."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_INCOMPLETE",
            status_code=409,
            details=details,
            retryable=True,
        )


class ExtractionSourceIntegrityError(ExtractionError):
    """Raised when source file is finalized but contains broken or corrupted record."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_INTEGRITY_ERROR",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceChecksumMismatchError(ExtractionError):
    """Raised when declared source_sha256 does not match actual calculated file checksum."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_CHECKSUM_MISMATCH",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionProtocolUnsupportedError(ExtractionError):
    """Raised when protocol_version or source_schema_version is unsupported."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PROTOCOL_UNSUPPORTED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingNotFoundError(ExtractionError):
    """Raised when specified mapping_id / mapping_version file cannot be found."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_NOT_FOUND",
            status_code=404,
            details=details,
            retryable=False,
        )


class ExtractionMappingNotApprovedError(ExtractionError):
    """Raised when mapping table status is not 'approved' (e.g. draft, deprecated)."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_NOT_APPROVED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingChecksumMismatchError(ExtractionError):
    """Raised when mapping table definition checksum does not match declared mapping_sha256."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_CHECKSUM_MISMATCH",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSchemaFingerprintMismatchError(ExtractionError):
    """Raised when source schema fingerprint does not match mapping expected fingerprint."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SCHEMA_FINGERPRINT_MISMATCH",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionRecordRejectedError(ExtractionError):
    """Raised when record-level extraction validation fails and cannot be isolated."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_RECORD_REJECTED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionDatasetConflictError(ExtractionError):
    """Raised when target dataset version already exists with different contents (overwrite forbidden)."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_DATASET_CONFLICT",
            status_code=409,
            details=details,
            retryable=False,
        )


class ExtractionNoValidObservationsError(ExtractionError):
    """Raised when extraction yielded 0 valid canonical observation records."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_NO_VALID_OBSERVATIONS",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionAlreadyRunningError(ExtractionError):
    """Raised when another extraction run is already in progress for the target dataset."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_ALREADY_RUNNING",
            status_code=409,
            details=details,
            retryable=True,
        )


class ExtractionLockLostError(ExtractionError):
    """Raised when single-writer lock lease is lost during execution."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_LOCK_LOST",
            status_code=409,
            details=details,
            retryable=True,
        )


class ExtractionIdempotencyConflictError(ExtractionError):
    """Raised when same idempotency_key is reused with different request payload."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_IDEMPOTENCY_CONFLICT",
            status_code=409,
            details=details,
            retryable=False,
        )


class ExtractionRequestInProgressError(ExtractionError):
    """Raised when same idempotency_key is already running concurrently."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_REQUEST_IN_PROGRESS",
            status_code=409,
            details=details,
            retryable=True,
        )


class ExtractionIntegrityError(ExtractionError):
    """Raised when atomic publishing or manifest checksum verification fails."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_INTEGRITY_ERROR",
            status_code=500,
            details=details,
            retryable=False,
        )


class ExtractionPublishFailedError(ExtractionError):
    """Raised when atomic rename or filesystem staging commit fails."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PUBLISH_FAILED",
            status_code=500,
            details=details,
            retryable=False,
        )


class ExtractionFeatureNotImplementedError(ExtractionError):
    """Raised when an unsupported transformation or conversion feature is requested."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_FEATURE_NOT_IMPLEMENTED",
            status_code=501,
            details=details,
            retryable=False,
        )


class ExtractionGenDataRootNotConfiguredError(ExtractionError):
    """Raised when GEN_DATA_OUTPUT_DIR is not configured in environment or settings."""

    def __init__(self, message: str = "GEN_DATA_OUTPUT_DIR is not configured", details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_GEN_DATA_ROOT_NOT_CONFIGURED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionGenDataRootInvalidError(ExtractionError):
    """Raised when GEN_DATA_OUTPUT_DIR or sensor_root path is invalid or not a directory."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_GEN_DATA_ROOT_INVALID",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionGenDataSourcePathUnsupportedError(ExtractionError):
    """Raised when discovered stream file or folder violates structure, bounds, or security invariants."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_GEN_DATA_SOURCE_PATH_UNSUPPORTED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionGenDataSourceDiscoveryFailedError(ExtractionError):
    """Raised when discovering gen_data sensor streams fails unexpectedly (e.g. permission error)."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_GEN_DATA_SOURCE_DISCOVERY_FAILED",
            status_code=500,
            details=details,
            retryable=False,
        )


class ExtractionSourceOffsetInvalidError(ExtractionError):
    """Raised when start_offset is negative, beyond file size, or violates offset bounds."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_OFFSET_INVALID",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionSourceOffsetNotAlignedError(ExtractionError):
    """Raised when start_offset does not align to the end of a previous complete line (missing preceding newline)."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_SOURCE_OFFSET_NOT_ALIGNED",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingSourceFormatMismatchError(ExtractionError):
    """Raised when mapping table source_format does not match expected source format."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_SOURCE_FORMAT_MISMATCH",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingDuplicateSourceFieldError(ExtractionError):
    """Raised when mapping table contains duplicate declarations of the same source_field."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_DUPLICATE_SOURCE_FIELD",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingTargetCollisionError(ExtractionError):
    """Raised when two or more distinct source_fields map to the same target_field."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_TARGET_COLLISION",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingReservedTargetFieldError(ExtractionError):
    """Raised when mapping target_field collides with reserved Identity or Provenance fields."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_RESERVED_TARGET_FIELD",
            status_code=422,
            details=details,
            retryable=False,
        )


class ExtractionMappingEmptyError(ExtractionError):
    """Raised when mapping table does not define at least one valid sensor field mapping."""

    def __init__(self, message: str, details: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_MAPPING_EMPTY",
            status_code=422,
            details=details,
            retryable=False,
        )

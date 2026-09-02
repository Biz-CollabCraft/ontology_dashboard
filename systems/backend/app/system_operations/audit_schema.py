from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audit_id: str
    occurred_at: str
    actor_id: str
    actor_type: Literal["system_operator", "system"]
    action: str
    resource_type: str
    resource_id: str
    resource_version: str | None = None
    outcome: Literal["succeeded", "failed", "denied"]
    request_id: str
    run_id: str | None = None
    job_id: str | None = None
    event_id: str | None = None
    reason: str | None = None
    error_code: str | None = None
    before_ref: dict[str, Any] | None = None
    after_ref: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["jsonl"] = "jsonl"
    source: Literal["audit", "operational_logs"] = "audit"
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=1000, ge=1, le=10000)

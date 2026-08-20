from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExportFormat = Literal["json", "csv", "pdf"]
ExportScope = Literal["dashboard", "event", "role_workspace"]
Role = Literal["manager", "engineer"]
AppLocale = Literal["ko-KR", "en-US"]
ReportContentOrigin = Literal["generated", "edited", "translated"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportDiagnosisEquipment(StrictModel):
    equipment_id: str
    display_name: str | None = None
    line: str | None = None
    criticality: str | None = None
    assigned_engineer: str | None = None


class ReportDiagnosisFactor(StrictModel):
    evidence_field_id: str
    feature: str
    display_name: str
    value: str | int | float | bool | None = None
    unit: str | None = None
    direction: str | None = None
    contribution: float | None = None
    source_type: str | None = None


class ReportDiagnosisEvidence(StrictModel):
    evidence_id: str
    event_id: str
    status: str
    recommended_decision: str
    confidence: str
    failure_probability: float | None = None
    threshold: float | None = None
    predicted_failure_type: str | None = None
    model_version: str | None = None
    policy_version: str | None = None
    dataset_version: str | None = None
    detected_interval_start: str | None = None
    detected_interval_end: str | None = None
    top_factors: list[ReportDiagnosisFactor] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    generated_at: str | None = None


class ReportDecisionActivity(StrictModel):
    id: str
    actor: str
    decision: str
    note: str
    created_at: str


class ReportNoteActivity(StrictModel):
    id: str
    actor: str
    body: str
    created_at: str


class ReportConversationActivity(StrictModel):
    id: str
    thread_id: str
    role: str
    question: str
    intent: str
    answer: str
    created_at: str


class ReportDiagnosisActivity(StrictModel):
    decisions: list[ReportDecisionActivity] = Field(default_factory=list)
    notes: list[ReportNoteActivity] = Field(default_factory=list)
    conversations: list[ReportConversationActivity] = Field(default_factory=list)


class ReportDiagnosisEvidenceSnapshot(StrictModel):
    """Report-owned projection of Diagnosis evidence and event activity.

    The export/report boundary deliberately excludes raw observations, runtime
    configuration, persistence payloads, and full Diagnosis history.
    """

    event_id: str
    project_id: str
    scenario_id: str
    equipment: ReportDiagnosisEquipment
    evidence: ReportDiagnosisEvidence
    activity: ReportDiagnosisActivity


class ReportSection(StrictModel):
    section_id: str
    title: str
    body: str
    evidence_field_ids: list[str] = Field(default_factory=list)


class ReportAction(StrictModel):
    action_id: str
    label: str
    kind: Literal["monitor", "inspect", "review_shutdown", "verify_data", "report"]
    requires_human_approval: bool = True
    source_refs: list[str] = Field(default_factory=list)


class GroundedReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    report_id: str
    event_id: str
    role: Role
    locale: AppLocale = "ko-KR"
    mode: Literal["deterministic", "llm", "deterministic_fallback"]
    headline: str
    summary: str
    status: str
    confidence: str
    recommended_decision: str
    sections: list[ReportSection]
    actions: list[ReportAction]
    citations: list[str]
    limitations: list[str]
    generated_at: str


class ReportRequest(StrictModel):
    role: Role
    locale: AppLocale = "ko-KR"
    use_llm: bool = True


class ReportDraftSection(StrictModel):
    section_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=12000)
    evidence_field_ids: list[str] = Field(default_factory=list)


class ReportDraftSaveRequest(StrictModel):
    workspace_id: str
    event_id: str = Field(min_length=1, max_length=160)
    role: Role = "engineer"
    locale: AppLocale = "ko-KR"
    base_revision: int = Field(default=0, ge=0)
    headline: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=12000)
    sections: list[ReportDraftSection]
    content_origin: ReportContentOrigin = "edited"
    source_locale: AppLocale | None = None
    source_revision: int | None = Field(default=None, ge=1)


class ReportDraftRecord(StrictModel):
    id: str
    organization_id: str
    project_id: str
    workspace_id: str
    event_id: str
    role: Role
    locale: AppLocale
    revision: int
    headline: str
    summary: str
    sections: list[ReportDraftSection]
    content_origin: ReportContentOrigin
    source_locale: AppLocale | None = None
    source_revision: int | None = None
    updated_by: str
    updated_at: str


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    format: ExportFormat
    scope: ExportScope = "dashboard"
    event_id: str | None = None
    title: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def require_event_id(self) -> "ExportRequest":
        if self.scope == "event" and not self.event_id:
            raise ValueError("event scope export requires event_id")
        if self.scope != "event" and self.event_id is not None:
            raise ValueError("event_id is only allowed for event scope export")
        return self


class ExportCheckpoint(BaseModel):
    id: str
    organization_id: str
    project_id: str
    workspace_id: str
    scope: ExportScope
    format: ExportFormat
    event_id: str | None
    filename: str
    media_type: str
    content_bytes: int
    snapshot_hash: str
    content_hash: str
    requested_by: str
    requested_by_name: str
    created_at: str


class ExportArtifact(BaseModel):
    checkpoint: ExportCheckpoint
    content: bytes

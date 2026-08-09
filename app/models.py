"""Domain models for the workflow dashboard.

These deliberately model a *finance process* rather than a generic task list:
steps declare the systems they touch and the business objects they consume and
produce. That input/output wiring is what a later ontology agent will scan to
propose object types and relationships, so it is part of the core model from the
start rather than bolted on afterwards.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    ACTIVE = "active"
    RETIRED = "retired"


class Criticality(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Maturity(str, Enum):
    AD_HOC = "ad_hoc"
    DEFINED = "defined"
    MANAGED = "managed"
    OPTIMIZED = "optimized"


class Frequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class StepType(str, Enum):
    MANUAL = "manual"
    AUTOMATED = "automated"
    SYSTEM = "system"
    APPROVAL = "approval"
    REVIEW = "review"


class RunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Domain(BaseModel):
    id: str
    name: str
    description: str


class Owner(BaseModel):
    id: str
    name: str
    role: str
    team: str


class System(BaseModel):
    id: str
    name: str
    kind: str


class DataObject(BaseModel):
    """A business object touched by a process — the raw material of the ontology."""

    id: str
    name: str
    description: str
    domain_ids: list[str] = Field(default_factory=list)


class Control(BaseModel):
    id: str
    name: str
    type: str
    framework: str


class Step(BaseModel):
    id: str
    seq: int
    name: str
    description: str
    type: StepType
    role: str
    owner_id: str
    duration_minutes: int
    system_ids: list[str] = Field(default_factory=list)
    input_object_ids: list[str] = Field(default_factory=list)
    output_object_ids: list[str] = Field(default_factory=list)
    controls: list[Control] = Field(default_factory=list)


class Workflow(BaseModel):
    id: str
    name: str
    domain_id: str
    description: str
    owner_id: str
    status: WorkflowStatus
    maturity: Maturity
    criticality: Criticality
    frequency: Frequency
    sla_hours: int
    system_ids: list[str] = Field(default_factory=list)
    data_object_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    risk_notes: str = ""
    step_count: int = 0
    planned_hours: float = 0.0
    steps: list[Step] = Field(default_factory=list)


class Exception_(BaseModel):
    """An issue raised during a run. Named with a trailing underscore to avoid
    shadowing the builtin; serialised as `Exception` nowhere, so the name is
    internal only."""

    id: str
    step_id: str
    severity: Severity
    description: str
    resolved: bool


class Run(BaseModel):
    id: str
    workflow_id: str
    period: str
    started_at: str
    completed_at: str | None = None
    status: RunStatus
    duration_hours: float | None = None
    sla_met: bool | None = None
    exceptions: list[Exception_] = Field(default_factory=list)


class WorkflowMetrics(BaseModel):
    """Per-workflow performance, derived from run history."""

    workflow_id: str
    total_runs: int
    completed_runs: int
    failed_runs: int
    in_progress_runs: int
    on_time_rate: float | None = None
    avg_duration_hours: float | None = None
    automation_rate: float = 0.0
    open_exceptions: int = 0
    last_run_at: str | None = None
    last_run_status: RunStatus | None = None


class WorkflowSummary(BaseModel):
    """List-view shape: workflow header plus its derived metrics, no steps."""

    id: str
    name: str
    domain_id: str
    domain_name: str
    description: str
    owner_id: str
    owner_name: str
    status: WorkflowStatus
    maturity: Maturity
    criticality: Criticality
    frequency: Frequency
    sla_hours: int
    tags: list[str] = Field(default_factory=list)
    step_count: int
    planned_hours: float
    metrics: WorkflowMetrics


class WorkflowDetail(BaseModel):
    """Detail-view shape: everything, with ids resolved to names for the UI."""

    workflow: Workflow
    domain: Domain
    owner: Owner
    systems: list[System] = Field(default_factory=list)
    data_objects: list[DataObject] = Field(default_factory=list)
    metrics: WorkflowMetrics
    recent_runs: list[Run] = Field(default_factory=list)


class PortfolioMetrics(BaseModel):
    """Top-of-dashboard rollup across every workflow in scope."""

    total_workflows: int
    active_workflows: int
    draft_workflows: int
    total_steps: int
    total_runs: int
    on_time_rate: float | None = None
    automation_rate: float = 0.0
    open_exceptions: int = 0
    high_severity_open_exceptions: int = 0
    at_risk_workflows: int = 0
    by_domain: list[dict] = Field(default_factory=list)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_criticality: dict[str, int] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatToolCall(BaseModel):
    """Surfaced to the UI so the user can see which data the answer came from."""

    name: str
    arguments: dict


class ChatResponse(BaseModel):
    reply: str
    mode: str  # "azure_ai_foundry" | "offline"
    tool_calls: list[ChatToolCall] = Field(default_factory=list)
    notice: str | None = None

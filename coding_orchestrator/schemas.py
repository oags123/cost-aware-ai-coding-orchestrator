from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Complexity = Literal["trivial", "simple", "medium", "hard", "critical"]
RiskLevel = Literal["low", "medium", "high"]
FinalStatus = Literal[
    "pending",
    "running",
    "completed",
    "failed",
    "blocked",
    "escalated",
    "skipped",
    "timeout",
]
WorkflowName = Literal[
    "explain_code",
    "fix_bug",
    "write_tests",
    "small_refactor",
    "large_refactor",
    "architecture_review",
    "dependency_update",
    "security_review",
]


class OrchestratorState(BaseModel):
    request_id: str
    user_request: str
    task_id: str | None = None
    task_type: str | None = None
    complexity: Complexity = "simple"
    risk_level: RiskLevel = "low"
    repo_path: str | None = None
    relevant_files: list[str] = Field(default_factory=list)
    retrieved_context: list[str] = Field(default_factory=list)
    selected_model: str | None = None
    selected_workflow: str | None = None
    validation_results: dict[str, Any] = Field(default_factory=dict)
    tool_results: dict[str, Any] = Field(default_factory=dict)
    retry_count: int = 0
    requires_human_approval: bool = False
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    final_status: FinalStatus = "pending"


class TaskSpec(BaseModel):
    id: str
    title: str
    description: str = ""
    complexity: Complexity = "simple"
    risk: RiskLevel = "low"
    depends_on: list[str] = Field(default_factory=list)
    allowed_files: list[str] = Field(default_factory=list)
    max_attempts: int = 2
    max_runtime_seconds: int = 480
    max_cost_usd: float = 0.06
    escalation_allowed: bool = True
    allow_deletes: bool = False
    validation_commands: list[str] = Field(default_factory=list)

    @field_validator("max_attempts", "max_runtime_seconds")
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be >= 1")
        return value

    @field_validator("max_cost_usd")
    @classmethod
    def positive_cost(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value


class CommandResult(BaseModel):
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    runtime_seconds: float = 0.0


class BuilderResult(BaseModel):
    text: str
    confidence: float
    estimated_output_tokens: int
    command: list[str] = Field(default_factory=list)
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    runtime_seconds: float = 0.0
    dry_run: bool = True


class ParsedPatch(BaseModel):
    patch: str
    touched_files: list[str]
    summary: str = ""
    confidence: float = 0.0
    output_mode: str = "unified_diff"


class ValidationResult(BaseModel):
    name: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class EscalationPackage(BaseModel):
    task: TaskSpec
    state: OrchestratorState
    diff: str
    logs: list[str]
    traceback: str | None = None
    validation_errors: list[str] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)
    retry_count: int = 0
    timeout_info: dict[str, Any] = Field(default_factory=dict)
    suggested_next_action: str = ""


def load_task_file(path: Path) -> TaskSpec:
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any]
    if text.lstrip().startswith("---"):
        _, frontmatter, body = text.split("---", 2)
        loaded = yaml.safe_load(frontmatter) or {}
        data = dict(loaded)
        data.setdefault("description", body.strip())
    else:
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Task file {path} must contain YAML metadata")
        data = loaded
    return TaskSpec.model_validate(data)

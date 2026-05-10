from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TimeoutSettings(BaseModel):
    max_task_runtime_seconds: int = 600
    max_attempt_runtime_seconds: int = 300
    max_total_runtime_seconds: int = 3600


class RetrySettings(BaseModel):
    max_retries: int = 1


class BudgetSettings(BaseModel):
    max_task_cost_usd: float = 0.10
    max_project_cost_usd: float = 5.0
    stop_threshold_ratio: float = 0.9


class ValidationSettings(BaseModel):
    max_files_changed: int = 5
    forbidden_paths: list[str] = Field(
        default_factory=lambda: ["/etc/", "~/.ssh", ".env", "secrets", "credentials", "tokens"]
    )
    default_commands: list[str] = Field(
        default_factory=lambda: ["ruff check .", "mypy .", "pytest"]
    )


class ModelRoutingSettings(BaseModel):
    trivial: str = "deterministic"
    simple: str = "opencode-local"
    medium: str = "opencode-coding"
    hard: str = "codex-reviewer-placeholder"
    critical: str = "human-approval"


class ToolPermissions(BaseModel):
    allowlisted_shell_commands: list[str] = Field(
        default_factory=lambda: ["git", "pytest", "ruff", "mypy", "python", "python3"]
    )
    require_approval_for_delete: bool = True


class OpenCodeSettings(BaseModel):
    enabled: bool = False
    dry_run: bool = True
    executable: str = "opencode"
    default_model: str = "opencode-local"
    max_runtime_seconds: int = 300
    output_mode: str = "unified_diff"
    allowed_env_vars: list[str] = Field(default_factory=list)
    extra_args: list[str] = Field(default_factory=list)
    missing_install_note: str = (
        "OpenCode is not installed or not on PATH. Install and authenticate OpenCode, "
        "then set opencode.enabled=true and opencode.dry_run=false."
    )


class GitSettings(BaseModel):
    require_clean_worktree: bool = False
    preserve_untracked_dirs: list[str] = Field(
        default_factory=lambda: ["logs", ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache"]
    )
    preserve_untracked_files: list[str] = Field(default_factory=lambda: [".gitignore"])


class AppConfig(BaseModel):
    repo_path: str = "."
    state_path: str = "logs/state.json"
    log_path: str = "logs/orchestrator.jsonl"
    model_routing: ModelRoutingSettings = Field(default_factory=ModelRoutingSettings)
    timeouts: TimeoutSettings = Field(default_factory=TimeoutSettings)
    retries: RetrySettings = Field(default_factory=RetrySettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    tool_permissions: ToolPermissions = Field(default_factory=ToolPermissions)
    opencode: OpenCodeSettings = Field(default_factory=OpenCodeSettings)
    git: GitSettings = Field(default_factory=GitSettings)


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else Path("config.yaml")
    if not config_path.exists():
        return AppConfig()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping")
    return AppConfig.model_validate(data)


def dump_example_config() -> dict[str, Any]:
    return AppConfig().model_dump()

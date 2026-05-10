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
    ledger_path: str = "logs/budget.sqlite"
    project_id: str = "default"
    project_total_budget_usd: float = 5.0
    cheap_builder_budget_usd: float = 3.0
    expensive_reviewer_budget_usd: float = 1.0
    emergency_budget_usd: float = 1.0


class ModelPricing(BaseModel):
    provider: str
    model: str
    input_usd_per_1m_tokens: float
    output_usd_per_1m_tokens: float
    max_output_tokens: int
    budget_pool: str


class PricingSettings(BaseModel):
    roles: dict[str, ModelPricing] = Field(
        default_factory=lambda: {
            "cheap_builder": ModelPricing(
                provider="opencode",
                model="opencode-local",
                input_usd_per_1m_tokens=0.10,
                output_usd_per_1m_tokens=0.40,
                max_output_tokens=4000,
                budget_pool="cheap_builder",
            ),
            "expensive_reviewer": ModelPricing(
                provider="placeholder",
                model="frontier-reviewer-placeholder",
                input_usd_per_1m_tokens=5.00,
                output_usd_per_1m_tokens=15.00,
                max_output_tokens=1500,
                budget_pool="expensive_reviewer",
            ),
        }
    )


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
    pricing: PricingSettings = Field(default_factory=PricingSettings)
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

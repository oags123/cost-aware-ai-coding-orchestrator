from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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


class LimitSettings(BaseModel):
    max_input_tokens_per_call: int = 32_000
    max_output_tokens_per_call: int = 4_000
    max_context_chars_per_call: int = 128_000
    max_retry_context_chars: int = 8_000
    max_patch_bytes: int = 256_000
    max_stdout_bytes: int = 256_000
    max_stderr_bytes: int = 64_000
    max_validation_output_bytes: int = 64_000
    context_over_limit_policy: Literal["reject", "trim"] = "reject"
    output_over_limit_policy: Literal["reject", "truncate"] = "reject"
    validation_output_over_limit_policy: Literal["reject", "truncate"] = "truncate"


class FlexTierSettings(BaseModel):
    max_attempt_runtime_seconds: int = 600
    max_consecutive_timeouts: int = 2
    timeout_rate_threshold: float = 0.5


class CheapBuilderTierSettings(BaseModel):
    default_tier: Literal["flex", "standard"] = "flex"
    fallback_tier: Literal["flex", "standard"] = "standard"
    flex: FlexTierSettings = Field(default_factory=FlexTierSettings)
    max_standard_fallbacks_per_run: int = 1
    max_standard_fallback_cost_usd_per_run: float = 0.25


class InferenceSettings(BaseModel):
    cheap_builder: CheapBuilderTierSettings = Field(default_factory=CheapBuilderTierSettings)


class ConvergenceSettings(BaseModel):
    max_stagnant_attempts: int = 2
    max_divergent_attempts: int = 1
    max_patch_growth_ratio: float = 1.5
    max_failure_growth_ratio: float = 1.25
    min_improvement_score_to_continue: float = -1.0
    hard_stop_on_syntax_regression: bool = True
    hard_stop_on_unrelated_file_touch: bool = True


class DiagnosisSettings(BaseModel):
    enabled: bool = False
    dry_run: bool = True
    provider: str = "placeholder"
    model: str = "frontier-reviewer-placeholder"
    model_role: str = "expensive_reviewer"
    max_input_tokens: int = 8_000
    max_output_tokens: int = 1_500
    max_context_chars: int = 24_000
    max_cost_per_call_usd: float = 0.25
    max_calls_per_task: int = 1
    max_calls_per_run: int = 2
    role_budget_pool: str = "expensive_reviewer"
    diagnosis_only: bool = True
    max_packet_chars: int = 24_000
    max_diff_chars: int = 10_000
    max_stdout_chars: int = 4_000
    max_stderr_chars: int = 4_000
    allow_direct_patch: bool = False


class TelegramSettings(BaseModel):
    enabled: bool = False
    bot_token_env_var: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env_var: str = "TELEGRAM_CHAT_ID"
    missing_env_policy: Literal["warn", "fail"] = "warn"
    notify_on_blocked: bool = True
    notify_on_budget_exhausted: bool = True
    notify_on_runtime_exhausted: bool = True
    notify_on_no_runnable_tasks: bool = True
    notify_on_system_error: bool = True


class ModelPricing(BaseModel):
    provider: str
    model: str
    inference_tier: str | None = None
    input_usd_per_1m_tokens: float
    output_usd_per_1m_tokens: float
    max_output_tokens: int
    budget_pool: str


class PricingSettings(BaseModel):
    roles: dict[str, ModelPricing] = Field(
        default_factory=lambda: {
            "cheap_builder:flex": ModelPricing(
                provider="google-gemini",
                model="gemini-3.1-flash-lite",
                inference_tier="flex",
                input_usd_per_1m_tokens=0.125,
                output_usd_per_1m_tokens=0.75,
                max_output_tokens=4000,
                budget_pool="cheap_builder",
            ),
            "cheap_builder:standard": ModelPricing(
                provider="google-gemini",
                model="gemini-3.1-flash-lite",
                inference_tier="standard",
                input_usd_per_1m_tokens=0.25,
                output_usd_per_1m_tokens=1.50,
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
    limits: LimitSettings = Field(default_factory=LimitSettings)
    inference: InferenceSettings = Field(default_factory=InferenceSettings)
    convergence: ConvergenceSettings = Field(default_factory=ConvergenceSettings)
    diagnosis: DiagnosisSettings = Field(default_factory=DiagnosisSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
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

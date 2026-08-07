from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high"]
ServiceTier = Literal["default", "flex", "priority", "batch", "fast"]
BuilderExecutionBackend = Literal["role_provider"]

LEGACY_MODEL_ALIAS_RENAMES = {
    "openai_ultra_cheap_legacy": "openai_classifier_nano",
}
LEGACY_ROLE_RENAMES = {
    "ultra_cheap_classifier": "classification_worker",
}

# Roles reachable through automatic routing (WorkflowEngine._select_builder_role)
# without going through the diagnosis/reviewer/emergency escalation paths. Used only
# for documentation/tests; the strict Flex-only policy below applies GLOBALLY to
# every role in the registry, not just this subset -- see
# AppConfig._enforce_flex_only_policy and ModelRoleSettings.live_calls_disabled.
AUTO_ROUTABLE_BUILDER_ROLES: frozenset[str] = frozenset(
    {
        "mechanical_worker",
        "classification_worker",
        "simple_builder",
        "general_builder",
        "coding_optimized_builder",
    }
)


class FlexPolicyViolation(ValueError):
    """Raised when configuration would violate the strict Flex-only execution policy."""


class TimeoutSettings(BaseModel):
    max_task_runtime_seconds: int = 600
    max_attempt_runtime_seconds: int = 300
    max_total_runtime_seconds: int = 3600


class RetrySettings(BaseModel):
    max_retries: int = 1


class BudgetSettings(BaseModel):
    schema_version: int = 3
    max_task_cost_usd: float = 0.10
    max_project_cost_usd: float = 5.0
    stop_threshold_ratio: float = 0.9
    ledger_path: str = "logs/budget.sqlite"
    project_id: str = "default"
    project_total_budget_usd: float = 5.0
    role_budgets_usd: dict[str, float] = Field(
        default_factory=lambda: {
            "worker": 1.0,
            "builder": 3.0,
            "reviewer": 1.0,
            "emergency": 1.0,
            "mechanical_worker": 1.0,
            "simple_builder": 3.0,
            "general_builder": 3.0,
            "coding_optimized_builder": 3.0,
            "frontier_reviewer": 1.0,
            "frontier_coding_reviewer": 1.0,
            "classification_worker": 1.0,
            "frontier_balanced_reviewer": 1.0,
            "emergency_pro_reviewer": 0.5,
            "legacy_reasoning_fallback": 0.5,
            "non_reasoning_instruction_follower": 0.5,
            "mini_legacy_fallback": 0.5,
        }
    )


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
    # Bounded retries on the flex tier itself after a transient error (timeout, rate
    # limit, capacity). Tier NEVER changes across these retries -- there is no
    # standard/default/priority/fast fallback. Once exhausted, the task ends with the
    # "flex_unavailable" status rather than escalating to a higher-priced tier.
    max_flex_retries: int = 2


class BuilderServiceTierSettings(BaseModel):
    # Automatic (non-manual-override) builder calls always request "flex". This field
    # is intentionally a fixed Literal, not configurable to any other tier, so a
    # non-flex automatic default cannot be introduced by editing config.yaml.
    default_tier: Literal["flex"] = "flex"
    flex: FlexTierSettings = Field(default_factory=FlexTierSettings)


class InferenceSettings(BaseModel):
    builder_service_tier: BuilderServiceTierSettings = Field(
        default_factory=BuilderServiceTierSettings
    )


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
    model_role: str = "frontier_reviewer"
    max_input_tokens: int = 8_000
    max_output_tokens: int = 1_500
    max_context_chars: int = 24_000
    max_cost_per_call_usd: float = 0.25
    max_calls_per_task: int = 1
    max_calls_per_run: int = 2
    role_budget_pool: str = "reviewer"
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
    service_tier: ServiceTier | None = None
    input_usd_per_1m_tokens: float
    cached_input_usd_per_1m_tokens: float | None = None
    output_usd_per_1m_tokens: float
    long_context_input_usd_per_1m_tokens: float | None = None
    long_context_cached_input_usd_per_1m_tokens: float | None = None
    long_context_output_usd_per_1m_tokens: float | None = None
    max_output_tokens: int
    budget_pool: str
    source_url: str = "https://developers.openai.com/api/docs/pricing"
    retrieved_or_verified_date: str = "2026-05-11"


class PricingSettings(BaseModel):
    roles: dict[str, ModelPricing] = Field(
        default_factory=lambda: {
            "mechanical_worker:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4-nano",
                service_tier="flex",
                input_usd_per_1m_tokens=0.10,
                cached_input_usd_per_1m_tokens=0.01,
                output_usd_per_1m_tokens=0.625,
                max_output_tokens=1500,
                budget_pool="worker",
            ),
            "mechanical_worker:default": ModelPricing(
                provider="openai",
                model="gpt-5.4-nano",
                service_tier="default",
                input_usd_per_1m_tokens=0.20,
                cached_input_usd_per_1m_tokens=0.02,
                output_usd_per_1m_tokens=1.25,
                max_output_tokens=1500,
                budget_pool="worker",
            ),
            "classification_worker:flex": ModelPricing(
                provider="openai",
                model="gpt-5-nano",
                service_tier="flex",
                input_usd_per_1m_tokens=0.025,
                cached_input_usd_per_1m_tokens=0.0025,
                output_usd_per_1m_tokens=0.2,
                max_output_tokens=1000,
                budget_pool="worker",
            ),
            "classification_worker:default": ModelPricing(
                provider="openai",
                model="gpt-5-nano",
                service_tier="default",
                input_usd_per_1m_tokens=0.05,
                cached_input_usd_per_1m_tokens=0.005,
                output_usd_per_1m_tokens=0.4,
                max_output_tokens=1000,
                budget_pool="worker",
            ),
            "simple_builder:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="flex",
                input_usd_per_1m_tokens=0.375,
                cached_input_usd_per_1m_tokens=0.0375,
                output_usd_per_1m_tokens=2.25,
                max_output_tokens=3000,
                budget_pool="builder",
            ),
            "simple_builder:default": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="default",
                input_usd_per_1m_tokens=0.75,
                cached_input_usd_per_1m_tokens=0.075,
                output_usd_per_1m_tokens=4.5,
                max_output_tokens=3000,
                budget_pool="builder",
            ),
            "general_builder:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="flex",
                input_usd_per_1m_tokens=0.375,
                cached_input_usd_per_1m_tokens=0.0375,
                output_usd_per_1m_tokens=2.25,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            "general_builder:default": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="default",
                input_usd_per_1m_tokens=0.75,
                cached_input_usd_per_1m_tokens=0.075,
                output_usd_per_1m_tokens=4.5,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            "general_builder:priority": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="priority",
                input_usd_per_1m_tokens=1.5,
                cached_input_usd_per_1m_tokens=0.15,
                output_usd_per_1m_tokens=9.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            # coding_optimized_builder was retargeted from gpt-5.3-codex to
            # gpt-5.4-mini because codex does not support Flex (live-verified
            # 2026-08-07); pricing below matches gpt-5.4-mini's real per-token rates
            # (identical to simple_builder/general_builder, same underlying model),
            # not codex's rates.
            "coding_optimized_builder:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="flex",
                input_usd_per_1m_tokens=0.375,
                cached_input_usd_per_1m_tokens=0.0375,
                output_usd_per_1m_tokens=2.25,
                max_output_tokens=8000,
                budget_pool="builder",
            ),
            "coding_optimized_builder:default": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="default",
                input_usd_per_1m_tokens=0.75,
                cached_input_usd_per_1m_tokens=0.075,
                output_usd_per_1m_tokens=4.5,
                max_output_tokens=8000,
                budget_pool="builder",
            ),
            "coding_optimized_builder:priority": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                service_tier="priority",
                input_usd_per_1m_tokens=1.5,
                cached_input_usd_per_1m_tokens=0.15,
                output_usd_per_1m_tokens=9.0,
                max_output_tokens=8000,
                budget_pool="builder",
            ),
            "frontier_coding_reviewer:default": ModelPricing(
                provider="openai",
                model="gpt-5.3-codex",
                service_tier="default",
                input_usd_per_1m_tokens=1.75,
                cached_input_usd_per_1m_tokens=0.175,
                output_usd_per_1m_tokens=14.0,
                max_output_tokens=8000,
                budget_pool="reviewer",
            ),
            "frontier_coding_reviewer:priority": ModelPricing(
                provider="openai",
                model="gpt-5.3-codex",
                service_tier="priority",
                input_usd_per_1m_tokens=3.5,
                cached_input_usd_per_1m_tokens=0.35,
                output_usd_per_1m_tokens=28.0,
                max_output_tokens=8000,
                budget_pool="reviewer",
            ),
            "frontier_balanced_reviewer:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4",
                service_tier="flex",
                input_usd_per_1m_tokens=1.25,
                cached_input_usd_per_1m_tokens=0.13,
                output_usd_per_1m_tokens=7.5,
                long_context_input_usd_per_1m_tokens=2.5,
                long_context_cached_input_usd_per_1m_tokens=0.25,
                long_context_output_usd_per_1m_tokens=11.25,
                max_output_tokens=6000,
                budget_pool="reviewer",
            ),
            "frontier_balanced_reviewer:default": ModelPricing(
                provider="openai",
                model="gpt-5.4",
                service_tier="default",
                input_usd_per_1m_tokens=2.5,
                cached_input_usd_per_1m_tokens=0.25,
                output_usd_per_1m_tokens=15.0,
                long_context_input_usd_per_1m_tokens=5.0,
                long_context_cached_input_usd_per_1m_tokens=0.5,
                long_context_output_usd_per_1m_tokens=22.5,
                max_output_tokens=6000,
                budget_pool="reviewer",
            ),
            "frontier_balanced_reviewer:priority": ModelPricing(
                provider="openai",
                model="gpt-5.4",
                service_tier="priority",
                input_usd_per_1m_tokens=5.0,
                cached_input_usd_per_1m_tokens=0.5,
                output_usd_per_1m_tokens=30.0,
                max_output_tokens=6000,
                budget_pool="reviewer",
            ),
            "frontier_reviewer:flex": ModelPricing(
                provider="openai",
                model="gpt-5.5",
                service_tier="flex",
                input_usd_per_1m_tokens=2.5,
                cached_input_usd_per_1m_tokens=0.25,
                output_usd_per_1m_tokens=15.0,
                long_context_input_usd_per_1m_tokens=5.0,
                long_context_cached_input_usd_per_1m_tokens=0.5,
                long_context_output_usd_per_1m_tokens=22.5,
                max_output_tokens=4000,
                budget_pool="reviewer",
            ),
            "frontier_reviewer:default": ModelPricing(
                provider="openai",
                model="gpt-5.5",
                service_tier="default",
                input_usd_per_1m_tokens=5.0,
                cached_input_usd_per_1m_tokens=0.5,
                output_usd_per_1m_tokens=30.0,
                long_context_input_usd_per_1m_tokens=10.0,
                long_context_cached_input_usd_per_1m_tokens=1.0,
                long_context_output_usd_per_1m_tokens=45.0,
                max_output_tokens=4000,
                budget_pool="reviewer",
            ),
            "frontier_reviewer:priority": ModelPricing(
                provider="openai",
                model="gpt-5.5",
                service_tier="priority",
                input_usd_per_1m_tokens=12.5,
                cached_input_usd_per_1m_tokens=1.25,
                output_usd_per_1m_tokens=75.0,
                max_output_tokens=4000,
                budget_pool="reviewer",
            ),
            "emergency_pro_reviewer:flex": ModelPricing(
                provider="openai",
                model="gpt-5.5-pro",
                service_tier="flex",
                input_usd_per_1m_tokens=15.0,
                cached_input_usd_per_1m_tokens=None,
                output_usd_per_1m_tokens=90.0,
                max_output_tokens=8000,
                budget_pool="emergency",
            ),
            "emergency_pro_reviewer:default": ModelPricing(
                provider="openai",
                model="gpt-5.5-pro",
                service_tier="default",
                input_usd_per_1m_tokens=30.0,
                cached_input_usd_per_1m_tokens=None,
                output_usd_per_1m_tokens=180.0,
                long_context_input_usd_per_1m_tokens=60.0,
                long_context_cached_input_usd_per_1m_tokens=None,
                long_context_output_usd_per_1m_tokens=270.0,
                max_output_tokens=8000,
                budget_pool="emergency",
            ),
            "emergency_pro_reviewer:batch": ModelPricing(
                provider="openai",
                model="gpt-5.5-pro",
                service_tier="batch",
                input_usd_per_1m_tokens=15.0,
                cached_input_usd_per_1m_tokens=None,
                output_usd_per_1m_tokens=90.0,
                max_output_tokens=8000,
                budget_pool="emergency",
            ),
            # gpt-5 live-verified Flex-capable 2026-08-07; flex rate follows the
            # same ~50% ratio observed for every other model in this table.
            "legacy_reasoning_fallback:flex": ModelPricing(
                provider="openai",
                model="gpt-5",
                service_tier="flex",
                input_usd_per_1m_tokens=0.625,
                cached_input_usd_per_1m_tokens=0.0625,
                output_usd_per_1m_tokens=5.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            "legacy_reasoning_fallback:default": ModelPricing(
                provider="openai",
                model="gpt-5",
                service_tier="default",
                input_usd_per_1m_tokens=1.25,
                cached_input_usd_per_1m_tokens=0.125,
                output_usd_per_1m_tokens=10.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            # gpt-5-mini live-verified Flex-capable 2026-08-07.
            "mini_legacy_fallback:flex": ModelPricing(
                provider="openai",
                model="gpt-5-mini",
                service_tier="flex",
                input_usd_per_1m_tokens=0.125,
                cached_input_usd_per_1m_tokens=0.0125,
                output_usd_per_1m_tokens=1.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            "mini_legacy_fallback:default": ModelPricing(
                provider="openai",
                model="gpt-5-mini",
                service_tier="default",
                input_usd_per_1m_tokens=0.25,
                cached_input_usd_per_1m_tokens=0.025,
                output_usd_per_1m_tokens=2.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
            # gpt-4.1 does NOT support Flex (live-verified 2026-08-07: "Invalid
            # service_tier argument"). No flex entry -- this role is
            # live_calls_disabled and can never make a live paid call.
            "non_reasoning_instruction_follower:default": ModelPricing(
                provider="openai",
                model="gpt-4.1",
                service_tier="default",
                input_usd_per_1m_tokens=2.0,
                cached_input_usd_per_1m_tokens=0.5,
                output_usd_per_1m_tokens=8.0,
                max_output_tokens=4000,
                budget_pool="builder",
            ),
        }
    )


class OpenAIProviderSettings(BaseModel):
    enabled: bool = True
    runtime_enabled: bool = False
    api_key_env_var: str = "OPENAI_API_KEY"
    base_url: str | None = None
    request_timeout_seconds: int = 300
    max_retries: int = 2


class ProviderSettings(BaseModel):
    openai: OpenAIProviderSettings = Field(default_factory=OpenAIProviderSettings)


class ModelAliasSettings(BaseModel):
    openai_classifier_nano: str = "gpt-5-nano"
    openai_nano: str = "gpt-5.4-nano"
    openai_mini_legacy: str = "gpt-5-mini"
    openai_mini: str = "gpt-5.4-mini"
    openai_codex: str = "gpt-5.3-codex"
    openai_frontier_balanced: str = "gpt-5.4"
    openai_frontier: str = "gpt-5.5"
    openai_frontier_pro: str = "gpt-5.5-pro"
    openai_legacy_reasoning: str = "gpt-5"
    openai_non_reasoning: str = "gpt-4.1"


class ModelRoleSettings(BaseModel):
    provider: str = "openai"
    model_alias: str
    purpose: str
    max_input_tokens: int
    max_output_tokens: int
    max_context_chars: int
    reasoning_effort: ReasoningEffort = "low"
    verbosity: Verbosity = "medium"
    structured_output: bool = True
    allow_tools: bool = False
    allow_direct_patch: bool = True
    budget_pool: str
    default_service_tier: ServiceTier = "default"
    fallback_service_tier: ServiceTier | None = None
    max_attempts: int = 2
    manual_approval_required: bool = False
    # True only for roles whose model is known NOT to support Flex (e.g.
    # gpt-5.3-codex) and that were deliberately kept on that model rather than
    # retargeted. Such roles can never make a real (paid) provider call -- the
    # provider layer refuses unconditionally -- and exist purely for
    # cost-estimation/analysis/documentation purposes.
    live_calls_disabled: bool = False


class ResolvedModelRole(BaseModel):
    role_name: str
    provider: str
    model: str
    model_alias: str
    purpose: str
    max_input_tokens: int
    max_output_tokens: int
    max_context_chars: int
    reasoning_effort: ReasoningEffort
    verbosity: Verbosity
    structured_output: bool
    allow_tools: bool
    allow_direct_patch: bool
    budget_pool: str
    service_tier: ServiceTier
    fallback_service_tier: ServiceTier | None = None
    max_attempts: int
    live_calls_disabled: bool = False


class ModelRoleRegistry(BaseModel):
    roles: dict[str, ModelRoleSettings] = Field(
        default_factory=lambda: {
            "mechanical_worker": ModelRoleSettings(
                model_alias="openai_nano",
                purpose="tiny deterministic coding tasks and bounded tiny patches",
                max_input_tokens=16_000,
                max_output_tokens=1_500,
                max_context_chars=64_000,
                reasoning_effort="low",
                verbosity="low",
                budget_pool="worker",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "classification_worker": ModelRoleSettings(
                model_alias="openai_classifier_nano",
                purpose="classification and summarization only",
                max_input_tokens=12_000,
                max_output_tokens=1_000,
                max_context_chars=48_000,
                reasoning_effort="none",
                verbosity="low",
                allow_direct_patch=False,
                budget_pool="worker",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "simple_builder": ModelRoleSettings(
                model_alias="openai_mini",
                purpose="small local Python patches, helpers, and validators",
                max_input_tokens=32_000,
                max_output_tokens=3_000,
                max_context_chars=128_000,
                reasoning_effort="low",
                verbosity="low",
                budget_pool="builder",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "general_builder": ModelRoleSettings(
                model_alias="openai_mini",
                purpose="normal coding tasks and guided repairs",
                max_input_tokens=64_000,
                max_output_tokens=4_000,
                max_context_chars=256_000,
                reasoning_effort="low",
                verbosity="medium",
                budget_pool="builder",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "coding_optimized_builder": ModelRoleSettings(
                # gpt-5.3-codex (openai_codex) does NOT support Flex -- live-verified
                # 2026-08-07: the API rejects service_tier="flex" for this model with
                # "Flex is not available for this model." Retargeted to gpt-5.4-mini
                # (openai_mini), which is Flex-capable and already used by
                # simple_builder/general_builder, so this role stays reachable through
                # automatic routing under the strict Flex-only policy.
                model_alias="openai_mini",
                purpose=(
                    "coding-optimized patch generation; retargeted from gpt-5.3-codex "
                    "to gpt-5.4-mini because codex does not support Flex"
                ),
                max_input_tokens=64_000,
                max_output_tokens=8_000,
                max_context_chars=256_000,
                reasoning_effort="medium",
                verbosity="medium",
                budget_pool="builder",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "frontier_coding_reviewer": ModelRoleSettings(
                # gpt-5.3-codex does NOT support Flex (live-verified 2026-08-07: the
                # API rejects service_tier="flex" for this model with "Flex is not
                # available for this model."). Per the strict global Flex-only policy,
                # a role using a non-Flex model may never make a live/paid request --
                # kept intentionally on codex for its coding-specialized review
                # quality, but live_calls_disabled=True makes this role
                # analysis/configuration-only. The provider layer refuses
                # unconditionally regardless of any override.
                model_alias="openai_codex",
                purpose=(
                    "difficult coding diagnosis and risky multi-file patch review; "
                    "codex has no Flex support, so this role is analysis/"
                    "configuration-only and can never make a live paid call"
                ),
                max_input_tokens=128_000,
                max_output_tokens=8_000,
                max_context_chars=400_000,
                reasoning_effort="high",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="reviewer",
                max_attempts=1,
                live_calls_disabled=True,
            ),
            "frontier_balanced_reviewer": ModelRoleSettings(
                # gpt-5.4 live-verified Flex-capable 2026-08-07.
                model_alias="openai_frontier_balanced",
                purpose="cost-conscious architecture-lite and large context review",
                max_input_tokens=256_000,
                max_output_tokens=6_000,
                max_context_chars=1_000_000,
                reasoning_effort="medium",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="reviewer",
                default_service_tier="flex",
                fallback_service_tier=None,
                max_attempts=1,
            ),
            "frontier_reviewer": ModelRoleSettings(
                # gpt-5.5 live-verified Flex-capable 2026-08-07.
                model_alias="openai_frontier",
                purpose="architecture, planning, difficult diagnosis, and review",
                max_input_tokens=256_000,
                max_output_tokens=8_000,
                max_context_chars=1_000_000,
                reasoning_effort="medium",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="reviewer",
                default_service_tier="flex",
                fallback_service_tier=None,
                max_attempts=1,
            ),
            "emergency_pro_reviewer": ModelRoleSettings(
                # gpt-5.5-pro: Flex pricing verified/documented (config validation
                # only -- no live generation call was made for this model, per the
                # cost policy for expensive emergency roles).
                model_alias="openai_frontier_pro",
                purpose="manual approval only final adjudication for hard blockers",
                max_input_tokens=128_000,
                max_output_tokens=8_000,
                max_context_chars=1_000_000,
                reasoning_effort="high",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="emergency",
                # Manual-approval-gated (never auto-routed) but still Flex, per the
                # global "no paid OpenAI request may ever use a non-Flex tier" policy.
                default_service_tier="flex",
                fallback_service_tier=None,
                max_attempts=1,
                manual_approval_required=True,
            ),
            "legacy_reasoning_fallback": ModelRoleSettings(
                # gpt-5 live-verified Flex-capable 2026-08-07.
                model_alias="openai_legacy_reasoning",
                purpose="legacy compatibility fallback only",
                max_input_tokens=64_000,
                max_output_tokens=4_000,
                max_context_chars=256_000,
                reasoning_effort="medium",
                verbosity="medium",
                budget_pool="builder",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "mini_legacy_fallback": ModelRoleSettings(
                # gpt-5-mini live-verified Flex-capable 2026-08-07.
                model_alias="openai_mini_legacy",
                purpose="legacy gpt-5-mini compatibility fallback only",
                max_input_tokens=64_000,
                max_output_tokens=4_000,
                max_context_chars=256_000,
                reasoning_effort="low",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="builder",
                default_service_tier="flex",
                fallback_service_tier=None,
            ),
            "non_reasoning_instruction_follower": ModelRoleSettings(
                # gpt-4.1 does NOT support Flex -- live-verified 2026-08-07: the API
                # rejects service_tier="flex" for this model with "Invalid
                # service_tier argument". No Flex-capable equivalent was retargeted
                # to (this role exists specifically for non-reasoning gpt-4.1
                # behavior), so it is analysis/configuration-only and can never make
                # a live paid call.
                model_alias="openai_non_reasoning",
                purpose=(
                    "deterministic instruction-following fallback without "
                    "reasoning; gpt-4.1 has no Flex support, so this role is "
                    "analysis/configuration-only and can never make a live paid call"
                ),
                max_input_tokens=64_000,
                max_output_tokens=4_000,
                max_context_chars=256_000,
                reasoning_effort="none",
                verbosity="medium",
                allow_direct_patch=False,
                budget_pool="builder",
                default_service_tier="default",
                fallback_service_tier=None,
                live_calls_disabled=True,
            ),
        }
    )


class PolicySettings(BaseModel):
    allow_frontier_direct_patch: bool = False
    allow_xhigh_reasoning: bool = False
    allow_emergency_pro_reviewer: bool = False
    builder_execution_backend: BuilderExecutionBackend = "role_provider"


class ConfigResolutionError(ValueError):
    pass


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
    simple: str = "mechanical_worker"
    medium: str = "general_builder"
    hard: str = "frontier_reviewer"
    critical: str = "human-approval"


class ToolPermissions(BaseModel):
    allowlisted_shell_commands: list[str] = Field(
        default_factory=lambda: ["git", "pytest", "ruff", "mypy", "python", "python3"]
    )
    require_approval_for_delete: bool = True


class GitSettings(BaseModel):
    require_clean_worktree: bool = False
    preserve_untracked_dirs: list[str] = Field(
        default_factory=lambda: ["logs", ".cache", ".pytest_cache", ".mypy_cache", ".ruff_cache"]
    )
    preserve_untracked_files: list[str] = Field(default_factory=lambda: [".gitignore"])


class AppConfig(BaseModel):
    schema_version: int = 3
    repo_path: str = "."
    state_path: str = "logs/state.json"
    log_path: str = "logs/orchestrator.jsonl"
    escalations_path: str = "logs/escalations"
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    model_aliases: ModelAliasSettings = Field(default_factory=ModelAliasSettings)
    model_roles: ModelRoleRegistry = Field(default_factory=ModelRoleRegistry)
    policies: PolicySettings = Field(default_factory=PolicySettings)
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
    git: GitSettings = Field(default_factory=GitSettings)

    @model_validator(mode="after")
    def _enforce_flex_only_policy(self) -> AppConfig:
        """Enforce the strict, GLOBAL Flex-only execution policy as a real
        config-time invariant, not merely a default: no configuration may be
        constructed (from YAML or directly in Python/tests) that would let ANY
        live-callable role -- automatic builders, classification, diagnosis
        reviewers, frontier reviewers, emergency reviewers, or legacy/manual
        aliases -- run outside Flex, declare an automatic fallback tier, or route
        through a model/tier combination without priced Flex support.

        The only escape hatch is `ModelRoleSettings.live_calls_disabled=True`,
        which is reserved for roles whose underlying model is verified to NOT
        support Flex (e.g. gpt-5.3-codex, gpt-4.1) and that were deliberately kept
        on that model rather than retargeted; such roles are analysis/
        configuration-only and the provider layer refuses to ever call them for
        real (see OpenAIProvider.generate), independent of this validator.
        """
        for role_name, role in self.model_roles.roles.items():
            if role.live_calls_disabled:
                continue
            if role.default_service_tier != "flex":
                raise FlexPolicyViolation(
                    f"model role {role_name!r} can make live calls but its "
                    f"default_service_tier is {role.default_service_tier!r}, not "
                    "'flex'. Every live-callable role must default to Flex -- set "
                    "live_calls_disabled=True instead if this role's model cannot "
                    "use Flex."
                )
            if role.fallback_service_tier is not None:
                raise FlexPolicyViolation(
                    f"model role {role_name!r} declares "
                    f"fallback_service_tier={role.fallback_service_tier!r}. Automatic "
                    "tier fallback (Flex to Standard/Default/Priority/Fast) is not "
                    "permitted for any role -- remove fallback_service_tier."
                )
            flex_key = f"{role_name}:flex"
            if flex_key not in self.pricing.roles:
                raise FlexPolicyViolation(
                    f"model role {role_name!r} can make live calls at the Flex "
                    f"tier but has no {flex_key!r} pricing entry. Verified Flex "
                    "pricing is required for every live-callable role."
                )
        for pricing_key, pricing_entry in self.pricing.roles.items():
            if ":" not in pricing_key:
                continue
            _, _, tier_suffix = pricing_key.rpartition(":")
            if pricing_entry.service_tier is not None and pricing_entry.service_tier != tier_suffix:
                raise FlexPolicyViolation(
                    f"pricing entry {pricing_key!r} declares "
                    f"service_tier={pricing_entry.service_tier!r}, which does not "
                    f"match its own key suffix {tier_suffix!r}. The pricing table "
                    "entry used for a call must match the tier actually requested -- "
                    "a Flex call must never be priced using Standard/Default rates."
                )
        diagnosis_role_name = _normalize_legacy_role_name(self.diagnosis.model_role)
        diagnosis_role = self.model_roles.roles.get(diagnosis_role_name)
        if diagnosis_role is not None and diagnosis_role.live_calls_disabled:
            raise FlexPolicyViolation(
                f"diagnosis.model_role={self.diagnosis.model_role!r} resolves to a "
                "role with live_calls_disabled=True and can never make a real "
                "diagnosis call. Point diagnosis.model_role at a live-callable, "
                "Flex-verified role."
            )
        return self


def _normalize_legacy_role_name(role_name: str) -> str:
    return LEGACY_ROLE_RENAMES.get(role_name, role_name)


def _rename_legacy_key(mapping: dict[str, Any], old_key: str, new_key: str) -> None:
    if old_key in mapping and new_key not in mapping:
        mapping[new_key] = mapping[old_key]
    mapping.pop(old_key, None)


def _normalize_legacy_config_keys(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)

    model_aliases = normalized.get("model_aliases")
    if isinstance(model_aliases, dict):
        aliases = dict(model_aliases)
        for old_key, new_key in LEGACY_MODEL_ALIAS_RENAMES.items():
            _rename_legacy_key(aliases, old_key, new_key)
        normalized["model_aliases"] = aliases

    model_roles = normalized.get("model_roles")
    if isinstance(model_roles, dict):
        roles = model_roles.get("roles")
        if isinstance(roles, dict):
            normalized_roles: dict[str, Any] = {}
            for role_name, role_settings in roles.items():
                normalized_role_name = _normalize_legacy_role_name(role_name)
                role_payload = (
                    dict(role_settings) if isinstance(role_settings, dict) else role_settings
                )
                if isinstance(role_payload, dict):
                    model_alias = role_payload.get("model_alias")
                    if isinstance(model_alias, str):
                        role_payload["model_alias"] = LEGACY_MODEL_ALIAS_RENAMES.get(
                            model_alias,
                            model_alias,
                        )
                normalized_roles[normalized_role_name] = role_payload
            normalized["model_roles"] = {**model_roles, "roles": normalized_roles}

    budget = normalized.get("budget")
    if isinstance(budget, dict):
        role_budgets = budget.get("role_budgets_usd")
        if isinstance(role_budgets, dict):
            normalized_budgets = dict(role_budgets)
            for old_key, new_key in LEGACY_ROLE_RENAMES.items():
                _rename_legacy_key(normalized_budgets, old_key, new_key)
            normalized["budget"] = {**budget, "role_budgets_usd": normalized_budgets}

    pricing = normalized.get("pricing")
    if isinstance(pricing, dict):
        roles = pricing.get("roles")
        if isinstance(roles, dict):
            normalized_pricing: dict[str, Any] = {}
            for role_key, pricing_settings in roles.items():
                normalized_role_key = role_key
                for old_key, new_key in LEGACY_ROLE_RENAMES.items():
                    if role_key == old_key or role_key.startswith(f"{old_key}:"):
                        normalized_role_key = role_key.replace(old_key, new_key, 1)
                        break
                normalized_pricing[normalized_role_key] = pricing_settings
            normalized["pricing"] = {**pricing, "roles": normalized_pricing}

    return normalized


def resolve_model_role(
    config: AppConfig,
    role_name: str,
    *,
    service_tier: ServiceTier | None = None,
) -> ResolvedModelRole:
    normalized_role_name = _normalize_legacy_role_name(role_name)
    role = config.model_roles.roles.get(normalized_role_name)
    if role is None:
        raise ConfigResolutionError(f"Unknown model role: {role_name}")

    aliases = config.model_aliases.model_dump()
    model = aliases.get(role.model_alias)
    if not isinstance(model, str) or not model:
        raise ConfigResolutionError(
            f"Model role {role_name!r} references unknown model alias: {role.model_alias!r}"
        )

    selected_service_tier = service_tier or role.default_service_tier
    return ResolvedModelRole(
        role_name=normalized_role_name,
        provider=role.provider,
        model=model,
        model_alias=role.model_alias,
        purpose=role.purpose,
        max_input_tokens=role.max_input_tokens,
        max_output_tokens=role.max_output_tokens,
        max_context_chars=role.max_context_chars,
        reasoning_effort=role.reasoning_effort,
        verbosity=role.verbosity,
        structured_output=role.structured_output,
        allow_tools=role.allow_tools,
        allow_direct_patch=(
            role.allow_direct_patch and config.policies.allow_frontier_direct_patch
            if normalized_role_name.startswith("frontier_")
            else role.allow_direct_patch
        ),
        budget_pool=role.budget_pool,
        service_tier=selected_service_tier,
        fallback_service_tier=role.fallback_service_tier,
        max_attempts=role.max_attempts,
        live_calls_disabled=role.live_calls_disabled,
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else Path("config.yaml")
    if not config_path.exists():
        return AppConfig()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Config must be a YAML mapping")
    return AppConfig.model_validate(_normalize_legacy_config_keys(data))


def dump_example_config() -> dict[str, Any]:
    return AppConfig().model_dump()

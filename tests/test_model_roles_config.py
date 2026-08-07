from __future__ import annotations

from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    ConfigResolutionError,
    load_config,
    resolve_model_role,
)
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.openai_provider import OpenAIProvider
from coding_orchestrator.models.provider import (
    BuilderOutput,
    ProviderConfigurationError,
    ProviderRequest,
)


def test_default_openai_model_roles_are_configured() -> None:
    config = AppConfig()

    assert config.schema_version == 3
    assert config.providers.openai.api_key_env_var == "OPENAI_API_KEY"
    assert not config.providers.openai.runtime_enabled
    assert config.model_aliases.openai_classifier_nano == "gpt-5-nano"
    assert config.model_aliases.openai_nano == "gpt-5.4-nano"
    assert config.model_aliases.openai_mini == "gpt-5.4-mini"
    assert config.model_aliases.openai_codex == "gpt-5.3-codex"
    assert config.model_aliases.openai_frontier == "gpt-5.5"
    assert config.model_aliases.openai_frontier_pro == "gpt-5.5-pro"

    mechanical = config.model_roles.roles["mechanical_worker"]
    assert mechanical.model_alias == "openai_nano"
    assert mechanical.reasoning_effort == "low"
    assert mechanical.verbosity == "low"
    assert mechanical.default_service_tier == "flex"
    assert mechanical.fallback_service_tier is None

    reviewer = config.model_roles.roles["frontier_reviewer"]
    assert reviewer.model_alias == "openai_frontier"
    assert not reviewer.allow_direct_patch
    assert reviewer.budget_pool == "reviewer"
    assert config.model_roles.roles["general_builder"].model_alias == "openai_mini"
    # coding_optimized_builder was retargeted from gpt-5.3-codex (openai_codex) to
    # gpt-5.4-mini (openai_mini) because codex does not support Flex.
    assert config.model_roles.roles["coding_optimized_builder"].model_alias == "openai_mini"
    assert config.model_roles.roles["coding_optimized_builder"].default_service_tier == "flex"
    # frontier_coding_reviewer intentionally stays on codex: manual-override-only,
    # never auto-routed.
    assert config.model_roles.roles["frontier_coding_reviewer"].model_alias == "openai_codex"
    assert config.model_roles.roles["emergency_pro_reviewer"].manual_approval_required


def test_default_openai_pricing_includes_source_metadata() -> None:
    config = AppConfig()

    nano_flex = config.pricing.roles["mechanical_worker:flex"]
    assert nano_flex.provider == "openai"
    assert nano_flex.model == "gpt-5.4-nano"
    assert nano_flex.service_tier == "flex"
    assert nano_flex.input_usd_per_1m_tokens == 0.10
    assert nano_flex.cached_input_usd_per_1m_tokens == 0.01
    assert nano_flex.output_usd_per_1m_tokens == 0.625
    assert nano_flex.source_url == "https://developers.openai.com/api/docs/pricing"
    assert nano_flex.retrieved_or_verified_date == "2026-05-11"

    mini_default = config.pricing.roles["general_builder:default"]
    assert mini_default.model == "gpt-5.4-mini"
    assert mini_default.input_usd_per_1m_tokens == 0.75
    assert mini_default.output_usd_per_1m_tokens == 4.5

    reviewer_priority = config.pricing.roles["frontier_reviewer:priority"]
    assert reviewer_priority.model == "gpt-5.5"
    assert reviewer_priority.service_tier == "priority"
    assert reviewer_priority.input_usd_per_1m_tokens == 12.5
    assert reviewer_priority.output_usd_per_1m_tokens == 75.0
    # coding_optimized_builder was retargeted to gpt-5.4-mini (Flex-capable); its
    # pricing must reflect gpt-5.4-mini's real rates, not gpt-5.3-codex's.
    coding_flex = config.pricing.roles["coding_optimized_builder:flex"]
    assert coding_flex.model == "gpt-5.4-mini"
    assert coding_flex.service_tier == "flex"
    assert config.pricing.roles["coding_optimized_builder:default"].model == "gpt-5.4-mini"
    assert (
        config.pricing.roles["coding_optimized_builder:priority"].output_usd_per_1m_tokens == 9.0
    )
    assert (
        config.pricing.roles[
            "emergency_pro_reviewer:default"
        ].cached_input_usd_per_1m_tokens
        is None
    )


def test_role_budgets_and_service_tier_policy_defaults() -> None:
    config = AppConfig()

    assert config.budget.role_budgets_usd == {
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
    assert config.policies.allow_frontier_direct_patch is False
    assert config.policies.allow_xhigh_reasoning is False
    assert config.policies.allow_emergency_pro_reviewer is False
    assert config.policies.builder_execution_backend == "role_provider"
    # Dead/unused ServiceTierPolicySettings (policies.service_tiers) was removed --
    # it was never wired to any actual tier-selection behavior. The real,
    # enforced Flex-only invariant lives in BuilderServiceTierSettings
    # (config.inference.builder_service_tier) and AppConfig's flex-policy validator.
    assert not hasattr(config.policies, "service_tiers")
    assert config.inference.builder_service_tier.default_tier == "flex"


def test_load_config_parses_custom_model_role(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 3
model_aliases:
  openai_classifier_nano: gpt-5-nano
  openai_nano: gpt-5.4-nano
  openai_mini_legacy: gpt-5-mini
  openai_mini: gpt-5.4-mini
  openai_codex: gpt-5.3-codex
  openai_frontier_balanced: gpt-5.4
  openai_frontier: gpt-5.5
  openai_frontier_pro: gpt-5.5-pro
  openai_legacy_reasoning: gpt-5
  openai_non_reasoning: gpt-4.1
model_roles:
  roles:
    mechanical_worker:
      provider: openai
      model_alias: openai_nano
      purpose: classify and summarize
      max_input_tokens: 4000
      max_output_tokens: 500
      max_context_chars: 16000
      reasoning_effort: low
      verbosity: low
      structured_output: true
      allow_tools: false
      allow_direct_patch: false
      budget_pool: worker
      default_service_tier: flex
      max_attempts: 1
pricing:
  roles:
    "mechanical_worker:flex":
      provider: openai
      model: gpt-5.4-nano
      service_tier: flex
      input_usd_per_1m_tokens: 0.2
      cached_input_usd_per_1m_tokens: 0.02
      output_usd_per_1m_tokens: 1.25
      max_output_tokens: 500
      budget_pool: worker
      source_url: https://developers.openai.com/api/docs/pricing
      retrieved_or_verified_date: "2026-05-11"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    role = config.model_roles.roles["mechanical_worker"]
    assert role.model_alias == "openai_nano"
    assert role.reasoning_effort == "low"
    assert role.default_service_tier == "flex"
    assert role.fallback_service_tier is None
    assert role.max_attempts == 1
    assert config.pricing.roles["mechanical_worker:flex"].cached_input_usd_per_1m_tokens == 0.02


def test_load_config_normalizes_legacy_classifier_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
schema_version: 3
model_aliases:
  openai_ultra_cheap_legacy: gpt-5-nano
model_roles:
  roles:
    ultra_cheap_classifier:
      provider: openai
      model_alias: openai_ultra_cheap_legacy
      purpose: classification and summarization only
      max_input_tokens: 12000
      max_output_tokens: 1000
      max_context_chars: 48000
      reasoning_effort: none
      verbosity: low
      structured_output: true
      allow_tools: false
      allow_direct_patch: false
      budget_pool: worker
      default_service_tier: flex
      max_attempts: 2
budget:
  role_budgets_usd:
    ultra_cheap_classifier: 2.5
pricing:
  roles:
    "ultra_cheap_classifier:flex":
      provider: openai
      model: gpt-5-nano
      service_tier: flex
      input_usd_per_1m_tokens: 0.025
      cached_input_usd_per_1m_tokens: 0.0025
      output_usd_per_1m_tokens: 0.20
      max_output_tokens: 1000
      budget_pool: worker
      source_url: https://developers.openai.com/api/docs/pricing
      retrieved_or_verified_date: "2026-05-11"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert "classification_worker" in config.model_roles.roles
    assert "ultra_cheap_classifier" not in config.model_roles.roles
    assert config.model_aliases.openai_classifier_nano == "gpt-5-nano"
    assert config.budget.role_budgets_usd["classification_worker"] == 2.5
    assert "classification_worker:flex" in config.pricing.roles

    resolved = resolve_model_role(config, "ultra_cheap_classifier")
    assert resolved.role_name == "classification_worker"
    assert resolved.model_alias == "openai_classifier_nano"


def test_resolve_model_role_uses_aliases_and_frontier_patch_policy() -> None:
    config = AppConfig()

    general = resolve_model_role(config, "general_builder", service_tier="default")

    assert general.role_name == "general_builder"
    assert general.provider == "openai"
    assert general.model == "gpt-5.4-mini"
    assert general.service_tier == "default"
    assert general.reasoning_effort == "low"
    assert general.allow_direct_patch is True

    reviewer = resolve_model_role(config, "frontier_reviewer")
    assert reviewer.model == "gpt-5.5"
    assert reviewer.service_tier == "default"
    assert reviewer.allow_direct_patch is False


def test_resolve_model_role_rejects_unknown_role_or_alias() -> None:
    config = AppConfig()

    with pytest.raises(ConfigResolutionError, match="Unknown model role"):
        resolve_model_role(config, "missing_role")

    config.model_roles.roles["broken"] = config.model_roles.roles["mechanical_worker"].model_copy(
        update={"model_alias": "does_not_exist"}
    )
    with pytest.raises(ConfigResolutionError, match="unknown model alias"):
        resolve_model_role(config, "broken")


def test_fake_provider_returns_structured_builder_output() -> None:
    config = AppConfig()
    role = resolve_model_role(config, "mechanical_worker")
    output = BuilderOutput(
        patch="diff --git a/example.py b/example.py\n",
        touched_files=["example.py"],
        summary="created tiny patch",
        confidence=0.9,
    )
    provider = FakeModelProvider([output])

    response = provider.generate(ProviderRequest(role=role, prompt="make a tiny change"))

    assert response.provider == "openai"
    assert response.model == "gpt-5.4-nano"
    assert response.service_tier == "flex"
    assert response.structured_output == output
    assert response.confidence == 0.9
    assert provider.requests[0].role.role_name == "mechanical_worker"


def test_openai_provider_requires_env_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig()
    role = resolve_model_role(config, "general_builder")
    config.providers.openai.runtime_enabled = True
    monkeypatch.delenv(config.providers.openai.api_key_env_var, raising=False)
    provider = OpenAIProvider(config.providers.openai)

    with pytest.raises(ProviderConfigurationError, match="environment variable is not set"):
        provider.generate(ProviderRequest(role=role, prompt="dry run"))


def test_codex_role_uses_request_level_reasoning_effort() -> None:
    config = AppConfig()
    # coding_optimized_builder was retargeted to gpt-5.4-mini because gpt-5.3-codex
    # does not support Flex; frontier_coding_reviewer intentionally stays on codex
    # since it's manual-override-only and never auto-routed.
    role = resolve_model_role(config, "coding_optimized_builder")
    reviewer_role = resolve_model_role(config, "frontier_coding_reviewer")

    assert role.model == "gpt-5.4-mini"
    assert role.service_tier == "flex"
    assert role.reasoning_effort == "medium"
    assert reviewer_role.model == "gpt-5.3-codex"
    assert reviewer_role.reasoning_effort == "high"


def test_frontier_pro_requires_manual_approval_and_priority_disabled() -> None:
    config = AppConfig()
    emergency = config.model_roles.roles["emergency_pro_reviewer"]

    assert emergency.model_alias == "openai_frontier_pro"
    assert emergency.manual_approval_required
    assert emergency.fallback_service_tier is None


def test_cached_input_none_is_distinct_from_zero() -> None:
    config = AppConfig()
    pro_default = config.pricing.roles["emergency_pro_reviewer:default"]
    nano_default = config.pricing.roles["mechanical_worker:default"]

    assert pro_default.cached_input_usd_per_1m_tokens is None
    assert nano_default.cached_input_usd_per_1m_tokens is not None
    assert nano_default.cached_input_usd_per_1m_tokens > 0.0

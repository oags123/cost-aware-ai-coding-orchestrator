from __future__ import annotations

from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    ConfigResolutionError,
    ModelAliasSettings,
    ModelPricing,
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
    assert config.model_aliases.openai_mini_legacy == "gpt-5-mini"
    assert config.model_aliases.openai_codex == "gpt-5.3-codex"
    assert config.model_aliases.openai_legacy_reasoning == "gpt-5"

    mechanical = config.model_roles.roles["mechanical_worker"]
    assert mechanical.model_alias == "openai_classifier_nano"
    assert mechanical.reasoning_effort == "low"
    assert mechanical.verbosity == "low"
    assert mechanical.default_service_tier == "flex"
    assert mechanical.fallback_service_tier is None

    reviewer = config.model_roles.roles["frontier_reviewer"]
    assert reviewer.model_alias == "openai_legacy_reasoning"
    assert not reviewer.allow_direct_patch
    assert reviewer.budget_pool == "reviewer"
    assert config.model_roles.roles["general_builder"].model_alias == "openai_mini_legacy"
    # coding_optimized_builder was retargeted from gpt-5.3-codex (openai_codex) to
    # gpt-5 (openai_legacy_reasoning) because codex does not support Flex.
    assert (
        config.model_roles.roles["coding_optimized_builder"].model_alias
        == "openai_legacy_reasoning"
    )
    assert config.model_roles.roles["coding_optimized_builder"].default_service_tier == "flex"
    # frontier_coding_reviewer intentionally stays on codex: manual-override-only,
    # never auto-routed.
    assert config.model_roles.roles["frontier_coding_reviewer"].model_alias == "openai_codex"
    assert config.model_roles.roles["emergency_pro_reviewer"].manual_approval_required


def test_default_openai_pricing_includes_source_metadata() -> None:
    config = AppConfig()

    nano_flex = config.pricing.roles["mechanical_worker:flex"]
    assert nano_flex.provider == "openai"
    assert nano_flex.model == "gpt-5-nano"
    assert nano_flex.service_tier == "flex"
    assert nano_flex.input_usd_per_1m_tokens == 0.025
    assert nano_flex.cached_input_usd_per_1m_tokens == 0.0025
    assert nano_flex.output_usd_per_1m_tokens == 0.2
    assert nano_flex.source_url == "https://developers.openai.com/api/docs/pricing"
    assert nano_flex.retrieved_or_verified_date == "2026-05-11"

    mini_flex = config.pricing.roles["general_builder:flex"]
    assert mini_flex.model == "gpt-5-mini"
    assert mini_flex.input_usd_per_1m_tokens == 0.125
    assert mini_flex.output_usd_per_1m_tokens == 1.0

    reviewer_flex = config.pricing.roles["frontier_reviewer:flex"]
    assert reviewer_flex.model == "gpt-5"
    assert reviewer_flex.service_tier == "flex"
    assert reviewer_flex.input_usd_per_1m_tokens == 0.625
    assert reviewer_flex.output_usd_per_1m_tokens == 5.0
    # coding_optimized_builder was retargeted to gpt-5 (Flex-capable); its pricing
    # must reflect gpt-5's real rates, not gpt-5.3-codex's.
    coding_flex = config.pricing.roles["coding_optimized_builder:flex"]
    assert coding_flex.model == "gpt-5"
    assert coding_flex.service_tier == "flex"
    assert (
        config.pricing.roles["emergency_pro_reviewer:flex"].cached_input_usd_per_1m_tokens
        == 0.0625
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
  openai_mini_legacy: gpt-5-mini
  openai_codex: gpt-5.3-codex
  openai_legacy_reasoning: gpt-5
  openai_non_reasoning: gpt-4.1
model_roles:
  roles:
    mechanical_worker:
      provider: openai
      model_alias: openai_classifier_nano
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
      model: gpt-5-nano
      service_tier: flex
      input_usd_per_1m_tokens: 0.025
      cached_input_usd_per_1m_tokens: 0.0025
      output_usd_per_1m_tokens: 0.2
      max_output_tokens: 500
      budget_pool: worker
      source_url: https://developers.openai.com/api/docs/pricing
      retrieved_or_verified_date: "2026-05-11"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    role = config.model_roles.roles["mechanical_worker"]
    assert role.model_alias == "openai_classifier_nano"
    assert role.reasoning_effort == "low"
    assert role.default_service_tier == "flex"
    assert role.fallback_service_tier is None
    assert role.max_attempts == 1
    assert (
        config.pricing.roles["mechanical_worker:flex"].cached_input_usd_per_1m_tokens == 0.0025
    )


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
    assert general.model == "gpt-5-mini"
    assert general.service_tier == "default"
    assert general.reasoning_effort == "medium"
    assert general.allow_direct_patch is True

    reviewer = resolve_model_role(config, "frontier_reviewer")
    assert reviewer.model == "gpt-5"
    assert reviewer.service_tier == "flex"
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
    assert response.model == "gpt-5-nano"
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
    # coding_optimized_builder was retargeted to gpt-5 because gpt-5.3-codex does
    # not support Flex; frontier_coding_reviewer intentionally stays on codex since
    # it's manual-override-only and never auto-routed.
    role = resolve_model_role(config, "coding_optimized_builder")
    reviewer_role = resolve_model_role(config, "frontier_coding_reviewer")

    assert role.model == "gpt-5"
    assert role.service_tier == "flex"
    assert role.reasoning_effort == "medium"
    assert reviewer_role.model == "gpt-5.3-codex"
    assert reviewer_role.reasoning_effort == "high"


def test_frontier_pro_requires_manual_approval_and_priority_disabled() -> None:
    config = AppConfig()
    emergency = config.model_roles.roles["emergency_pro_reviewer"]

    assert emergency.model_alias == "openai_legacy_reasoning"
    assert emergency.manual_approval_required
    assert emergency.fallback_service_tier is None


def test_cached_input_none_is_distinct_from_zero() -> None:
    config = AppConfig()
    nano_flex = config.pricing.roles["mechanical_worker:flex"]
    assert nano_flex.cached_input_usd_per_1m_tokens is not None
    assert nano_flex.cached_input_usd_per_1m_tokens > 0.0

    undocumented = ModelPricing(
        provider="openai",
        model="gpt-5",
        service_tier="flex",
        input_usd_per_1m_tokens=0.625,
        cached_input_usd_per_1m_tokens=None,
        output_usd_per_1m_tokens=5.0,
        max_output_tokens=4000,
        budget_pool="reviewer",
    )
    assert undocumented.cached_input_usd_per_1m_tokens is None


# Roles simplified 2026-08-07 to the 3-model Flex policy (gpt-5-nano/gpt-5-mini/
# gpt-5), following a benchmark that showed comparable reliability at lower cost per
# completed task versus the previous gpt-5.4-nano/gpt-5.4-mini/gpt-5.4/gpt-5.5/
# gpt-5.5-pro spread -- see docs/OPERATIONAL_HARDENING_CHANGES.md.
THREE_MODEL_POLICY_ROLES = frozenset(
    {
        "mechanical_worker",
        "classification_worker",
        "simple_builder",
        "general_builder",
        "coding_optimized_builder",
        "frontier_balanced_reviewer",
        "frontier_reviewer",
        "emergency_pro_reviewer",
    }
)
THREE_MODEL_POLICY_MODELS = frozenset({"gpt-5-nano", "gpt-5-mini", "gpt-5"})


def test_three_model_policy_roles_only_use_the_three_approved_models() -> None:
    config = AppConfig()
    aliases = config.model_aliases.model_dump()

    for role_name in THREE_MODEL_POLICY_ROLES:
        role = config.model_roles.roles[role_name]
        model = aliases[role.model_alias]
        assert model in THREE_MODEL_POLICY_MODELS, (
            f"{role_name} resolves to {model!r}, not one of the three approved "
            f"models {sorted(THREE_MODEL_POLICY_MODELS)}"
        )
        pricing = config.pricing.roles[f"{role_name}:flex"]
        assert pricing.model in THREE_MODEL_POLICY_MODELS


def test_three_model_policy_removed_now_unused_aliases() -> None:
    # openai_nano (gpt-5.4-nano), openai_mini (gpt-5.4-mini), openai_frontier_balanced
    # (gpt-5.4), openai_frontier (gpt-5.5), and openai_frontier_pro (gpt-5.5-pro)
    # became unreferenced once every role above was retargeted -- they were removed
    # from ModelAliasSettings entirely rather than left as dead config surface.
    alias_fields = set(ModelAliasSettings.model_fields)
    for removed in (
        "openai_nano",
        "openai_mini",
        "openai_frontier_balanced",
        "openai_frontier",
        "openai_frontier_pro",
    ):
        assert removed not in alias_fields


def test_classification_worker_reasoning_effort_is_not_none() -> None:
    # Regression guard: reasoning_effort="none" is REJECTED by the live API for
    # every gpt-5-family model (live-verified 2026-08-07, "Unsupported value: 'none'
    # is not supported ... Supported values are: 'minimal', 'low', 'medium', and
    # 'high'"). classification_worker previously shipped with "none" and could never
    # have made a successful live call.
    config = AppConfig()
    assert config.model_roles.roles["classification_worker"].reasoning_effort != "none"

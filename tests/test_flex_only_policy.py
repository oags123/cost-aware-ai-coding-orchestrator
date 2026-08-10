"""Regression tests for the strict Flex-only OpenAI execution policy.

Cost predictability is prioritized over latency: every normal (automatically routed)
OpenAI call must request service_tier="flex", there is no automatic fallback to any
other tier, and unavailable Flex capacity ends a task with an accurate status rather
than silently escalating to a higher-priced tier. See
docs/OPERATIONAL_HARDENING_CHANGES.md and AppConfig._enforce_flex_only_policy for the
full design. These tests use real temporary git repositories wherever git/repo state
matters, per the project's own test conventions.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pydantic
import pytest

from coding_orchestrator.config import (
    AppConfig,
    BuilderServiceTierSettings,
    FlexTierSettings,
    InferenceSettings,
    ModelPricing,
    PricingSettings,
)
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.provider import (
    BuilderOutput,
    ProviderRequest,
    ProviderTransientError,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)


def commit_file(path: Path, relative: str, content: str) -> None:
    target = path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", relative], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)


def real_patch_provider(touched_file: str = "app.py") -> FakeModelProvider:
    return FakeModelProvider(
        [
            BuilderOutput(
                patch=(
                    f"diff --git a/{touched_file} b/{touched_file}\n"
                    f"--- a/{touched_file}\n"
                    f"+++ b/{touched_file}\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
                touched_files=[touched_file],
                summary="flex policy test patch",
                confidence=0.7,
            )
        ]
    )


def base_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )


# --- 1. Every automatically routed model uses Flex ---


@pytest.mark.parametrize(
    ("task_kwargs", "expected_role"),
    [
        ({"title": "Explain the code"}, "mechanical_worker"),
        ({"title": "Write tests for helper"}, "mechanical_worker"),
        ({"title": "Fix bug", "allowed_files": ["app.py"]}, "simple_builder"),
        ({"title": "Fix bug", "risk": "high"}, "general_builder"),
        ({"title": "Fix bug", "complexity": "hard"}, "general_builder"),
    ],
)
def test_every_automatically_routed_role_uses_flex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task_kwargs: dict[str, object],
    expected_role: str,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    task = TaskSpec(
        id="T-1",
        validation_commands=["python -c 'pass'"],
        **task_kwargs,  # type: ignore[arg-type]
    )

    state = engine.run_task(task)

    assert state.tool_results["builder_role"] == expected_role
    assert state.tool_results["requested_service_tier"] == "flex"
    assert state.tool_results["builder_service_tier"] == "flex"


# --- 2. No silent Standard/Fast fallback ---


def test_no_silent_fallback_tier_ever_requested_across_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = base_config(tmp_path).model_copy(
        update={
            "inference": InferenceSettings(
                builder_service_tier=BuilderServiceTierSettings(
                    flex=FlexTierSettings(max_flex_retries=3)
                )
            )
        }
    )
    engine = WorkflowEngine(config)
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))

    requested_tiers: list[str] = []

    def flaky(request: ProviderRequest) -> object:
        requested_tiers.append(request.role.service_tier)
        if len(requested_tiers) <= 3:
            raise ProviderTransientError("capacity blip")
        return real_patch_provider().generate(request)

    monkeypatch.setattr(engine.openai_provider, "generate", flaky)

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.final_status == "completed"
    assert requested_tiers == ["flex", "flex", "flex", "flex"]
    non_flex_tiers = {"standard", "default", "priority", "batch", "fast"}
    assert not any(tier in non_flex_tiers for tier in requested_tiers)


def test_no_fallback_tier_config_field_exists() -> None:
    # The old fallback_tier / max_standard_fallbacks_per_run knobs were removed
    # entirely from BuilderServiceTierSettings -- there is no field left that could
    # reintroduce automatic fallback via configuration.
    settings = BuilderServiceTierSettings()
    assert not hasattr(settings, "fallback_tier")
    assert not hasattr(settings, "max_standard_fallbacks_per_run")
    assert settings.default_tier == "flex"


# --- 3 & 4. Flex timeout preserves repository state; flex_unavailable is accurate ---


def test_flex_unavailable_preserves_dirty_preexisting_work_and_reports_accurately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    commit_file(tmp_path, "user_work.py", "original\n")
    (tmp_path / "user_work.py").write_text("user's uncommitted edit\n", encoding="utf-8")
    original_app_sha = subprocess.run(
        ["git", "hash-object", "app.py"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()

    config = base_config(tmp_path).model_copy(
        update={
            "inference": InferenceSettings(
                builder_service_tier=BuilderServiceTierSettings(
                    flex=FlexTierSettings(max_flex_retries=0)
                )
            )
        }
    )
    engine = WorkflowEngine(config)
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(
        engine.openai_provider,
        "generate",
        lambda request: (_ for _ in ()).throw(ProviderTransientError("flex capacity exhausted")),
    )

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.final_status == "flex_unavailable"
    assert state.final_status not in {"completed", "failed", "blocked"}
    message = state.validation_results["service_tier"]["message"]
    assert "No higher-priced tier was used" in message
    assert "handoff_package" in state.tool_results
    handoff_path = Path(state.tool_results["handoff_package"])
    assert handoff_path.exists()
    assert "reason: flex_unavailable" in handoff_path.read_text(encoding="utf-8")

    current_app_sha = subprocess.run(
        ["git", "hash-object", "app.py"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert current_app_sha == original_app_sha
    assert (tmp_path / "user_work.py").read_text(encoding="utf-8") == "user's uncommitted edit\n"
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert log.count("\n") == 2  # only the two seed commits, nothing new


# --- 5. Pricing always comes from the Flex entry ---


def test_estimate_and_ledger_use_flex_pricing_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "completed"
    flex_pricing = engine.budget.pricing_for_role(
        state.tool_results["builder_role"], "flex"
    )
    assert flex_pricing.service_tier == "flex"
    estimate = state.tool_results["budget_estimate"]
    expected_input_cost = (
        estimate["estimated_input_tokens"] / 1_000_000.0
    ) * flex_pricing.input_usd_per_1m_tokens
    assert estimate["estimated_input_cost_usd"] == pytest.approx(expected_input_cost)

    with sqlite3.connect(engine.budget.settings.ledger_path) as conn:
        row = conn.execute(
            "SELECT requested_service_tier, actual_service_tier FROM budget_events "
            "WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task.id,),
        ).fetchone()
    assert row == ("flex", "flex")


# --- 6. Non-Flex models cannot be automatically routed ---


def test_config_rejects_auto_routed_role_without_flex_pricing() -> None:
    with pytest.raises(pydantic.ValidationError, match="has no .*:flex' pricing entry"):
        AppConfig(
            pricing=PricingSettings(
                roles={
                    "simple_builder:default": ModelPricing(
                        provider="openai",
                        model="gpt-5.3-codex",
                        service_tier="default",
                        input_usd_per_1m_tokens=1.0,
                        output_usd_per_1m_tokens=2.0,
                        max_output_tokens=100,
                        budget_pool="builder",
                    )
                }
            )
        )


def test_config_rejects_auto_routed_role_with_non_flex_default_tier() -> None:
    from coding_orchestrator.config import ModelRoleRegistry

    base = AppConfig()
    roles = dict(base.model_roles.roles)
    roles["simple_builder"] = roles["simple_builder"].model_copy(
        update={"default_service_tier": "default"}
    )
    with pytest.raises(pydantic.ValidationError, match="not 'flex'"):
        AppConfig(model_roles=ModelRoleRegistry(roles=roles), pricing=base.pricing)


def test_config_rejects_auto_routed_role_with_fallback_tier_declared() -> None:
    from coding_orchestrator.config import ModelRoleRegistry

    base = AppConfig()
    roles = dict(base.model_roles.roles)
    roles["general_builder"] = roles["general_builder"].model_copy(
        update={"fallback_service_tier": "default"}
    )
    with pytest.raises(pydantic.ValidationError, match="fallback_service_tier"):
        AppConfig(model_roles=ModelRoleRegistry(roles=roles), pricing=base.pricing)


def test_config_rejects_pricing_entry_tier_mismatch() -> None:
    base = AppConfig()
    roles = dict(base.pricing.roles)
    roles["mechanical_worker:flex"] = roles["mechanical_worker:flex"].model_copy(
        update={"service_tier": "default"}
    )
    with pytest.raises(pydantic.ValidationError, match="does not match its own key suffix"):
        AppConfig(pricing=PricingSettings(roles=roles))


def test_codex_role_not_reachable_through_automatic_routing(tmp_path: Path) -> None:
    # gpt-5.3-codex (openai_codex) does not support Flex (live-verified). Its
    # remaining role, frontier_coding_reviewer, must never be selectable by
    # WorkflowEngine._select_builder_role for any complexity/risk combination.
    from coding_orchestrator.schemas import Complexity, OrchestratorState, RiskLevel

    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(base_config(tmp_path))
    complexities: list[Complexity] = ["trivial", "simple", "medium", "hard", "critical"]
    risks: list[RiskLevel] = ["low", "medium", "high"]
    for complexity in complexities:
        for risk in risks:
            for allowed_files in ([], ["app.py"], ["a.py", "b.py"]):
                task = TaskSpec(
                    id="T-1",
                    title="Fix bug",
                    complexity=complexity,
                    risk=risk,
                    allowed_files=allowed_files,
                )
                state = OrchestratorState(
                    request_id="r",
                    user_request="fix",
                    complexity=complexity,
                    risk_level=risk,
                    task_type="fix_bug",
                    retry_count=0,
                )
                role = engine._select_builder_role(task, state)  # noqa: SLF001
                assert role in {"mechanical_worker", "simple_builder", "general_builder"}
                assert role != "frontier_coding_reviewer"
                assert role != "coding_optimized_builder"


def test_coding_optimized_builder_retargeted_away_from_codex() -> None:
    config = AppConfig()
    role = config.model_roles.roles["coding_optimized_builder"]
    assert role.model_alias != "openai_codex"
    assert config.model_aliases.model_dump()[role.model_alias] != "gpt-5.3-codex"


# --- 7. There is no non-Flex override mechanism anywhere, for any path ---


def test_workflow_engine_has_no_manual_tier_override_parameter(tmp_path: Path) -> None:
    import inspect

    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")

    signature = inspect.signature(WorkflowEngine.__init__)
    assert "manual_service_tier_override" not in signature.parameters
    assert not hasattr(WorkflowEngine(base_config(tmp_path)), "manual_service_tier_override")


def test_cli_has_no_non_flex_override_flag() -> None:
    from coding_orchestrator.app import build_parser

    parser = build_parser()
    args = parser.parse_args(["run", "--task", "tasks/example_task.md"])
    assert not hasattr(args, "allow_non_flex_tier")

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--allow-non-flex-tier", "default", "run", "--task", "tasks/example_task.md"]
        )


def test_default_run_always_requests_flex(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")

    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.tool_results["requested_service_tier"] == "flex"


def test_provider_refuses_any_non_flex_request_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The hard guard in OpenAIProvider.generate() is the actual enforcement boundary
    # -- construct a request explicitly asking for a non-Flex tier (simulating any
    # hypothetical future code path, direct-provider use, or manual role selection)
    # and confirm it is refused before any client/API interaction happens.
    from coding_orchestrator.config import (
        OpenAIProviderSettings,
        ProviderSettings,
        resolve_model_role,
    )
    from coding_orchestrator.models.openai_provider import OpenAIProvider
    from coding_orchestrator.models.provider import ProviderConfigurationError

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = AppConfig(
        providers=ProviderSettings(openai=OpenAIProviderSettings(runtime_enabled=True))
    )
    role = resolve_model_role(config, "general_builder", service_tier="default")
    provider = OpenAIProvider(OpenAIProviderSettings(runtime_enabled=True))
    request = ProviderRequest(role=role, prompt="do it")

    with pytest.raises(ProviderConfigurationError, match="only 'flex' is permitted"):
        provider.generate(request)


def test_provider_refuses_live_calls_disabled_role_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coding_orchestrator.config import OpenAIProviderSettings, resolve_model_role
    from coding_orchestrator.models.openai_provider import OpenAIProvider
    from coding_orchestrator.models.provider import ProviderConfigurationError

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = AppConfig()
    # frontier_coding_reviewer defaults to "default" tier and live_calls_disabled=True
    # (gpt-5.3-codex has no Flex support) -- even resolving it at "flex" explicitly
    # must still be refused because live_calls_disabled is unconditional.
    role = resolve_model_role(config, "frontier_coding_reviewer", service_tier="flex")
    assert role.live_calls_disabled is True
    provider = OpenAIProvider(OpenAIProviderSettings(runtime_enabled=True))
    request = ProviderRequest(role=role, prompt="do it")

    with pytest.raises(ProviderConfigurationError, match="live_calls_disabled=True"):
        provider.generate(request)


# --- 8. Ledger records requested and returned tiers correctly ---


def test_ledger_records_requested_and_actual_tiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "completed"
    with sqlite3.connect(engine.budget.settings.ledger_path) as conn:
        row = conn.execute(
            "SELECT requested_service_tier, actual_service_tier, fallback_occurred, "
            "actual_cost_usd FROM budget_events WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task.id,),
        ).fetchone()
    assert row is not None
    requested, actual, fallback_occurred, actual_cost = row
    assert requested == "flex"
    assert actual == "flex"
    assert fallback_occurred == 0
    assert actual_cost is not None and actual_cost >= 0


# --- Requirement 10: returned tier mismatch must not be treated as normal success ---


def test_service_tier_mismatch_blocks_task_conservatively(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")

    class MismatchedTierProvider(FakeModelProvider):
        def generate(self, request: ProviderRequest):  # type: ignore[no-untyped-def]
            response = super().generate(request)
            return response.model_copy(update={"service_tier": "default"})

    provider = MismatchedTierProvider(
        [
            BuilderOutput(
                patch=(
                    "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
                    "@@ -1 +1 @@\n-old\n+new\n"
                ),
                touched_files=["app.py"],
                summary="x",
                confidence=0.5,
            )
        ]
    )
    engine = WorkflowEngine(base_config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.final_status == "blocked"
    mismatch = state.tool_results["service_tier_mismatch"]
    assert mismatch == {"requested": "flex", "actual": "default"}
    # Repository must not carry the unverified change through as if it succeeded.
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


# --- Requirement 9 (global scope): diagnosis, emergency, and legacy/alias paths ---


def test_diagnosis_role_resolves_flex_compliant() -> None:
    config = AppConfig()
    from coding_orchestrator.config import resolve_model_role

    diagnosis_role = resolve_model_role(config, config.diagnosis.model_role)
    assert diagnosis_role.service_tier == "flex"
    assert diagnosis_role.live_calls_disabled is False


def test_diagnosis_model_role_pointing_at_disabled_role_rejected() -> None:
    from coding_orchestrator.config import DiagnosisSettings

    with pytest.raises(pydantic.ValidationError, match="live_calls_disabled=True"):
        AppConfig(diagnosis=DiagnosisSettings(model_role="frontier_coding_reviewer"))


def test_emergency_reviewer_is_flex_with_manual_approval_preserved() -> None:
    config = AppConfig()
    from coding_orchestrator.config import resolve_model_role

    role = config.model_roles.roles["emergency_pro_reviewer"]
    assert role.default_service_tier == "flex"
    assert role.fallback_service_tier is None
    assert role.manual_approval_required is True
    resolved = resolve_model_role(config, "emergency_pro_reviewer")
    assert resolved.service_tier == "flex"
    assert "emergency_pro_reviewer:flex" in config.pricing.roles


def test_legacy_and_alias_roles_are_flex_or_explicitly_disabled() -> None:
    config = AppConfig()
    # gpt-5 and gpt-5-mini are live-verified Flex-capable -> must be flex.
    for role_name in ("legacy_reasoning_fallback", "mini_legacy_fallback"):
        role = config.model_roles.roles[role_name]
        assert role.default_service_tier == "flex"
        assert role.fallback_service_tier is None
        assert role.live_calls_disabled is False
        assert f"{role_name}:flex" in config.pricing.roles
    # gpt-4.1 is NOT Flex-capable -> must be fully disabled for live calls, never
    # reachable at "default" or any other paid tier.
    non_reasoning = config.model_roles.roles["non_reasoning_instruction_follower"]
    assert non_reasoning.live_calls_disabled is True


def test_every_live_enabled_role_in_registry_is_flex_and_priced() -> None:
    # Comprehensive sweep: for every role in the default registry, either it is
    # live_calls_disabled (and therefore provably unreachable at the provider
    # boundary, see test_provider_refuses_live_calls_disabled_role_unconditionally),
    # or it is Flex-only with verified pricing. No third state exists.
    config = AppConfig()
    for role_name, role in config.model_roles.roles.items():
        if role.live_calls_disabled:
            continue
        assert role.default_service_tier == "flex", role_name
        assert role.fallback_service_tier is None, role_name
        assert f"{role_name}:flex" in config.pricing.roles, role_name


def test_every_live_enabled_role_is_blocked_at_provider_if_forced_non_flex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Belt-and-suspenders: even if some future bug resolved a live-enabled role at a
    # non-Flex tier, the provider must still refuse it. Sweep every role.
    from coding_orchestrator.config import OpenAIProviderSettings, resolve_model_role
    from coding_orchestrator.models.openai_provider import OpenAIProvider
    from coding_orchestrator.models.provider import ProviderConfigurationError

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    config = AppConfig()
    provider = OpenAIProvider(OpenAIProviderSettings(runtime_enabled=True))
    for role_name in config.model_roles.roles:
        role = resolve_model_role(config, role_name, service_tier="default")
        request = ProviderRequest(role=role, prompt="do it")
        with pytest.raises(ProviderConfigurationError):
            provider.generate(request)

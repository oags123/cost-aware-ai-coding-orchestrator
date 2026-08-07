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
    monkeypatch.setattr(engine, "_validate", lambda task: [])
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
    monkeypatch.setattr(engine, "_validate", lambda task: [])

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
    monkeypatch.setattr(engine, "_validate", lambda task: [])
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
    monkeypatch.setattr(engine, "_validate", lambda task: [])
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


# --- 7. Manual override is explicit and visible ---


def test_manual_override_is_explicit_and_never_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")

    # No override passed -> always Flex, regardless of config content.
    default_engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    assert default_engine.manual_service_tier_override is None
    monkeypatch.setattr(default_engine, "_validate", lambda task: [])
    state = default_engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))
    assert state.tool_results["requested_service_tier"] == "flex"
    assert state.tool_results["manual_service_tier_override"] is False


def test_manual_override_is_visible_in_logs(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = base_config(tmp_path)

    WorkflowEngine(config, manual_service_tier_override="default")

    log_path = tmp_path / "log.jsonl"
    log_content = log_path.read_text(encoding="utf-8")
    assert "manual_service_tier_override_active" in log_content
    assert "MANUAL OVERRIDE" in log_content
    assert "default" in log_content


def test_manual_override_applies_to_builder_calls_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = base_config(tmp_path)
    engine = WorkflowEngine(
        config,
        provider_overrides={"openai": real_patch_provider()},
        manual_service_tier_override="default",
    )
    monkeypatch.setattr(engine, "_validate", lambda task: [])

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.tool_results["requested_service_tier"] == "default"
    assert state.tool_results["manual_service_tier_override"] is True


def test_cli_exposes_explicit_non_flex_override_flag() -> None:
    from coding_orchestrator.app import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["--allow-non-flex-tier", "default", "run", "--task", "tasks/example_task.md"]
    )
    assert args.allow_non_flex_tier == "default"

    default_args = parser.parse_args(["run", "--task", "tasks/example_task.md"])
    assert default_args.allow_non_flex_tier is None


# --- 8. Ledger records requested and returned tiers correctly ---


def test_ledger_records_requested_and_actual_tiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: [])
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
    monkeypatch.setattr(engine, "_validate", lambda task: [])

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.final_status == "blocked"
    mismatch = state.tool_results["service_tier_mismatch"]
    assert mismatch == {"requested": "flex", "actual": "default"}
    # Repository must not carry the unverified change through as if it succeeded.
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    BudgetSettings,
    BuilderServiceTierSettings,
    FlexTierSettings,
    ModelPricing,
    PricingSettings,
)
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.provider import BuilderOutput, ProviderError, ProviderRequest
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    target = path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)


def real_patch_provider() -> FakeModelProvider:
    return FakeModelProvider(
        [
            BuilderOutput(
                patch=(
                    "diff --git a/app.py b/app.py\n"
                    "--- a/app.py\n"
                    "+++ b/app.py\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
                touched_files=["app.py"],
                summary="tier policy test patch",
                confidence=0.6,
            )
        ]
    )


def pricing(output_tokens: int = 100) -> PricingSettings:
    # Every live-callable role (live_calls_disabled=False) needs a "{role}:flex"
    # pricing entry, or AppConfig's strict Flex-only policy validator rejects
    # construction. Derive the role list from the default registry so this stays
    # correct as roles are added/changed.
    live_roles = [
        name for name, role in AppConfig().model_roles.roles.items() if not role.live_calls_disabled
    ]
    return PricingSettings(
        roles={
            f"{role}:flex": ModelPricing(
                provider="openai",
                model="gpt-5.4-mini",
                inference_tier="flex",
                service_tier="flex",
                input_usd_per_1m_tokens=0.375,
                output_usd_per_1m_tokens=2.25,
                max_output_tokens=output_tokens,
                budget_pool="builder",
            )
            for role in live_roles
        }
    )


def config(
    tmp_path: Path,
    tier_settings: BuilderServiceTierSettings | None = None,
    output_tokens: int = 100,
) -> AppConfig:
    return AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=BudgetSettings(
            ledger_path=str(tmp_path / "budget.sqlite"),
            project_id="tier-tests",
            project_total_budget_usd=10.0,
            role_budgets_usd={"simple_builder": 10.0},
            max_task_cost_usd=10.0,
            max_project_cost_usd=10.0,
        ),
        inference=AppConfig().inference.model_copy(
            update={"builder_service_tier": tier_settings or BuilderServiceTierSettings()}
        ),
        pricing=pricing(output_tokens),
    )


def test_flex_selected_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_repo(tmp_path)
    provider = real_patch_provider()
    engine = WorkflowEngine(config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    state = engine.run_task(
        TaskSpec(id="T-FLEX", title="Fix bug", max_cost_usd=10, allowed_files=["app.py"])
    )

    assert state.final_status == "completed"
    assert state.tool_results["builder"]["tier"] == "flex"
    assert state.tool_results["builder"]["service_tier"] == "flex"
    assert state.tool_results["requested_service_tier"] == "flex"
    assert state.tool_results["actual_service_tier"] == "flex"


def test_flex_transient_error_retries_on_flex_only_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # A transient Flex error must trigger a bounded retry that stays on Flex --
    # never a switch to any other tier.
    init_repo(tmp_path)
    engine = WorkflowEngine(
        config(
            tmp_path,
            BuilderServiceTierSettings(flex=FlexTierSettings(max_flex_retries=2)),
        )
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    call_count = {"n": 0}
    requested_tiers: list[str] = []

    def flaky_generate(request: ProviderRequest):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        requested_tiers.append(request.role.service_tier)
        if call_count["n"] == 1:
            raise ProviderError("429 resource unavailable on flex tier")
        return real_patch_provider().generate(request)

    monkeypatch.setattr(engine.openai_provider, "generate", flaky_generate)

    state = engine.run_task(
        TaskSpec(id="T-RETRY", title="Fix bug", max_cost_usd=10, allowed_files=["app.py"])
    )

    assert state.final_status == "completed"
    assert state.tool_results["builder"]["tier"] == "flex"
    assert state.tool_results["builder"]["service_tier"] == "flex"
    assert set(requested_tiers) == {"flex"}  # every attempt requested Flex, no exceptions
    assert call_count["n"] == 2


def test_flex_unavailable_after_bounded_retries_exhausted_preserves_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    engine = WorkflowEngine(
        config(
            tmp_path,
            BuilderServiceTierSettings(flex=FlexTierSettings(max_flex_retries=1)),
        )
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))

    requested_tiers: list[str] = []

    def always_flaky(request: ProviderRequest):  # type: ignore[no-untyped-def]
        requested_tiers.append(request.role.service_tier)
        raise ProviderError("429 resource unavailable on flex tier")

    monkeypatch.setattr(engine.openai_provider, "generate", always_flaky)

    state = engine.run_task(
        TaskSpec(id="T-UNAVAILABLE", title="Fix bug", max_cost_usd=10, allowed_files=["app.py"])
    )

    assert state.final_status == "flex_unavailable"
    assert set(requested_tiers) == {"flex"}
    # max_flex_retries=1 -> 2 total attempts (initial + 1 retry), never more, never a
    # different tier.
    assert len(requested_tiers) == 2
    assert "No higher-priced tier was used" in state.validation_results["service_tier"]["message"]
    # Repository preserved exactly: no patch was ever applied, nothing to roll back.
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"
    status = subprocess.run(
        ["git", "status", "--short"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert "app.py" not in status


def test_report_includes_service_tier_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    provider = real_patch_provider()
    engine = WorkflowEngine(config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    engine.run_task(
        TaskSpec(id="T-REPORT", title="Fix bug", max_cost_usd=10, allowed_files=["app.py"])
    )
    report = engine.budget_report()

    assert report.calls_by_service_tier["flex"] == 1
    assert report.estimated_cost_by_service_tier_usd["flex"] > 0
    # Automatic fallback is structurally impossible under the strict Flex-only
    # policy -- this must always be exactly 0.
    assert report.service_tier_fallbacks == 0

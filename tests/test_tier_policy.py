from __future__ import annotations

from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    BudgetSettings,
    CheapBuilderTierSettings,
    FlexTierSettings,
    ModelPricing,
    OpenCodeSettings,
    PricingSettings,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import BuilderResult, TaskSpec
from coding_orchestrator.tools.opencode_runner import OpenCodeExecutionError, OpenCodeRunner


def pricing(output_tokens: int = 100) -> PricingSettings:
    return PricingSettings(
        roles={
            "cheap_builder:flex": ModelPricing(
                provider="google-gemini",
                model="gemini-3.1-flash-lite",
                inference_tier="flex",
                input_usd_per_1m_tokens=0.125,
                output_usd_per_1m_tokens=0.75,
                max_output_tokens=output_tokens,
                budget_pool="cheap_builder",
            ),
            "cheap_builder:standard": ModelPricing(
                provider="google-gemini",
                model="gemini-3.1-flash-lite",
                inference_tier="standard",
                input_usd_per_1m_tokens=0.25,
                output_usd_per_1m_tokens=1.50,
                max_output_tokens=output_tokens,
                budget_pool="cheap_builder",
            ),
        }
    )


def config(
    tmp_path: Path,
    tier_settings: CheapBuilderTierSettings | None = None,
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
            cheap_builder_budget_usd=10.0,
            max_task_cost_usd=10.0,
            max_project_cost_usd=10.0,
        ),
        inference=AppConfig().inference.model_copy(
            update={"cheap_builder": tier_settings or CheapBuilderTierSettings()}
        ),
        pricing=pricing(output_tokens),
        opencode=OpenCodeSettings(enabled=False, dry_run=True),
    )


def test_flex_selected_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = WorkflowEngine(config(tmp_path))
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    monkeypatch.setattr(engine, "_commit", lambda task, state: None)

    state = engine.run_task(TaskSpec(id="T-FLEX", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "completed"
    assert state.tool_results["builder"]["tier"] == "flex"
    assert state.tool_results["builder"]["model"] == "gemini-3.1-flash-lite"


def test_standard_fallback_after_flex_timeout_threshold(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            CheapBuilderTierSettings(
                flex=FlexTierSettings(max_consecutive_timeouts=1, timeout_rate_threshold=1.0)
            ),
        )
    )
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    monkeypatch.setattr(engine, "_commit", lambda task, state: None)

    def fake_run(self: OpenCodeRunner, task: TaskSpec, context: str) -> BuilderResult:
        if self.settings and self.settings.max_runtime_seconds == 600:
            raise OpenCodeExecutionError("flex timeout", timed_out=True)
        return BuilderResult(
            text="",
            confidence=0.0,
            estimated_output_tokens=1,
            dry_run=True,
        )

    monkeypatch.setattr(OpenCodeRunner, "run_bounded_step", fake_run)

    state = engine.run_task(TaskSpec(id="T-STANDARD", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "completed"
    assert state.tool_results["builder"]["tier"] == "standard"
    report = engine.budget_report()
    assert report.flex_timeouts == 1
    assert report.standard_fallbacks == 1


def test_standard_fallback_blocked_by_cost_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            CheapBuilderTierSettings(
                flex=FlexTierSettings(max_consecutive_timeouts=1),
                max_standard_fallback_cost_usd_per_run=0.000001,
            ),
        )
    )

    def fake_run(self: OpenCodeRunner, task: TaskSpec, context: str) -> BuilderResult:
        raise OpenCodeExecutionError("flex timeout", timed_out=True)

    monkeypatch.setattr(OpenCodeRunner, "run_bounded_step", fake_run)

    state = engine.run_task(TaskSpec(id="T-COST", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "blocked"
    assert "standard fallback cost budget" in state.validation_results["budget"]["message"]


def test_standard_fallback_blocked_by_count_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            CheapBuilderTierSettings(
                flex=FlexTierSettings(max_consecutive_timeouts=1),
                max_standard_fallbacks_per_run=0,
            ),
        )
    )

    def fake_run(self: OpenCodeRunner, task: TaskSpec, context: str) -> BuilderResult:
        raise OpenCodeExecutionError("flex timeout", timed_out=True)

    monkeypatch.setattr(OpenCodeRunner, "run_bounded_step", fake_run)

    state = engine.run_task(TaskSpec(id="T-COUNT", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "blocked"
    assert "standard fallback limit" in state.validation_results["budget"]["message"]


def test_report_includes_tier_usage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    engine = WorkflowEngine(config(tmp_path))
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    monkeypatch.setattr(engine, "_commit", lambda task, state: None)

    engine.run_task(TaskSpec(id="T-REPORT", title="Fix bug", max_cost_usd=10))
    report = engine.budget_report()

    assert report.calls_by_tier["flex"] == 1
    assert report.estimated_cost_by_tier_usd["flex"] > 0

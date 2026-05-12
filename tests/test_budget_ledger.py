from __future__ import annotations

from pathlib import Path

import pytest

from coding_orchestrator.config import AppConfig, BudgetSettings, ModelPricing, PricingSettings
from coding_orchestrator.orchestrator.budget import BudgetExceeded, BudgetGuard, BudgetLedger
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec


def pricing(output_tokens: int = 1000) -> PricingSettings:
    return PricingSettings(
        roles={
            "general_builder:flex": ModelPricing(
                provider="test",
                model="builder-flex",
                inference_tier="flex",
                input_usd_per_1m_tokens=1.0,
                output_usd_per_1m_tokens=2.0,
                max_output_tokens=output_tokens,
                budget_pool="builder",
            ),
            "frontier_reviewer:default": ModelPricing(
                provider="test",
                model="reviewer-default",
                inference_tier="default",
                input_usd_per_1m_tokens=10.0,
                output_usd_per_1m_tokens=20.0,
                max_output_tokens=output_tokens,
                budget_pool="reviewer",
            ),
        }
    )


def budget_settings(
    path: Path,
    *,
    project_id: str = "test-project",
    project_total_budget_usd: float = 10.0,
    role_budgets_usd: dict[str, float] | None = None,
    max_task_cost_usd: float = 10.0,
    max_project_cost_usd: float = 10.0,
) -> BudgetSettings:
    role_budgets = role_budgets_usd or {"general_builder": 10.0}
    return BudgetSettings(
        ledger_path=str(path),
        project_id=project_id,
        project_total_budget_usd=project_total_budget_usd,
        role_budgets_usd=role_budgets,
        max_task_cost_usd=max_task_cost_usd,
        max_project_cost_usd=max_project_cost_usd,
    )


def test_budget_ledger_persists_events(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite"
    guard = BudgetGuard(budget_settings(path), pricing())
    task = TaskSpec(id="T-1", title="x", max_cost_usd=10)
    estimate = guard.estimate_pre_call(
        task=task,
        attempt_id=1,
        model_role="general_builder",
        context="abcd" * 100,
        inference_tier="flex",
    )
    guard.record_estimate(estimate)

    reopened = BudgetLedger(path)

    assert reopened.spend_for_project("test-project") == pytest.approx(
        estimate.estimated_total_cost_usd
    )


def test_estimate_calculation_uses_configured_prices(tmp_path: Path) -> None:
    guard = BudgetGuard(budget_settings(tmp_path / "budget.sqlite"), pricing(output_tokens=100))
    estimate = guard.estimate_pre_call(
        task=TaskSpec(id="T-1", title="x"),
        attempt_id=1,
        model_role="general_builder",
        context="abcd" * 100,
        inference_tier="flex",
    )

    assert estimate.estimated_input_tokens == 100
    assert estimate.estimated_output_tokens == 100
    assert estimate.estimated_input_cost_usd == pytest.approx(0.0001)
    assert estimate.estimated_output_cost_usd == pytest.approx(0.0002)
    assert estimate.estimated_total_cost_usd == pytest.approx(0.0003)


def test_budget_exceeded_blocks_call_and_records_block(tmp_path: Path) -> None:
    guard = BudgetGuard(
        budget_settings(tmp_path / "budget.sqlite", max_task_cost_usd=0.00001),
        pricing(output_tokens=1000),
    )
    task = TaskSpec(id="T-1", title="x", max_cost_usd=0.00001)
    estimate = guard.estimate_pre_call(
        task=task,
        attempt_id=1,
        model_role="general_builder",
        context="abcd" * 1000,
        inference_tier="flex",
    )

    with pytest.raises(BudgetExceeded):
        guard.check_pre_call(task, estimate)

    report = guard.report()
    assert report.blocked_calls == 1
    assert report.project_total_spend_usd == 0


def test_role_specific_budget_pool_is_enforced(tmp_path: Path) -> None:
    guard = BudgetGuard(
        budget_settings(
            tmp_path / "budget.sqlite",
            role_budgets_usd={"general_builder": 0.00001},
        ),
        pricing(output_tokens=1000),
    )
    task = TaskSpec(id="T-1", title="x", max_cost_usd=10)
    estimate = guard.estimate_pre_call(
        task=task,
        attempt_id=1,
        model_role="general_builder",
        context="abcd" * 1000,
        inference_tier="flex",
    )

    with pytest.raises(BudgetExceeded, match="general_builder budget"):
        guard.check_pre_call(task, estimate)


def test_project_budget_persists_across_engine_instances(tmp_path: Path) -> None:
    ledger_path = tmp_path / "budget.sqlite"
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=budget_settings(
            ledger_path,
            project_total_budget_usd=0.0005,
            role_budgets_usd={"general_builder": 10.0},
        ),
        pricing=pricing(output_tokens=100),
    )
    first = WorkflowEngine(config)
    task = TaskSpec(id="T-1", title="x", max_cost_usd=10)
    estimate = first.budget.estimate_pre_call(
        task=task,
        attempt_id=1,
        model_role="general_builder",
        context="abcd" * 100,
        inference_tier="flex",
    )
    first.budget.record_estimate(estimate)

    second = WorkflowEngine(config)
    next_estimate = second.budget.estimate_pre_call(
        task=task,
        attempt_id=2,
        model_role="general_builder",
        context="abcd" * 100,
        inference_tier="flex",
    )

    with pytest.raises(BudgetExceeded, match="project_total budget"):
        second.budget.check_pre_call(task, next_estimate)

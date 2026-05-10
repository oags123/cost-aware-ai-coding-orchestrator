from __future__ import annotations

from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    BudgetSettings,
    LimitSettings,
    ModelPricing,
    PricingSettings,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.orchestrator.limits import LimitExceeded, LimitGuard
from coding_orchestrator.schemas import BuilderResult, TaskSpec, ValidationResult
from coding_orchestrator.tools.patch import parse_builder_output


def pricing(output_tokens: int = 1000) -> PricingSettings:
    return PricingSettings(
        roles={
            "cheap_builder": ModelPricing(
                provider="test",
                model="cheap",
                input_usd_per_1m_tokens=1.0,
                output_usd_per_1m_tokens=2.0,
                max_output_tokens=output_tokens,
                budget_pool="cheap_builder",
            )
        }
    )


def app_config(tmp_path: Path, limits: LimitSettings, output_tokens: int = 1000) -> AppConfig:
    return AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=BudgetSettings(
            ledger_path=str(tmp_path / "budget.sqlite"),
            project_id="limit-tests",
            project_total_budget_usd=10.0,
            cheap_builder_budget_usd=10.0,
            max_task_cost_usd=10.0,
            max_project_cost_usd=10.0,
        ),
        limits=limits,
        pricing=pricing(output_tokens),
    )


def test_context_too_large_blocks_call_and_records_ledger(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        app_config(
            tmp_path,
            LimitSettings(max_context_chars_per_call=10),
        )
    )
    task = TaskSpec(id="T-LIMIT", title="Fix bug", description="x" * 100, max_cost_usd=10)

    state = engine.run_task(task)

    assert state.final_status == "blocked"
    assert state.validation_results["limits"]["details"]["status"] == "context_limit_exceeded"
    report = engine.budget_report()
    assert report.blocked_calls == 1
    assert report.limit_failures["context_limit_exceeded"] == 1
    assert report.largest_context_chars > 10


def test_output_token_estimate_blocks_call(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        app_config(
            tmp_path,
            LimitSettings(max_output_tokens_per_call=10),
            output_tokens=100,
        )
    )
    task = TaskSpec(id="T-OUTPUT", title="Fix bug", max_cost_usd=10)

    state = engine.run_task(task)

    assert state.final_status == "blocked"
    assert state.validation_results["limits"]["details"]["status"] == "output_limit_exceeded"
    assert engine.budget_report().limit_failures["output_limit_exceeded"] == 1


def test_patch_too_large_rejected() -> None:
    parsed = parse_builder_output(
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        f"+{'x' * 100}\n"
    )
    assert parsed is not None

    with pytest.raises(LimitExceeded, match="Patch size exceeds"):
        LimitGuard(LimitSettings(max_patch_bytes=20)).check_patch(parsed)


def test_stdout_stderr_too_large_can_be_truncated() -> None:
    guard = LimitGuard(
        LimitSettings(
            max_stdout_bytes=8,
            max_stderr_bytes=4,
            output_over_limit_policy="truncate",
        )
    )
    result = guard.check_builder_output(
        BuilderResult(
            text="x" * 20,
            stdout="x" * 20,
            stderr="y" * 10,
            confidence=0.0,
            estimated_output_tokens=5,
        )
    )

    assert len(result.stdout.encode("utf-8")) == 8
    assert len(result.stderr.encode("utf-8")) == 4
    assert guard.metrics.largest_stdout_bytes == 20
    assert guard.metrics.largest_stderr_bytes == 10


def test_validation_output_too_large_can_be_summarized_safely() -> None:
    guard = LimitGuard(
        LimitSettings(
            max_validation_output_bytes=20,
            validation_output_over_limit_policy="truncate",
        )
    )
    results = guard.enforce_validation_output(
        [
            ValidationResult(
                name="tests",
                passed=False,
                message="m" * 100,
                details={"pytest": {"stdout": "x" * 100, "stderr": "y" * 100}},
            )
        ]
    )

    assert results[0].details["_limit_notice"] == (
        "validation_output_limit_exceeded; output truncated"
    )
    assert guard.metrics.limit_failures["validation_output_limit_exceeded"] == 1


def test_budget_ledger_records_limit_blocked_calls(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        app_config(
            tmp_path,
            LimitSettings(max_input_tokens_per_call=1),
        )
    )
    task = TaskSpec(id="T-TOKENS", title="Fix bug", description="abcd" * 20, max_cost_usd=10)

    state = engine.run_task(task)

    assert state.final_status == "blocked"
    report = engine.budget_report()
    assert report.blocked_calls == 1
    assert report.limit_failures["context_limit_exceeded"] == 1

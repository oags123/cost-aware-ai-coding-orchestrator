from __future__ import annotations

import subprocess
from pathlib import Path

from coding_orchestrator.config import AppConfig, BudgetSettings, ConvergenceSettings
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.orchestrator.convergence import ConvergenceEvaluator
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import AttemptMetrics, TaskSpec, ValidationResult


def init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    target = path / "app.py"
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)


def metrics(
    *,
    attempt: int,
    errors: int,
    tests: int = 0,
    files: int = 1,
    patch: int = 100,
    signatures: list[str] | None = None,
    new_failures: bool = False,
    repeated_failures: bool = False,
    unrelated: bool = False,
    syntax: bool = False,
) -> AttemptMetrics:
    return AttemptMetrics(
        attempt_number=attempt,
        validation_status="failed" if errors else "passed",
        validator_error_count=errors,
        failing_test_count=tests,
        changed_file_count=files,
        patch_size_bytes=patch,
        failure_signatures=signatures or ["tests:failed"],
        repeated_failures=repeated_failures,
        new_failures=new_failures,
        unrelated_file_touch=unrelated,
        syntax_regression=syntax,
    )


def test_convergence_detected() -> None:
    evaluator = ConvergenceEvaluator(ConvergenceSettings())
    previous = metrics(attempt=1, errors=3, tests=2, files=3, patch=300)
    current = metrics(attempt=2, errors=1, tests=1, files=1, patch=100)

    decision = evaluator.evaluate(current, previous)

    assert decision.status == "converging"
    assert decision.action == "continue_current_role_retry"
    assert decision.improvement_score > 0


def test_stagnation_detected() -> None:
    evaluator = ConvergenceEvaluator(ConvergenceSettings())
    previous = metrics(attempt=1, errors=2, signatures=["tests:same"])
    current = metrics(
        attempt=2,
        errors=2,
        signatures=["tests:same"],
        repeated_failures=True,
        new_failures=False,
    )

    decision = evaluator.evaluate(current, previous)

    assert decision.status == "stagnating"


def test_divergence_detected() -> None:
    evaluator = ConvergenceEvaluator(ConvergenceSettings(max_patch_growth_ratio=1.2))
    previous = metrics(attempt=1, errors=1, patch=100)
    current = metrics(attempt=2, errors=2, patch=300)

    decision = evaluator.evaluate(current, previous)

    assert decision.status == "diverging"
    assert decision.action == "request_diagnosis"


def test_repeated_same_failure_and_new_failure_detected() -> None:
    evaluator = ConvergenceEvaluator(ConvergenceSettings())
    previous = metrics(attempt=1, errors=1, signatures=["tests:a"])
    results = [
        ValidationResult(name="tests", passed=False, message="a"),
        ValidationResult(name="syntax", passed=False, message="b"),
    ]

    collected = evaluator.collect_attempt_metrics(
        attempt_number=2,
        validation_results=results,
        changed_files=["app.py"],
        allowed_files=["app.py"],
        tool_results={},
        previous=previous,
    )

    assert collected.repeated_failures
    assert collected.new_failures


def test_hard_stop_conditions() -> None:
    evaluator = ConvergenceEvaluator(ConvergenceSettings())
    current = metrics(attempt=1, errors=1, unrelated=True, syntax=True)

    decision = evaluator.evaluate(current)

    assert decision.status == "diverging"
    assert decision.action == "pause_block_task"


def test_diagnosis_needed_package_generated(tmp_path: Path) -> None:
    init_repo(tmp_path)
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=BudgetSettings(
            ledger_path=str(tmp_path / "budget.sqlite"),
            project_id="convergence-tests",
            project_total_budget_usd=10,
            role_budgets_usd={"general_builder": 10},
            max_task_cost_usd=10,
            max_project_cost_usd=10,
        ),
        convergence=ConvergenceSettings(max_stagnant_attempts=0),
    )
    engine = WorkflowEngine(config, provider_overrides={"openai": FakeModelProvider(["", ""])})
    task = TaskSpec(id="T-CONV", title="Fix bug", max_attempts=2, max_cost_usd=10)
    failures = [ValidationResult(name="tests", passed=False, message="failed")]
    engine._validate = lambda task: failures  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(task)

    assert state.final_status == "escalated"
    assert state.convergence_status == "non_converging"
    assert "diagnosis_needed_package" in state.tool_results
    assert "handoff_package" in state.tool_results
    handoff_path = Path(state.tool_results["handoff_package"])
    assert handoff_path.exists()
    content = handoff_path.read_text(encoding="utf-8")
    assert "reason: non_converging" in content
    assert "T-CONV" in content

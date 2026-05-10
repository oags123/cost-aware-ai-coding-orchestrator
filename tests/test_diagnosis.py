from __future__ import annotations

from pathlib import Path

from coding_orchestrator.config import (
    AppConfig,
    BudgetSettings,
    ConvergenceSettings,
    DiagnosisSettings,
)
from coding_orchestrator.orchestrator.diagnosis import (
    DiagnosisReviewer,
    ReviewPacketBuilder,
    packet_to_prompt,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import OrchestratorState, TaskSpec, ValidationResult


def test_review_packet_is_compact_and_diagnosis_only() -> None:
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])
    state = OrchestratorState(
        request_id="r",
        user_request="fix",
        task_id="T-1",
        tool_results={"patch": {"touched_files": ["app.py"]}},
    )

    packet = ReviewPacketBuilder(DiagnosisSettings(max_packet_chars=600)).build(
        task=task,
        state=state,
        diff="x" * 2000,
        logs=["builder stdout:\n" + "a" * 1000],
        validation_errors=["pytest failed"],
        remaining_task_usd=0.01,
        projected_review_usd=0.02,
    )

    text = packet_to_prompt(packet)
    assert len(text) <= 700
    assert packet.question["type"] == "diagnosis"
    assert "Do not produce a patch" in packet.question["prompt"]


def test_dry_run_diagnosis_interface_returns_structured_result() -> None:
    packet = ReviewPacketBuilder(DiagnosisSettings()).build(
        task=TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]),
        state=OrchestratorState(request_id="r", user_request="fix"),
        diff="",
        logs=[],
        validation_errors=["pytest failed"],
        remaining_task_usd=0.01,
        projected_review_usd=0.02,
    )

    result = DiagnosisReviewer(DiagnosisSettings(enabled=True, dry_run=True)).diagnose(packet)

    assert result.recommended_next_instruction
    assert not result.direct_patch_proposed


def config(tmp_path: Path, diagnosis: DiagnosisSettings) -> AppConfig:
    return AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=BudgetSettings(
            ledger_path=str(tmp_path / "budget.sqlite"),
            project_id="diagnosis-tests",
            project_total_budget_usd=10,
            cheap_builder_budget_usd=10,
            expensive_reviewer_budget_usd=10,
            max_task_cost_usd=10,
            max_project_cost_usd=10,
        ),
        convergence=ConvergenceSettings(max_stagnant_attempts=0),
        diagnosis=diagnosis,
    )


def test_diagnosis_disabled_still_creates_review_packet(tmp_path: Path) -> None:
    engine = WorkflowEngine(config(tmp_path, DiagnosisSettings(enabled=False)))
    failures = [ValidationResult(name="tests", passed=False, message="failed")]
    engine._validate = lambda task: failures  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(TaskSpec(id="T-DISABLED", title="Fix bug", max_cost_usd=10))

    assert "review_packet" in state.tool_results
    assert "diagnosis" not in state.tool_results
    assert "diagnosis_needed_package" in state.tool_results


def test_diagnosis_enabled_dry_run_records_result(tmp_path: Path) -> None:
    engine = WorkflowEngine(config(tmp_path, DiagnosisSettings(enabled=True, dry_run=True)))
    failures = [ValidationResult(name="tests", passed=False, message="failed")]
    engine._validate = lambda task: failures  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(TaskSpec(id="T-ENABLED", title="Fix bug", max_cost_usd=10))

    assert "diagnosis" in state.tool_results
    assert "diagnosis_budget_estimate" in state.tool_results


def test_diagnosis_budget_block_blocks_reviewer_call(tmp_path: Path) -> None:
    app_config = config(tmp_path, DiagnosisSettings(enabled=True, dry_run=True))
    app_config.budget = app_config.budget.model_copy(update={"expensive_reviewer_budget_usd": 0.0})
    engine = WorkflowEngine(app_config)
    failures = [ValidationResult(name="tests", passed=False, message="failed")]
    engine._validate = lambda task: failures  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(TaskSpec(id="T-BUDGET", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "blocked"
    assert "expensive_reviewer budget" in state.validation_results["budget"]["message"]

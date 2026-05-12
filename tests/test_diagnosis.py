from __future__ import annotations

from pathlib import Path

from coding_orchestrator.config import (
    AppConfig,
    BudgetSettings,
    ConvergenceSettings,
    DiagnosisSettings,
)
from coding_orchestrator.orchestrator.budget import BudgetExceeded
from coding_orchestrator.orchestrator.diagnosis import (
    DiagnosisError,
    DiagnosisReviewer,
    ReviewPacketBuilder,
    packet_to_prompt,
    validate_diagnosis_result,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import (
    BuilderResult,
    DiagnosisResult,
    OrchestratorState,
    TaskSpec,
    ValidationResult,
)


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
    assert len(text) <= 800
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

    assert result.recommended_next_action
    assert result.guided_fix_instruction
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
            role_budgets_usd={"frontier_reviewer": 10, "general_builder": 10},
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
    app_config.budget = app_config.budget.model_copy(
        update={"role_budgets_usd": {"frontier_reviewer": 0.0}}
    )
    engine = WorkflowEngine(app_config)
    failures = [ValidationResult(name="tests", passed=False, message="failed")]
    engine._validate = lambda task: failures  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(TaskSpec(id="T-BUDGET", title="Fix bug", max_cost_usd=10))

    assert state.final_status == "blocked"
    assert "frontier_reviewer budget" in state.validation_results["budget"]["message"]


def test_reviewer_direct_patch_rejected() -> None:
    result = DiagnosisResult(
        root_cause="x",
        minimal_fix_strategy="diff --git a/app.py b/app.py",
        guided_fix_instruction="focus app.py",
        direct_patch_proposed=True,
    )

    try:
        validate_diagnosis_result(result, DiagnosisSettings(enabled=True))
    except DiagnosisError as exc:
        assert "direct" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected direct patch rejection")


def test_reviewer_shell_command_rejected() -> None:
    result = DiagnosisResult(
        root_cause="x",
        minimal_fix_strategy="narrow fix",
        guided_fix_instruction="run pytest tests/test_app.py",
    )

    try:
        validate_diagnosis_result(result, DiagnosisSettings(enabled=True))
    except DiagnosisError as exc:
        assert "diagnosis-only contract" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected shell command rejection")


def test_valid_diagnosis_accepted() -> None:
    result = DiagnosisResult(
        root_cause="test expectation mismatch",
        minimal_fix_strategy="adjust the allowed file only",
        files_to_focus=["app.py"],
        risks=["keep scope small"],
        guided_fix_instruction="Focus on app.py and address the current validator failure.",
        confidence=0.7,
        should_retry_with_builder=True,
    )

    accepted = validate_diagnosis_result(result, DiagnosisSettings(enabled=True))

    assert accepted.should_retry_with_builder


def test_diagnosis_feeds_guided_builder_retry(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            DiagnosisSettings(enabled=True, dry_run=True),
        ).model_copy(update={"convergence": ConvergenceSettings(max_stagnant_attempts=0)})
    )
    contexts: list[str] = []

    def fake_builder(
        task: TaskSpec,
        state: OrchestratorState,
        context: str,
    ) -> BuilderResult:
        contexts.append(context)
        return BuilderResult(text="", confidence=0.0, estimated_output_tokens=1, dry_run=True)

    validations = [
        [ValidationResult(name="tests", passed=False, message="failed")],
        [ValidationResult(name="tests", passed=False, message="failed")],
        [],
    ]
    engine._run_tiered_builder = fake_builder  # type: ignore[method-assign]  # noqa: SLF001
    engine._validate = lambda task: validations.pop(0)  # type: ignore[method-assign]  # noqa: SLF001
    engine._commit = lambda task, state: None  # type: ignore[method-assign]  # noqa: SLF001

    state = engine.run_task(
        TaskSpec(id="T-GUIDED", title="Fix bug", max_attempts=3, max_cost_usd=10)
    )

    assert state.final_status == "completed"
    assert any("Diagnosis-only reviewer guidance" in context for context in contexts)


def test_max_reviewer_calls_per_task_enforced(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            DiagnosisSettings(enabled=True, dry_run=True, max_calls_per_task=0),
        )
    )
    packet = engine._build_review_packet(  # noqa: SLF001
        TaskSpec(id="T-CALLS", title="Fix bug", max_cost_usd=10),
        OrchestratorState(request_id="r", user_request="fix"),
        ["failed"],
    )

    try:
        engine._run_diagnosis_reviewer(  # noqa: SLF001
            TaskSpec(id="T-CALLS", title="Fix bug", max_cost_usd=10),
            OrchestratorState(request_id="r", user_request="fix"),
            packet,
        )
    except BudgetExceeded as exc:
        assert "max_calls_per_task" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected reviewer call limit")


def test_max_reviewer_calls_per_run_enforced(tmp_path: Path) -> None:
    engine = WorkflowEngine(
        config(
            tmp_path,
            DiagnosisSettings(enabled=True, dry_run=True, max_calls_per_run=0),
        )
    )
    task = TaskSpec(id="T-RUN", title="Fix bug", max_cost_usd=10)
    state = OrchestratorState(request_id="r", user_request="fix")
    packet = engine._build_review_packet(task, state, ["failed"])  # noqa: SLF001

    try:
        engine._run_diagnosis_reviewer(task, state, packet)  # noqa: SLF001
    except BudgetExceeded as exc:
        assert "max_calls_per_run" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected reviewer run limit")

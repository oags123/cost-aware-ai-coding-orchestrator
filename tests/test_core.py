from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from coding_orchestrator.config import AppConfig, BudgetSettings, ValidationSettings
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.provider import BuilderOutput
from coding_orchestrator.models.router import ModelRouter
from coding_orchestrator.orchestrator.budget import BudgetGuard
from coding_orchestrator.orchestrator.engine import WorkflowEngine, order_tasks
from coding_orchestrator.orchestrator.router import TaskClassifier
from coding_orchestrator.orchestrator.timeouts import TimeoutGuard
from coding_orchestrator.schemas import (
    BuilderResult,
    CommandResult,
    OrchestratorState,
    TaskSpec,
    ValidationResult,
)
from coding_orchestrator.tools.shell import run_limited_command
from coding_orchestrator.validators.patch_validator import PatchValidator
from coding_orchestrator.validators.permission_validator import PermissionValidator


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


def real_patch_provider(touched_file: str = "app.py", attempts: int = 1) -> FakeModelProvider:
    output = BuilderOutput(
        patch=(
            f"diff --git a/{touched_file} b/{touched_file}\n"
            f"--- a/{touched_file}\n"
            f"+++ b/{touched_file}\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        ),
        touched_files=[touched_file],
        summary="test patch",
        confidence=0.8,
    )
    return FakeModelProvider([output] * attempts)


def test_task_and_complexity_classification() -> None:
    task = TaskSpec(id="T-1", title="Fix login bug", complexity="medium", risk="low")
    classifier = TaskClassifier()

    assert classifier.classify_task_type(task) == "fix_bug"
    assert classifier.classify_complexity(task) == "medium"
    assert classifier.classify_risk(task) == "low"


def test_model_routing_uses_minimum_required_tier() -> None:
    router = ModelRouter()

    assert router.select_model("simple", "low") == "mechanical_worker"
    assert router.select_model("hard", "high") == "frontier_reviewer"
    assert router.select_model("critical", "high") == "human-approval"


def test_timeout_wrapper_marks_timeout(tmp_path: Path) -> None:
    result = run_limited_command(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        tmp_path,
        0.01,
        [sys.executable],
    )

    assert result.timed_out
    assert result.returncode == 124


def test_timeout_guard_remaining() -> None:
    guard = TimeoutGuard(10)

    assert guard.remaining() > 0


def test_budget_guard_blocks_task_over_limit() -> None:
    guard = BudgetGuard(BudgetSettings(max_task_cost_usd=0.01, max_project_cost_usd=1.0))
    task = TaskSpec(id="T-1", title="x", max_cost_usd=0.01)
    state = OrchestratorState(request_id="r", user_request="x", estimated_cost_usd=0.02)

    assert not guard.can_spend(task, state)


def test_patch_validator_rejects_forbidden_and_unallowed_paths(tmp_path: Path) -> None:
    result = PatchValidator(
        changed_files=[".env"],
        workspace=tmp_path,
        allowed_files=["src/app.py"],
        settings=ValidationSettings(),
    ).validate()

    assert not result.passed
    assert "forbidden" in result.message


def test_permission_validator_accepts_allowed_workspace_file(tmp_path: Path) -> None:
    result = PermissionValidator(
        paths=["src/app.py"],
        workspace=tmp_path,
        allowed_files=["src/app.py"],
        forbidden_paths=[],
    ).validate()

    assert result.passed


def test_dependency_ordering() -> None:
    first = TaskSpec(id="T-1", title="first")
    second = TaskSpec(id="T-2", title="second", depends_on=["T-1"])

    assert [task.id for task in order_tasks([second, first])] == ["T-1", "T-2"]


def test_workflow_success_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )
    engine = WorkflowEngine(config, provider_overrides={"openai": real_patch_provider()})
    task = TaskSpec(
        id="T-1",
        title="Fix bug",
        allowed_files=["app.py"],
        validation_commands=["python -c 'pass'"],
    )

    monkeypatch.setattr(engine, "_validate", lambda task: [])

    state = engine.run_task(task)

    assert state.final_status == "completed"


def test_workflow_failure_retries_rolls_back_and_escalates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )
    engine = WorkflowEngine(config)
    task = TaskSpec(
        id="T-1",
        title="Fix bug",
        max_attempts=2,
        escalation_allowed=True,
        allowed_files=["app.py"],
    )
    rollback_calls: list[bool] = []

    def no_op_builder(task: TaskSpec, state: OrchestratorState, context: str) -> BuilderResult:
        return BuilderResult(text="", confidence=0.0, estimated_output_tokens=1, dry_run=False)

    monkeypatch.setattr(engine, "_run_tiered_builder", no_op_builder)
    monkeypatch.setattr(
        engine,
        "_validate",
        lambda task: [ValidationResult(name="tests", passed=False, message="failed")],
    )
    monkeypatch.setattr(
        engine.git,
        "rollback_to_checkpoint",
        lambda checkpoint, preserve_dirs, preserve_files: rollback_calls.append(True),
    )
    monkeypatch.setattr(engine.git, "diff", lambda: "diff")

    state = engine.run_task(task)

    assert state.retry_count == 2
    assert rollback_calls
    assert state.final_status == "escalated"
    assert "escalation_package" in state.tool_results


def test_commit_failure_does_not_complete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )
    engine = WorkflowEngine(config, provider_overrides={"openai": real_patch_provider()})
    task = TaskSpec(id="T-1", title="Fix bug", max_attempts=1, allowed_files=["app.py"])

    monkeypatch.setattr(engine, "_validate", lambda task: [])
    monkeypatch.setattr(
        engine.git,
        "commit_task",
        lambda task_id, title, changed_files, allowed_files: CommandResult(
            command=["git", "commit"],
            returncode=128,
            stdout="",
            stderr="missing identity",
        ),
    )
    monkeypatch.setattr(engine.git, "diff", lambda: "")
    monkeypatch.setattr(
        engine.git,
        "rollback_to_checkpoint",
        lambda checkpoint, preserve_dirs, preserve_files: CommandResult(
            command=["git", "restore"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    state = engine.run_task(task)

    assert state.final_status == "failed"
    assert state.tool_results["git_commit"]["returncode"] == 128

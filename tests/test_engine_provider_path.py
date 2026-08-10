from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from coding_orchestrator.config import AppConfig
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.provider import BuilderOutput
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec, ValidationResult


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


def build_provider_engine(
    tmp_path: Path,
    provider: FakeModelProvider,
) -> WorkflowEngine:
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )
    return WorkflowEngine(config, provider_overrides={"openai": provider})


def test_engine_selects_mechanical_worker_for_tiny_validated_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider(
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
                summary="tiny edit",
                confidence=0.8,
            )
        ]
    )
    engine = build_provider_engine(tmp_path, provider)
    task = TaskSpec(
        id="T-1",
        title="Write tests for helper",
        complexity="simple",
        risk="low",
        allowed_files=["app.py"],
        validation_commands=["python -c 'pass'"],
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    state = engine.run_task(task)

    assert state.final_status == "completed"
    assert state.tool_results["builder_role"] == "mechanical_worker"
    assert state.tool_results["builder_backend"] == "role_provider"
    assert state.tool_results["builder_provider"] == "openai"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_provider_structured_patch_flows_through_patch_safety(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "src/app.py", "old\n")
    provider = FakeModelProvider(
        [
            BuilderOutput(
                patch=(
                    "diff --git a/src/app.py b/src/app.py\n"
                    "--- a/src/app.py\n"
                    "+++ b/src/app.py\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ),
                touched_files=["src/app.py"],
                summary="apply bounded patch",
                confidence=0.9,
            )
        ]
    )
    engine = build_provider_engine(tmp_path, provider)
    task = TaskSpec(
        id="T-2",
        title="Fix local bug",
        allowed_files=["src/app.py"],
        validation_commands=["python -c 'pass'"],
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    state = engine.run_task(task)

    assert state.final_status == "completed"
    patch = state.tool_results.get("patch", {})
    assert patch.get("touched_files") == ["src/app.py"]
    assert (tmp_path / "src/app.py").read_text(encoding="utf-8") == "new\n"


def test_failed_validation_still_triggers_rollback_with_provider_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider(
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
                summary="will be rolled back",
                confidence=0.7,
            )
        ]
    )
    engine = build_provider_engine(tmp_path, provider)
    task = TaskSpec(
        id="T-3",
        title="Fix bug",
        max_attempts=1,
        escalation_allowed=False,
        allowed_files=["app.py"],
        validation_commands=["python -c 'pass'"],
    )
    monkeypatch.setattr(
        engine,
        "_validate",
        lambda task: ([ValidationResult(name="tests", passed=False, message="still failing")], []),
    )
    monkeypatch.setattr(engine.git, "diff", lambda: "")

    state = engine.run_task(task)

    assert state.final_status == "failed"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_budget_ledger_records_provider_role_and_service_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider(
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
                summary="budget metadata test",
                confidence=0.6,
            )
        ]
    )
    engine = build_provider_engine(tmp_path, provider)
    task = TaskSpec(
        id="T-4",
        title="Write tests for parser",
        complexity="simple",
        allowed_files=["app.py"],
        validation_commands=["python -c 'pass'"],
    )
    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    state = engine.run_task(task)

    assert state.final_status == "completed"
    with sqlite3.connect(engine.budget.settings.ledger_path) as conn:
        row = conn.execute(
            (
                "SELECT model_role, provider, model, inference_tier FROM budget_events "
                "WHERE task_id = ? ORDER BY id DESC LIMIT 1"
            ),
            (task.id,),
        ).fetchone()
    assert row is not None
    assert row[0] in {"mechanical_worker", "simple_builder", "general_builder"}
    assert row[1] == "openai"
    assert row[2] in {"gpt-5-nano", "gpt-5-mini"}
    assert row[3] in {"flex", "default"}


def test_role_provider_backend_is_active_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider(
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
                summary="default backend check",
                confidence=0.6,
            )
        ]
    )
    engine = build_provider_engine(tmp_path, provider)
    task = TaskSpec(id="T-5", title="Fix bug", allowed_files=["app.py"])

    monkeypatch.setattr(engine, "_validate", lambda task: ([], engine._changed_files()))
    monkeypatch.setattr(engine, "_commit", lambda task, state, changed_files: None)

    state = engine.run_task(task)

    assert state.final_status == "completed"
    assert state.tool_results["builder_backend"] == "role_provider"
    assert state.tool_results["builder_provider"] == "openai"

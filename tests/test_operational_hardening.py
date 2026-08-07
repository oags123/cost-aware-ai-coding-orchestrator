"""Regression tests for the operational-readiness hardening pass.

Each test below pins down a specific invariant that was previously violated:
provider misconfiguration or a no-op builder response could be reported as a
successful "completed" task, git changed-file detection missed whole classes of
change, rollback could destroy a user's pre-existing uncommitted work, budget
actuals were never reconciled, and various patch/commit safety boundaries were
not enforced. These use real temporary git repositories wherever git behavior
matters, per the project's own test conventions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_orchestrator.config import (
    AppConfig,
    BuilderServiceTierSettings,
    FlexTierSettings,
    InferenceSettings,
    ValidationSettings,
)
from coding_orchestrator.models.fake_provider import FakeModelProvider
from coding_orchestrator.models.provider import (
    BuilderOutput,
    ProviderRequest,
    ProviderTransientError,
    StructuredOutputError,
)
from coding_orchestrator.orchestrator.budget import BudgetEstimate, BudgetLedger
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec, ValidationResult
from coding_orchestrator.tools.git import GitManager, HeadChangedError
from coding_orchestrator.tools.lock import ConcurrentExecutionError, RepoLock
from coding_orchestrator.tools.patch import (
    PatchContractError,
    SafePatchApplier,
    parse_builder_output,
)


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
                summary="test patch",
                confidence=0.8,
            )
        ]
    )


def base_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
    )


# --- Status distinctness: provider disabled / no-op builder must never == "completed" ---


def test_provider_disabled_reports_dry_run_not_completed(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(base_config(tmp_path))  # runtime_enabled defaults to False
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "dry_run"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_no_op_builder_response_reports_no_change_not_completed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider([""])  # parses to no patch at all
    engine = WorkflowEngine(base_config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "no_change"


def test_disabled_workflow_requires_human_approval(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    # "refactor" classifies to small_refactor/large_refactor, both Workflow.enabled=False.
    task = TaskSpec(id="T-1", title="Refactor the module", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "blocked"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_explain_code_workflow_accepts_prose_response_without_patch_parsing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Regression test: a real model returning free-text prose (not a diff/JSON patch)
    # for a non-modifying workflow must not be treated as a parse failure.
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider(["## Explanation\n\nThis package does X, Y, Z."])
    engine = WorkflowEngine(base_config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    task = TaskSpec(id="T-1", title="Explain the code")

    state = engine.run_task(task)

    assert state.final_status == "completed"
    assert "explanation" in state.tool_results["builder"]["text"].lower()
    assert "patch" not in state.tool_results


def test_explain_code_workflow_may_complete_without_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    provider = FakeModelProvider([""])
    engine = WorkflowEngine(base_config(tmp_path), provider_overrides={"openai": provider})
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    task = TaskSpec(id="T-1", title="Explain the code")  # -> explain_code, non-modifying

    state = engine.run_task(task)

    assert state.final_status == "completed"


# --- Budget ledger: actual usage reconciliation must be idempotent, never double-counted ---


def test_ledger_actual_usage_reconciliation_is_idempotent(tmp_path: Path) -> None:
    ledger = BudgetLedger(tmp_path / "ledger.sqlite")
    estimate = BudgetEstimate(
        project_id="p",
        task_id="T-1",
        attempt_id=1,
        model_role="simple_builder",
        provider="openai",
        model="m",
        estimated_input_tokens=1000,
        estimated_output_tokens=1000,
        estimated_input_cost_usd=0.01,
        estimated_output_cost_usd=0.01,
        estimated_total_cost_usd=0.02,
    )
    ledger.record(estimate, status="estimated")

    ledger.record_actual_usage(
        project_id="p",
        task_id="T-1",
        attempt_id=1,
        model_role="simple_builder",
        actual_input_tokens=800,
        actual_output_tokens=900,
        actual_cost_usd=0.015,
    )
    spend_after_first = ledger.spend_for_task("p", "T-1")

    # A repeat reconciliation call for the same attempt must not create a second
    # row or overwrite the first -- it must be a safe no-op.
    ledger.record_actual_usage(
        project_id="p",
        task_id="T-1",
        attempt_id=1,
        model_role="simple_builder",
        actual_input_tokens=99999,
        actual_output_tokens=99999,
        actual_cost_usd=999.0,
    )
    spend_after_second = ledger.spend_for_task("p", "T-1")

    assert spend_after_first == pytest.approx(0.015)
    assert spend_after_second == spend_after_first


def test_engine_reconciles_actual_usage_into_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sqlite3

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
            "SELECT actual_cost_usd, actual_input_tokens, actual_output_tokens "
            "FROM budget_events WHERE task_id = ? ORDER BY id DESC LIMIT 1",
            (task.id,),
        ).fetchone()
    assert row is not None
    assert row[0] is not None  # actual_cost_usd reconciled, not left NULL
    assert row[1] is not None and row[1] > 0
    assert row[2] is not None and row[2] > 0


# --- Git changed-file detection: tracked, staged, untracked, deleted, renamed, spaces ---


def test_changed_files_detects_every_change_type(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "keep.py", "keep\n")
    commit_file(tmp_path, "to_delete.py", "bye\n")
    commit_file(tmp_path, "to_rename.py", "rename me\n")
    manager = GitManager(tmp_path)

    (tmp_path / "keep.py").write_text("keep changed\n", encoding="utf-8")  # tracked modification
    (tmp_path / "new_file.py").write_text("new\n", encoding="utf-8")  # untracked new file
    (tmp_path / "to_delete.py").unlink()  # deletion
    subprocess.run(["git", "mv", "to_rename.py", "renamed.py"], cwd=tmp_path, check=True)  # rename
    (tmp_path / "staged.py").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "staged.py"], cwd=tmp_path, check=True)  # staged
    (tmp_path / "has space.py").write_text("space\n", encoding="utf-8")  # unusual filename

    changed = set(manager.changed_files())

    assert "keep.py" in changed
    assert "new_file.py" in changed
    assert "to_delete.py" in changed
    assert "renamed.py" in changed
    assert "staged.py" in changed
    assert "has space.py" in changed


def test_changed_files_lists_files_inside_new_untracked_directory(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    manager = GitManager(tmp_path)

    (tmp_path / "newdir").mkdir()
    (tmp_path / "newdir" / "one.py").write_text("one\n", encoding="utf-8")
    (tmp_path / "newdir" / "two.py").write_text("two\n", encoding="utf-8")

    changed = set(manager.changed_files())

    assert "newdir/one.py" in changed
    assert "newdir/two.py" in changed
    assert "newdir/" not in changed  # must not collapse to the directory itself


# --- Rollback must preserve exact pre-task state, including pre-existing user work ---


def test_rollback_preserves_preexisting_dirty_tracked_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    commit_file(tmp_path, "user_work.py", "original\n")
    (tmp_path / "user_work.py").write_text("user's uncommitted edit\n", encoding="utf-8")

    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(
        engine,
        "_validate",
        lambda task: [ValidationResult(name="tests", passed=False, message="fail")],
    )
    task = TaskSpec(
        id="T-1",
        title="Fix bug",
        max_attempts=1,
        escalation_allowed=False,
        allowed_files=["app.py"],
    )

    state = engine.run_task(task)

    assert state.final_status == "failed"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"
    assert (tmp_path / "user_work.py").read_text(encoding="utf-8") == "user's uncommitted edit\n"


def test_success_preserves_preexisting_untracked_scratch_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    (tmp_path / "scratch.txt").write_text("my scratch notes\n", encoding="utf-8")

    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "completed"
    assert (tmp_path / "scratch.txt").read_text(encoding="utf-8") == "my scratch notes\n"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


# --- Concurrency protection ---


def test_repo_lock_blocks_concurrent_acquisition(tmp_path: Path) -> None:
    with RepoLock(tmp_path), pytest.raises(ConcurrentExecutionError), RepoLock(tmp_path):
        pass  # pragma: no cover


def test_engine_run_task_blocked_while_locked(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(base_config(tmp_path))

    with RepoLock(tmp_path):
        state = engine.run_task(TaskSpec(id="T-1", title="Fix bug"))

    assert state.final_status == "blocked"


# --- HEAD-changed detection ---


def test_verify_head_detects_head_moved_during_run(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    manager = GitManager(tmp_path)
    checkpoint = manager.checkpoint("T-1")

    commit_file(tmp_path, "other.py", "concurrent commit\n")

    with pytest.raises(HeadChangedError):
        manager.verify_head(checkpoint)


# --- Structured output must be rejected, not silently downgraded ---


def test_invalid_structured_output_raises_structured_output_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coding_orchestrator.config import AppConfig as _AppConfig
    from coding_orchestrator.config import OpenAIProviderSettings, resolve_model_role
    from coding_orchestrator.models.openai_provider import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class FakeUsage:
        input_tokens = 10
        output_tokens = 5
        input_tokens_details = None
        output_tokens_details = None

    class FakeResponse:
        output_text = '{"touched_files": ["app.py"]}'  # missing required "patch" field
        usage = FakeUsage()
        service_tier = "default"

    class FakeResponses:
        def create(self, **kwargs: object) -> FakeResponse:
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("openai.OpenAI", FakeClient)

    provider = OpenAIProvider(OpenAIProviderSettings(runtime_enabled=True))
    config = _AppConfig()
    role = resolve_model_role(config, "simple_builder")
    request = ProviderRequest(
        role=role, prompt="do it", response_schema_name="builder_patch_contract"
    )

    with pytest.raises(StructuredOutputError):
        provider.generate(request)


# --- Patch safety: traversal, absolute paths, symlinks ---


def test_patch_rejects_path_traversal(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "diff --git a/../outside.py b/../outside.py\n"
        "--- a/../outside.py\n"
        "+++ b/../outside.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="escapes workspace"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["../outside.py"]),
        )


def test_patch_rejects_absolute_path(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "--- /etc/passwd\n+++ /etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="must be relative"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["/etc/passwd"]),
        )


def test_patch_rejects_symlink_creation(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "diff --git a/link b/link\n"
        "new file mode 120000\n"
        "index 0000000..abc123\n"
        "--- /dev/null\n"
        "+++ b/link\n"
        "@@ -0,0 +1 @@\n"
        "+/etc/passwd\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="symlink"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["link"]),
        )


def test_patch_rejects_declared_files_not_matching_diff(tmp_path: Path) -> None:
    # A duplicate (or otherwise inconsistent) declared touched_files list can never
    # match the deduplicated file list extracted from the actual diff content.
    parsed = parse_builder_output(
        '{"patch":"diff --git a/app.py b/app.py\\n--- a/app.py\\n+++ b/app.py\\n'
        '@@ -1 +1 @@\\n-old\\n+new\\n",'
        '"touched_files":["app.py","app.py"],"summary":"x","confidence":0.5}'
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="do not match"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["app.py"]),
        )


# --- Commit must never stage files outside the task's allowed_files boundary ---


def test_commit_task_refuses_unrelated_files_outside_boundary(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    commit_file(tmp_path, "other.py", "other-old\n")
    manager = GitManager(tmp_path)
    (tmp_path / "app.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("other-new\n", encoding="utf-8")  # unrelated dirty file

    changed = manager.changed_files()
    result = manager.commit_task("T-1", "Fix bug", changed, ["app.py"])

    assert result.returncode == 0
    log = subprocess.run(
        ["git", "show", "--stat", "HEAD"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert "app.py" in log
    assert "other.py" not in log
    status = subprocess.run(
        ["git", "status", "--short"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert "other.py" in status  # unrelated change left untouched, not committed


def test_commit_task_refuses_when_no_changed_file_is_in_allowed_set(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "other.py", "old\n")
    manager = GitManager(tmp_path)
    (tmp_path / "other.py").write_text("changed\n", encoding="utf-8")

    result = manager.commit_task("T-1", "Fix bug", manager.changed_files(), ["app.py"])

    assert result.returncode != 0
    assert "outside task.allowed_files boundary" in result.stderr


# --- Service-tier fallback must fire on typed transient errors regardless of message text ---


def test_flex_fallback_triggers_on_typed_transient_error_without_keyword_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    config = base_config(tmp_path).model_copy(
        update={
            "inference": InferenceSettings(
                builder_service_tier=BuilderServiceTierSettings(
                    flex=FlexTierSettings(max_consecutive_timeouts=1, timeout_rate_threshold=1.0)
                )
            )
        }
    )
    engine = WorkflowEngine(config)
    monkeypatch.setattr(engine, "_validate", lambda task: [])

    call_count = {"n": 0}

    def flaky_generate(request: ProviderRequest) -> object:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Deliberately no "429"/"timeout"/"rate limit" substring -- only the
            # exception type should be enough to trigger the fallback now.
            raise ProviderTransientError("upstream had a bad day")
        return real_patch_provider().generate(request)

    monkeypatch.setattr(engine.openai_provider, "generate", flaky_generate)

    state = engine.run_task(TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"]))

    assert state.final_status == "completed"
    assert state.tool_results["builder"]["tier"] == "standard"
    assert call_count["n"] == 2


# --- End-to-end fake-provider smoke test ---


def test_end_to_end_fake_provider_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    engine = WorkflowEngine(
        base_config(tmp_path), provider_overrides={"openai": real_patch_provider()}
    )
    monkeypatch.setattr(engine, "_validate", lambda task: [])
    task = TaskSpec(id="T-1", title="Fix bug", allowed_files=["app.py"])

    state = engine.run_task(task)

    assert state.final_status == "completed"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=tmp_path, check=True, capture_output=True, text=True
    ).stdout
    assert "T-1" in log

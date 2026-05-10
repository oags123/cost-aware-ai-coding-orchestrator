from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from coding_orchestrator.config import OpenCodeSettings, ValidationSettings
from coding_orchestrator.schemas import CommandResult, TaskSpec
from coding_orchestrator.tools.git import DirtyWorktreeError, GitManager
from coding_orchestrator.tools.opencode_runner import OpenCodeExecutionError, OpenCodeRunner
from coding_orchestrator.tools.patch import (
    PatchApplyError,
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


def test_opencode_dry_run_returns_placeholder(tmp_path: Path) -> None:
    runner = OpenCodeRunner(tmp_path, settings=OpenCodeSettings(enabled=False, dry_run=True))

    result = runner.run_bounded_step(TaskSpec(id="T-1", title="x"), "context")

    assert result.dry_run
    assert "Placeholder" in result.text


def test_opencode_missing_fails_cleanly(tmp_path: Path) -> None:
    runner = OpenCodeRunner(
        tmp_path,
        settings=OpenCodeSettings(
            enabled=True,
            dry_run=False,
            executable="definitely-missing-opencode",
        ),
    )

    with pytest.raises(OpenCodeExecutionError, match="OpenCode is not installed"):
        runner.run_bounded_step(TaskSpec(id="T-1", title="x"), "context")


def test_opencode_real_mode_uses_bounded_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    def fake_which(executable: str) -> str:
        return "/usr/bin/opencode"

    def fake_run_limited_command(
        command: list[str],
        cwd: Path,
        timeout_seconds: float,
        allowlist: list[str],
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["timeout"] = timeout_seconds
        captured["allowlist"] = allowlist
        return CommandResult(
            command=command,
            returncode=0,
            stdout=(
                "diff --git a/app.py b/app.py\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            ),
            stderr="",
        )

    monkeypatch.setattr("coding_orchestrator.tools.opencode_runner.shutil.which", fake_which)
    monkeypatch.setattr(
        "coding_orchestrator.tools.opencode_runner.run_limited_command",
        fake_run_limited_command,
    )
    runner = OpenCodeRunner(
        tmp_path,
        settings=OpenCodeSettings(enabled=True, dry_run=False, default_model="openai/gpt-test"),
    )

    result = runner.run_bounded_step(TaskSpec(id="T-1", title="x"), "context")

    assert not result.dry_run
    assert captured["cwd"] == tmp_path
    assert captured["allowlist"] == ["/usr/bin/opencode"]
    assert captured["command"][0:4] == ["/usr/bin/opencode", "run", "--model", "openai/gpt-test"]


def test_parse_rejects_free_form_output() -> None:
    with pytest.raises(PatchContractError):
        parse_builder_output("Please edit app.py manually")


def test_parse_json_patch_contract() -> None:
    parsed = parse_builder_output(
        '{"patch":"diff --git a/app.py b/app.py\\n--- a/app.py\\n+++ b/app.py\\n'
        '@@ -1 +1 @@\\n-old\\n+new\\n",'
        '"touched_files":["app.py"],"summary":"update","confidence":0.8}'
    )

    assert parsed is not None
    assert parsed.touched_files == ["app.py"]


def test_safe_patch_applies_allowed_patch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    patch = parse_builder_output(
        "diff --git a/app.py b/app.py\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert patch is not None

    SafePatchApplier(tmp_path, ValidationSettings()).apply(
        patch,
        TaskSpec(id="T-1", title="x", allowed_files=["app.py"]),
    )

    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "new\n"


def test_safe_patch_rejects_forbidden_path(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="forbidden path"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=[".env"]),
        )


def test_safe_patch_rejects_too_many_files(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-a\n+b\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="too many files"):
        SafePatchApplier(tmp_path, ValidationSettings(max_files_changed=1)).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["a.py", "b.py"]),
        )


def test_safe_patch_rejects_delete_without_approval(tmp_path: Path) -> None:
    parsed = parse_builder_output(
        "diff --git a/app.py b/app.py\n"
        "deleted file mode 100644\n"
        "--- a/app.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-old\n"
    )
    assert parsed is not None

    with pytest.raises(PatchContractError, match="deletes"):
        SafePatchApplier(tmp_path, ValidationSettings()).validate_patch(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["app.py"]),
        )


def test_safe_patch_rejects_invalid_patch(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    parsed = parse_builder_output(
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-missing\n+new\n"
    )
    assert parsed is not None

    with pytest.raises(PatchApplyError):
        SafePatchApplier(tmp_path, ValidationSettings()).apply(
            parsed,
            TaskSpec(id="T-1", title="x", allowed_files=["app.py"]),
        )


def test_rollback_removes_new_untracked_but_preserves_logs(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    manager = GitManager(tmp_path)
    checkpoint = manager.checkpoint("T-1")

    (tmp_path / "new.txt").write_text("remove", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "state.json").write_text("keep", encoding="utf-8")
    (tmp_path / "app.py").write_text("changed\n", encoding="utf-8")

    manager.rollback_to_checkpoint(checkpoint, preserve_dirs=["logs"], preserve_files=[])

    assert not (tmp_path / "new.txt").exists()
    assert (tmp_path / "logs" / "state.json").exists()
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"


def test_checkpoint_can_reject_dirty_worktree(tmp_path: Path) -> None:
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    (tmp_path / "app.py").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(DirtyWorktreeError):
        GitManager(tmp_path).checkpoint("T-1", require_clean=True)

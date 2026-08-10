from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coding_orchestrator.config import ValidationSettings
from coding_orchestrator.schemas import TaskSpec
from coding_orchestrator.tools.git import DirtyWorktreeError, GitManager
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


def test_checkpoint_excludes_dirs_starting_with_underscore(tmp_path: Path) -> None:
    # Regression test: git's short pathspec-exclude shorthand (":!path") treats
    # characters immediately after "!" as potential additional magic-signature
    # letters, and a real git binary (2.43.0) rejects ":!__pycache__" outright with
    # "fatal: Unimplemented pathspec magic '_' in ':!__pycache__'" -- this broke
    # every checkpoint() call once "__pycache__" (a name starting with "_", exactly
    # what SyntaxValidator's compileall step creates) was added to the default
    # preserve_untracked_dirs list. The long-form ":(exclude)path" magic has no such
    # ambiguity for any path and must be used instead.
    init_repo(tmp_path)
    commit_file(tmp_path, "app.py", "old\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"fake bytecode")
    (tmp_path / "new_dirty.txt").write_text("dirty", encoding="utf-8")

    checkpoint = GitManager(tmp_path).checkpoint("T-1", preserve_dirs=["__pycache__"])

    assert checkpoint.stashed
    # The excluded directory was left untouched by the stash...
    assert (tmp_path / "__pycache__" / "app.cpython-312.pyc").exists()
    # ...while the genuinely dirty file was actually stashed away.
    assert not (tmp_path / "new_dirty.txt").exists()

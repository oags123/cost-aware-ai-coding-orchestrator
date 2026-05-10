from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from coding_orchestrator.config import ValidationSettings
from coding_orchestrator.orchestrator.policies import is_forbidden_path, is_within_workspace
from coding_orchestrator.schemas import ParsedPatch, TaskSpec
from coding_orchestrator.tools.shell import run_limited_command


class PatchContractError(ValueError):
    pass


class PatchApplyError(RuntimeError):
    pass


DIFF_FILE_RE = re.compile(r"^(?:diff --git a/(.*?) b/(.*?)|--- (?:a/)?(.+)|\+\+\+ (?:b/)?(.+))$")


def parse_builder_output(text: str) -> ParsedPatch | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            loaded = json.loads(stripped)
            parsed = ParsedPatch.model_validate(loaded)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PatchContractError(f"invalid json patch output: {exc}") from exc
        parsed.patch = _ensure_final_newline(parsed.patch)
        _require_patch_shape(parsed.patch)
        return parsed
    if stripped.startswith("diff --git ") or stripped.startswith("--- "):
        patch = _ensure_final_newline(_strip_fenced_patch(stripped))
        _require_patch_shape(patch)
        return ParsedPatch(
            patch=patch,
            touched_files=extract_touched_files(patch),
            output_mode="unified_diff",
        )
    if stripped.startswith("```"):
        patch = _ensure_final_newline(_strip_fenced_patch(stripped))
        _require_patch_shape(patch)
        return ParsedPatch(
            patch=patch,
            touched_files=extract_touched_files(patch),
            output_mode="unified_diff",
        )
    raise PatchContractError("OpenCode output must be unified diff or structured JSON patch")


def extract_touched_files(patch: str) -> list[str]:
    files: list[str] = []
    for line in patch.splitlines():
        match = DIFF_FILE_RE.match(line)
        if not match:
            continue
        for value in match.groups():
            if value and value != "/dev/null":
                normalized = value.strip()
                if normalized not in files:
                    files.append(normalized)
    return files


def patch_deletes_files(patch: str) -> bool:
    markers = ("deleted file mode", "+++ /dev/null")
    return any(marker in patch for marker in markers)


class SafePatchApplier:
    def __init__(
        self,
        repo_path: Path,
        settings: ValidationSettings,
        timeout_seconds: int = 60,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    def validate_patch(self, parsed: ParsedPatch, task: TaskSpec) -> None:
        patch_files = extract_touched_files(parsed.patch)
        if parsed.touched_files and sorted(parsed.touched_files) != sorted(patch_files):
            raise PatchContractError("declared touched_files do not match unified diff paths")
        touched = parsed.touched_files or patch_files
        if not touched:
            raise PatchContractError("patch does not declare touched files")
        if len(touched) > self.settings.max_files_changed:
            raise PatchContractError(f"too many files touched: {len(touched)}")
        if patch_deletes_files(parsed.patch) and not task.allow_deletes:
            raise PatchContractError("file deletes are not allowed for this task")
        allowed = set(task.allowed_files)
        for raw_path in touched:
            if is_forbidden_path(raw_path, self.settings.forbidden_paths):
                raise PatchContractError(f"forbidden path in patch: {raw_path}")
            candidate = (self.repo_path / raw_path).resolve()
            if not is_within_workspace(candidate, self.repo_path):
                raise PatchContractError(f"patch path escapes workspace: {raw_path}")
            if allowed and raw_path not in allowed:
                raise PatchContractError(f"patch touches file outside task boundary: {raw_path}")

    def apply(self, parsed: ParsedPatch, task: TaskSpec) -> None:
        self.validate_patch(parsed, task)
        check = run_limited_command(
            ["git", "apply", "--check", "-"],
            self.repo_path,
            self.timeout_seconds,
            ["git"],
            stdin=parsed.patch,
        )
        if check.returncode != 0:
            raise PatchApplyError(check.stderr or check.stdout or "git apply --check failed")
        applied = run_limited_command(
            ["git", "apply", "-"],
            self.repo_path,
            self.timeout_seconds,
            ["git"],
            stdin=parsed.patch,
        )
        if applied.returncode != 0:
            raise PatchApplyError(applied.stderr or applied.stdout or "git apply failed")


def _strip_fenced_patch(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip() + "\n"
    return text


def _require_patch_shape(patch: str) -> None:
    if "diff --git " not in patch and not ("--- " in patch and "+++ " in patch):
        raise PatchContractError("output does not contain a unified diff")


def _ensure_final_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"

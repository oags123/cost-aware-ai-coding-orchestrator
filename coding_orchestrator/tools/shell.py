from __future__ import annotations

import subprocess
from pathlib import Path
from time import monotonic

from coding_orchestrator.orchestrator.policies import command_is_allowlisted
from coding_orchestrator.schemas import CommandResult


class CommandSafetyError(ValueError):
    pass


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_limited_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: float,
    allowlist: list[str],
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if not command:
        raise CommandSafetyError("command cannot be empty")
    if not command_is_allowlisted(command[0], allowlist):
        raise CommandSafetyError(f"command not allowlisted: {command[0]}")
    started = monotonic()
    try:
        proc = subprocess.run(
            command,
            input=stdin,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            runtime_seconds=monotonic() - started,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=command,
            returncode=124,
            stdout=_to_text(exc.stdout),
            stderr=_to_text(exc.stderr) or f"Timed out after {timeout_seconds} seconds",
            timed_out=True,
            runtime_seconds=monotonic() - started,
        )

from __future__ import annotations

from pathlib import Path

FORBIDDEN_PATH_MARKERS = ("/etc/", "~/.ssh", ".env", "secrets", "credentials", "tokens")


def is_forbidden_path(path: str, forbidden: list[str] | None = None) -> bool:
    normalized = path.replace("\\", "/").lower()
    markers = tuple(item.lower() for item in (forbidden or list(FORBIDDEN_PATH_MARKERS)))
    return any(marker in normalized or normalized.startswith(marker) for marker in markers)


def is_within_workspace(path: Path, workspace: Path) -> bool:
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError:
        return False
    return True


def command_is_allowlisted(command: str, allowlist: list[str]) -> bool:
    executable = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return executable in allowlist


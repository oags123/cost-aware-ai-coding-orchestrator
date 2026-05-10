from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk_level: str
    cacheable: bool
    requires_approval: bool
    input_schema: dict[str, Any]


def default_tool_registry() -> dict[str, ToolDefinition]:
    tools = [
        ToolDefinition("read_file", "Read a workspace file", "low", True, False, {"path": "str"}),
        ToolDefinition(
            "write_file",
            "Write an allowed workspace file",
            "medium",
            False,
            False,
            {"path": "str", "content": "str"},
        ),
        ToolDefinition(
            "apply_patch",
            "Apply a bounded patch",
            "medium",
            False,
            False,
            {"patch": "str"},
        ),
        ToolDefinition("list_files", "List workspace files", "low", True, False, {}),
        ToolDefinition(
            "search_repo",
            "Search repository text",
            "low",
            True,
            False,
            {"query": "str"},
        ),
        ToolDefinition("run_tests", "Run pytest", "medium", False, False, {"target": "str?"}),
        ToolDefinition("run_linter", "Run ruff check", "medium", False, False, {}),
        ToolDefinition("run_formatter", "Run ruff format", "medium", False, False, {}),
        ToolDefinition("run_type_checker", "Run mypy", "medium", False, False, {}),
        ToolDefinition("git_diff", "Inspect git diff", "low", False, False, {}),
        ToolDefinition("git_status", "Inspect git status", "low", False, False, {}),
        ToolDefinition("git_branch", "Inspect git branch", "low", False, False, {}),
        ToolDefinition(
            "shell_command_limited",
            "Run allowlisted command with timeout",
            "high",
            False,
            True,
            {"command": "list[str]"},
        ),
    ]
    return {tool.name: tool for tool in tools}

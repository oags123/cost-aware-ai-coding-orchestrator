from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from coding_orchestrator.config import HandoffSettings
from coding_orchestrator.schemas import OrchestratorState, TaskSpec

HANDOFF_INSTRUCTIONS = """\
This task could not make further economical progress using cheap, Flex-only OpenAI
models (gpt-5-nano / gpt-5-mini). Please review the situation below using the
ChatGPT subscription app's stronger reasoning, and produce one of:

1. One or more corrected/new task files in this repository's task file format
   (YAML frontmatter + Markdown body, or pure YAML) -- see "Task file schema"
   below. These can be dropped into the tasks directory and run again with
   `coding-orchestrator run` / `run-all`.
2. Directly corrected source files, to be placed into the repository by hand.
3. A short written diagnosis, if neither of the above is appropriate yet.

Please place the result back wherever this handoff file was retrieved from (for
example, the configured Google Drive folder) so it can be brought back to the VPS.
"""

TASK_FILE_SCHEMA = """\
id: <string, required>
title: <string, required>
description: <string, optional -- may also be the Markdown body after the closing '---'>
complexity: trivial|simple|medium|hard|critical  (default: simple)
risk: low|medium|high  (default: low)
depends_on: [<task id>, ...]  (default: [])
allowed_files: [<repo-relative path>, ...]  (default: [] -- the ONLY files a patch may touch)
max_attempts: <int >= 1>  (default: 2)
max_runtime_seconds: <int >= 1>  (default: 480)
max_cost_usd: <float > 0>  (default: 0.06)
escalation_allowed: <bool>  (default: true)
allow_deletes: <bool>  (default: false)
validation_commands: [<shell command>, ...]  (default: [] -- falls back to configured defaults)
"""

REASON_DESCRIPTIONS: dict[str, str] = {
    "non_converging": (
        "Repeated cheap attempts stopped making meaningful progress: validation "
        "failures were repeating or getting worse rather than shrinking "
        "(see the convergence summary below)."
    ),
    "retries_exhausted": (
        "The task's configured attempt limit (max_attempts) was reached without "
        "a passing validation result."
    ),
    "budget_exceeded": (
        "A task, role, or project budget ceiling was reached (or a single call's "
        "estimate already exceeded the allowed cost) before the task could "
        "complete."
    ),
    "limits_exceeded": (
        "A context, token, or output size limit was exceeded -- the task's scope "
        "or the amount of surrounding context it needs may be too large for the "
        "configured nano/mini roles."
    ),
    "flex_unavailable": (
        "OpenAI Flex capacity was requested and, after bounded retries, never "
        "succeeded. This is a capacity/availability issue, not a capability "
        "issue -- retrying later may work without any escalation at all."
    ),
    "timeout": (
        "The task exceeded its configured runtime budget before completing."
    ),
    "requires_human_approval": (
        "The task was blocked before any model call was attempted -- either its "
        "complexity is 'critical', its classified workflow is disabled, or a "
        "coarse pre-check already determined its estimated scope would exceed "
        "the configured budget. This task's scope may be too large for a "
        "bounded nano/mini role at all; consider ChatGPT for it from the start "
        "rather than narrowing it and retrying."
    ),
}


def _tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "... [truncated, showing final " + str(limit) + " characters] ...\n" + text[-limit:]


def _safe_filename_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "task"


@dataclass
class HandoffBuilder:
    """Builds a single, self-contained, human/ChatGPT-readable Markdown artifact
    whenever automatic progress on a task stops without completing. This is pure
    local file I/O: it never calls a model and never touches the network. It is
    the intended escalation surface for problems nano/mini Flex calls can't
    economically resolve -- a human reads or uploads the file and asks the
    ChatGPT subscription app for corrections, rather than the orchestrator
    automatically spending more on a pricier OpenAI API model.
    """

    settings: HandoffSettings
    output_dir: Path

    def __post_init__(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        *,
        task: TaskSpec,
        state: OrchestratorState,
        reason: str,
        diff: str = "",
        validation_errors: list[str] | None = None,
        budget_snapshot: dict[str, Any] | None = None,
    ) -> Path:
        content = self._render(
            task=task,
            state=state,
            reason=reason,
            diff=diff,
            validation_errors=validation_errors or [],
            budget_snapshot=budget_snapshot or {},
        )
        filename = (
            f"{_safe_filename_component(task.id)}-"
            f"{_safe_filename_component(state.request_id[:8])}-handoff.md"
        )
        path = self.output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def _render(
        self,
        *,
        task: TaskSpec,
        state: OrchestratorState,
        reason: str,
        diff: str,
        validation_errors: list[str],
        budget_snapshot: dict[str, Any],
    ) -> str:
        created_at = datetime.now(UTC).isoformat()
        frontmatter = yaml.safe_dump(
            {
                "task_id": task.id,
                "request_id": state.request_id,
                "reason": reason,
                "final_status": state.final_status,
                "retry_count": state.retry_count,
                "created_at": created_at,
            },
            sort_keys=False,
        ).strip()

        task_yaml = yaml.safe_dump(
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "complexity": task.complexity,
                "risk": task.risk,
                "depends_on": task.depends_on,
                "allowed_files": task.allowed_files,
                "max_attempts": task.max_attempts,
                "max_cost_usd": task.max_cost_usd,
                "validation_commands": task.validation_commands,
            },
            sort_keys=False,
        ).strip()

        reason_text = REASON_DESCRIPTIONS.get(reason, reason)

        attempts_section = self._render_attempts(state)
        validation_section = self._render_validation(validation_errors)
        budget_section = self._render_budget(state, budget_snapshot)
        diff_section = _tail(diff.strip(), self.settings.max_diff_chars) or "(no diff captured)"

        return f"""\
---
{frontmatter}
---

# Handoff: {task.id} -- {task.title}

## Why automation stopped

**Reason code:** `{reason}`

{reason_text}

## Instructions

{HANDOFF_INSTRUCTIONS}

## Task specification

```yaml
{task_yaml}
```

## Attempts and convergence

{attempts_section}

## Latest validation failures

{validation_section}

## Budget so far

{budget_section}

## Current repository diff

```diff
{diff_section}
```

## Task file schema (for producing corrections)

```
{TASK_FILE_SCHEMA}
```
"""

    def _render_attempts(self, state: OrchestratorState) -> str:
        if not state.attempt_metrics:
            return "No attempts completed (blocked before or during the first attempt)."
        lines = ["| # | status | validator errors | failing tests | repeated? | new failures? |",
                 "| --- | --- | --- | --- | --- | --- |"]
        for metrics in state.attempt_metrics:
            lines.append(
                f"| {metrics.attempt_number} | {metrics.validation_status} | "
                f"{metrics.validator_error_count} | {metrics.failing_test_count} | "
                f"{metrics.repeated_failures} | {metrics.new_failures} |"
            )
        if state.convergence_decision is not None:
            decision = state.convergence_decision
            lines.append("")
            lines.append(
                f"Convergence status: **{decision.status}** "
                f"(action: `{decision.action}`, reason: {decision.reason or 'n/a'}, "
                f"stagnant attempts: {decision.stagnant_attempts}, "
                f"divergent attempts: {decision.divergent_attempts})"
            )
        return "\n".join(lines)

    def _render_validation(self, validation_errors: list[str]) -> str:
        if not validation_errors:
            return "(none recorded)"
        joined = "\n".join(f"- {error}" for error in validation_errors)
        return _tail(joined, self.settings.max_validation_chars)

    def _render_budget(self, state: OrchestratorState, budget_snapshot: dict[str, Any]) -> str:
        lines = [
            f"- Estimated cost so far (this task): ${state.estimated_cost_usd:.4f}",
        ]
        for key, value in budget_snapshot.items():
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)


def list_handoffs(output_dir: Path) -> list[dict[str, Any]]:
    """Enumerate pending handoff files (most recently created first) by reading
    each file's YAML frontmatter. Read-only, local, no network access -- intended
    for the `coding-orchestrator handoff` CLI command and for scripting an rclone
    upload step around its output.
    """
    if not output_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("*-handoff.md")):
        text = path.read_text(encoding="utf-8")
        record: dict[str, Any] = {"path": str(path)}
        if text.startswith("---"):
            _, frontmatter, _ = text.split("---", 2)
            loaded = yaml.safe_load(frontmatter) or {}
            if isinstance(loaded, dict):
                record.update(loaded)
        records.append(record)
    records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return records

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from coding_orchestrator.orchestrator.policies import is_within_workspace
from coding_orchestrator.schemas import OrchestratorState, TaskSpec

NON_MODIFYING_WORKFLOWS: frozenset[str] = frozenset(
    {"explain_code", "architecture_review", "security_review"}
)


@dataclass(frozen=True)
class Workflow:
    name: str
    prompt_template: str
    enabled: bool = True

    def build_context(self, task: TaskSpec, state: OrchestratorState) -> str:
        rules = (
            "Rules: respond with plain-text analysis only; do not output a patch, diff, "
            "or code block; no shell commands; no secret access."
            if self.name in NON_MODIFYING_WORKFLOWS
            else (
                "Rules: output patches only for allowed files; no shell commands; "
                "no secret access.\n"
                "Output format: respond with ONLY a standard unified diff (git diff "
                "format), starting with 'diff --git a/<path> b/<path>', e.g.:\n"
                "diff --git a/app.py b/app.py\n"
                "--- a/app.py\n"
                "+++ b/app.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-old line\n"
                "+new line\n"
                "Do NOT use the apply_patch tool format ('*** Begin Patch' / "
                "'*** Update File:' / '*** End Patch'). Do NOT include any "
                "explanation, markdown fences, or text outside the diff.\n"
                "The diff MUST apply cleanly against the exact current file contents "
                "shown below -- match whitespace, quoting, and every existing line "
                "character-for-character in your context/removed lines. Do not guess "
                "or reconstruct file contents from the task description."
            )
        )
        return (
            f"Task: {task.id} - {task.title}\n"
            f"Description:\n{task.description}\n\n"
            f"Workflow: {self.name}\n"
            f"Complexity: {state.complexity}\n"
            f"Risk: {state.risk_level}\n"
            f"Allowed files: {', '.join(task.allowed_files) or '(none)'}\n"
            f"Retry: {state.retry_count}\n"
            f"{rules}"
            f"{self._current_file_contents(task, state)}"
        )

    def _current_file_contents(self, task: TaskSpec, state: OrchestratorState) -> str:
        if self.name in NON_MODIFYING_WORKFLOWS or not task.allowed_files or not state.repo_path:
            return ""
        root = Path(state.repo_path).resolve()
        sections: list[str] = []
        for relative in task.allowed_files:
            candidate = (root / relative).resolve()
            if not is_within_workspace(candidate, root) or not candidate.is_file():
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            sections.append(f"\n\n--- Current content of {relative} ---\n{content}")
        if not sections:
            return ""
        return "\n\nCurrent file contents (patch against this exactly):" + "".join(sections)


WORKFLOWS: dict[str, Workflow] = {
    "explain_code": Workflow("explain_code", "Explain relevant code within allowed context."),
    "fix_bug": Workflow("fix_bug", "Produce a minimal bug-fix patch."),
    "write_tests": Workflow("write_tests", "Produce tests for allowed behavior."),
    "small_refactor": Workflow(
        "small_refactor",
        "Produce a bounded refactor patch.",
        enabled=False,
    ),
    "large_refactor": Workflow("large_refactor", "Escalate large refactors.", enabled=False),
    "architecture_review": Workflow(
        "architecture_review",
        "Prepare architecture review.",
        enabled=False,
    ),
    "dependency_update": Workflow("dependency_update", "Prepare dependency update.", enabled=False),
    "security_review": Workflow("security_review", "Prepare security review.", enabled=False),
}

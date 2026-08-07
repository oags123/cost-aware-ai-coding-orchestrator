from __future__ import annotations

from dataclasses import dataclass

from coding_orchestrator.schemas import OrchestratorState, TaskSpec


@dataclass(frozen=True)
class Workflow:
    name: str
    prompt_template: str
    enabled: bool = True

    def build_context(self, task: TaskSpec, state: OrchestratorState) -> str:
        return (
            f"Task: {task.id} - {task.title}\n"
            f"Description:\n{task.description}\n\n"
            f"Workflow: {self.name}\n"
            f"Complexity: {state.complexity}\n"
            f"Risk: {state.risk_level}\n"
            f"Allowed files: {', '.join(task.allowed_files) or '(none)'}\n"
            f"Retry: {state.retry_count}\n"
            "Rules: output patches only for allowed files; no shell commands; no secret access."
        )


NON_MODIFYING_WORKFLOWS: frozenset[str] = frozenset(
    {"explain_code", "architecture_review", "security_review"}
)


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

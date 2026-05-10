from __future__ import annotations

import json
from pathlib import Path

from coding_orchestrator.schemas import EscalationPackage, OrchestratorState, TaskSpec


class EscalationManager:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def should_escalate(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> bool:
        return bool(
            task.escalation_allowed
            and (
                state.retry_count >= task.max_attempts - 1
                or state.risk_level == "high"
                or state.complexity == "critical"
                or validation_errors
            )
        )

    def create_package(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        diff: str,
        logs: list[str],
        validation_errors: list[str],
        traceback: str | None = None,
        timeout_info: dict[str, object] | None = None,
    ) -> Path:
        package = EscalationPackage(
            task=task,
            state=state,
            diff=diff,
            logs=logs,
            traceback=traceback,
            validation_errors=validation_errors,
            related_files=task.allowed_files,
            retry_count=state.retry_count,
            timeout_info=timeout_info or {},
            suggested_next_action=self._suggest_next_action(state, validation_errors),
        )
        path = self.output_dir / f"{task.id}-escalation.json"
        path.write_text(json.dumps(package.model_dump(mode="json"), indent=2), encoding="utf-8")
        return path

    def _suggest_next_action(
        self,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> str:
        if state.final_status == "timeout":
            return "Review task scope or increase the configured timeout for this task."
        if any("OpenCode" in error or "opencode" in error for error in validation_errors):
            return "Install/configure OpenCode or rerun in dry_run mode."
        if validation_errors:
            return "Review validator output and prepare a bounded manual patch."
        return "Review task state and git diff before retrying."

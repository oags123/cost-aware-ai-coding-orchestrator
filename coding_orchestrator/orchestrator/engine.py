from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from coding_orchestrator.config import AppConfig
from coding_orchestrator.models.router import ModelRouter
from coding_orchestrator.observability.logger import JsonlLogger
from coding_orchestrator.orchestrator.budget import BudgetExceeded, BudgetGuard
from coding_orchestrator.orchestrator.escalation import EscalationManager
from coding_orchestrator.orchestrator.router import TaskClassifier
from coding_orchestrator.orchestrator.state import StateStore
from coding_orchestrator.orchestrator.timeouts import TimeoutExceeded, TimeoutGuard
from coding_orchestrator.orchestrator.workflows import WORKFLOWS
from coding_orchestrator.schemas import (
    OrchestratorState,
    TaskSpec,
    ValidationResult,
    load_task_file,
)
from coding_orchestrator.tools.git import GitCheckpoint, GitManager
from coding_orchestrator.tools.opencode_runner import OpenCodeRunner
from coding_orchestrator.tools.patch import SafePatchApplier, parse_builder_output
from coding_orchestrator.validators.code_validator import SyntaxValidator
from coding_orchestrator.validators.patch_validator import PatchValidator
from coding_orchestrator.validators.safety_validator import CommandSafetyValidator
from coding_orchestrator.validators.test_validator import TestValidator


class DependencyError(RuntimeError):
    pass


class CommitFailed(RuntimeError):
    pass


class WorkflowEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.repo_path = Path(config.repo_path).resolve()
        self.classifier = TaskClassifier()
        self.model_router = ModelRouter(config.model_routing)
        budget_settings = config.budget
        ledger_path = Path(budget_settings.ledger_path)
        if not ledger_path.is_absolute():
            budget_settings = budget_settings.model_copy(
                update={"ledger_path": str((self.repo_path / ledger_path).resolve())}
            )
        self.budget = BudgetGuard(budget_settings, config.pricing)
        self.logger = JsonlLogger(Path(config.log_path))
        self.state_store = StateStore(Path(config.state_path))
        self.escalation = EscalationManager(Path("logs/escalations"))
        self.git = GitManager(self.repo_path)
        self.patch_applier = SafePatchApplier(
            self.repo_path,
            self.config.validation,
            self.config.timeouts.max_attempt_runtime_seconds,
        )

    def run_task_file(self, task_path: Path) -> OrchestratorState:
        return self.run_task(load_task_file(task_path))

    def run_task(self, task: TaskSpec) -> OrchestratorState:
        state = self._initial_state(task)
        max_runtime = min(task.max_runtime_seconds, self.config.timeouts.max_task_runtime_seconds)
        guard = TimeoutGuard(max_runtime)
        self.logger.log("task_started", request_id=state.request_id, task_id=task.id)
        validation_errors: list[str] = []
        checkpoint: GitCheckpoint | None = None
        try:
            checkpoint = self.git.checkpoint(task.id, self.config.git.require_clean_worktree)
            if state.requires_human_approval:
                state.final_status = "blocked"
                return self._finish(state, "task_blocked")
            while state.retry_count < task.max_attempts:
                guard.check()
                state.final_status = "running"
                self._run_builder_step(task, state, validation_errors)
                results = self._validate(task)
                state.validation_results = {result.name: result.model_dump() for result in results}
                validation_errors = [result.message for result in results if not result.passed]
                if not validation_errors:
                    self._commit(task, state)
                    state.final_status = "completed"
                    self.budget.record(state)
                    return self._finish(state, "task_completed")
                self.logger.log(
                    "validation_failed",
                    request_id=state.request_id,
                    task_id=task.id,
                    errors=validation_errors,
                    retry=state.retry_count,
                )
                state.retry_count += 1
            self._handle_failure(task, state, validation_errors, checkpoint)
            return state
        except TimeoutExceeded as exc:
            state.final_status = "timeout"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            self._escalate_if_allowed(task, state, validation_errors)
            return self._finish(state, "task_timeout")
        except BudgetExceeded as exc:
            state.final_status = "blocked"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["budget"] = {
                "name": "budget",
                "passed": False,
                "message": str(exc),
                "details": state.tool_results.get("budget_estimate", {}),
            }
            return self._finish(state, "task_budget_blocked")
        except Exception as exc:
            state.final_status = "failed"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            self._escalate_if_allowed(task, state, validation_errors)
            return self._finish(state, "task_failed")

    def run_all(self, tasks_dir: Path) -> list[OrchestratorState]:
        tasks = [load_task_file(path) for path in sorted(tasks_dir.glob("*")) if path.is_file()]
        ordered = order_tasks(tasks)
        completed: set[str] = set()
        states: list[OrchestratorState] = []
        for task in ordered:
            if any(dep not in completed for dep in task.depends_on):
                state = self._initial_state(task)
                state.final_status = "skipped"
                states.append(self._finish(state, "task_skipped_blocked_dependency"))
                continue
            state = self.run_task(task)
            states.append(state)
            if state.final_status == "completed":
                completed.add(task.id)
        return states

    def _initial_state(self, task: TaskSpec) -> OrchestratorState:
        complexity = self.classifier.classify_complexity(task)
        risk = self.classifier.classify_risk(task)
        workflow = self.classifier.select_workflow(task)
        model = self.model_router.select_model(complexity, risk)
        state = OrchestratorState(
            request_id=str(uuid4()),
            user_request=task.description or task.title,
            task_id=task.id,
            task_type=self.classifier.classify_task_type(task),
            complexity=complexity,
            risk_level=risk,
            repo_path=str(self.repo_path),
            relevant_files=task.allowed_files,
            selected_model=model,
            selected_workflow=workflow,
            requires_human_approval=model == "human-approval",
        )
        state.estimated_input_tokens = max(1, len(state.user_request) // 4)
        state.estimated_output_tokens = 1000
        state.estimated_cost_usd = self.budget.estimate(state.user_request)
        if not self.budget.can_spend(task, state):
            state.requires_human_approval = True
        return state

    def _run_builder_step(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> None:
        workflow = WORKFLOWS[state.selected_workflow or "fix_bug"]
        context = workflow.build_context(task, state)
        if validation_errors:
            context += "\n\nPrevious validation feedback:\n" + self._compact_feedback(state)
        state.retrieved_context = [context]
        estimate = self.budget.estimate_pre_call(
            task=task,
            attempt_id=state.retry_count + 1,
            model_role="cheap_builder",
            context=context,
            model_override=state.selected_model or self.config.opencode.default_model,
        )
        state.estimated_input_tokens = estimate.estimated_input_tokens
        state.estimated_output_tokens = estimate.estimated_output_tokens
        state.estimated_cost_usd = estimate.estimated_total_cost_usd
        state.tool_results["budget_estimate"] = estimate.model_dump()
        self.budget.check_pre_call(task, estimate)
        self.budget.record_estimate(estimate, status="estimated")
        runner = OpenCodeRunner(
            self.repo_path,
            state.selected_model or self.config.opencode.default_model,
            self.config.opencode,
        )
        response = runner.run_bounded_step(task, context)
        state.tool_results["builder"] = {
            "model": state.selected_model,
            "confidence": response.confidence,
            "text": response.text,
            "returncode": response.returncode,
            "stderr": response.stderr[-4000:],
            "timed_out": response.timed_out,
            "dry_run": response.dry_run,
        }
        if response.dry_run:
            return
        parsed = parse_builder_output(response.text)
        if parsed is None:
            return
        self.patch_applier.apply(parsed, task)
        state.tool_results["patch"] = parsed.model_dump()

    def _validate(self, task: TaskSpec) -> list[ValidationResult]:
        changed = self.git.changed_files()
        commands = task.validation_commands or self.config.validation.default_commands
        timeout = self.config.timeouts.max_attempt_runtime_seconds
        return [
            CommandSafetyValidator(
                commands,
                self.config.tool_permissions.allowlisted_shell_commands,
            ).validate(),
            PatchValidator(
                changed,
                self.repo_path,
                task.allowed_files,
                self.config.validation,
            ).validate(),
            SyntaxValidator(self.repo_path, timeout).validate(),
            TestValidator(commands, self.repo_path, timeout).validate(),
        ]

    def _commit(self, task: TaskSpec, state: OrchestratorState) -> None:
        result = self.git.commit_task(task.id, task.title, task.allowed_files)
        state.tool_results["git_commit"] = result.model_dump()
        if result.returncode != 0:
            raise CommitFailed(result.stderr or result.stdout or "git commit failed")

    def _handle_failure(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        checkpoint: GitCheckpoint,
    ) -> None:
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self.config.git.preserve_untracked_files,
        )
        if self._escalate_if_allowed(task, state, validation_errors):
            state.final_status = "escalated"
        else:
            state.final_status = "failed"
        self._finish(state, state.final_status)

    def _escalate_if_allowed(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> bool:
        if not self.escalation.should_escalate(task, state, validation_errors):
            return False
        path = self.escalation.create_package(
            task=task,
            state=state,
            diff=self.git.diff(),
            logs=self._collect_relevant_logs(state),
            validation_errors=validation_errors,
        )
        state.tool_results["escalation_package"] = str(path)
        self.logger.log(
            "task_escalated",
            request_id=state.request_id,
            task_id=task.id,
            path=str(path),
        )
        return True

    def _finish(self, state: OrchestratorState, event: str) -> OrchestratorState:
        state.finished_at = datetime.now(UTC)
        self.state_store.append(state)
        self.logger.log(
            event,
            request_id=state.request_id,
            task_id=state.task_id,
            status=state.final_status,
            retries=state.retry_count,
            cost=state.estimated_cost_usd,
        )
        return state

    def _rollback_if_checkpoint(self, checkpoint: GitCheckpoint | None) -> None:
        if checkpoint is None:
            return
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self.config.git.preserve_untracked_files,
        )

    def _compact_feedback(self, state: OrchestratorState) -> str:
        lines: list[str] = []
        for name, result in state.validation_results.items():
            if not isinstance(result, dict) or result.get("passed"):
                continue
            lines.append(f"{name}: {result.get('message', '')}")
            details = result.get("details", {})
            if isinstance(details, dict):
                for command, command_result in details.items():
                    if isinstance(command_result, dict):
                        stdout = str(command_result.get("stdout", ""))[-1000:]
                        stderr = str(command_result.get("stderr", ""))[-1000:]
                        if stdout:
                            lines.append(f"{command} stdout:\n{stdout}")
                        if stderr:
                            lines.append(f"{command} stderr:\n{stderr}")
        return "\n".join(lines[-20:])

    def _collect_relevant_logs(self, state: OrchestratorState) -> list[str]:
        logs: list[str] = []
        for key in ("builder", "git_commit"):
            value = state.tool_results.get(key)
            if isinstance(value, dict):
                stderr = str(value.get("stderr", ""))[-4000:]
                stdout = str(value.get("stdout", ""))[-4000:]
                if stdout:
                    logs.append(f"{key} stdout:\n{stdout}")
                if stderr:
                    logs.append(f"{key} stderr:\n{stderr}")
        return logs


def order_tasks(tasks: list[TaskSpec]) -> list[TaskSpec]:
    by_id = {task.id: task for task in tasks}
    ordered: list[TaskSpec] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(task: TaskSpec) -> None:
        if task.id in permanent:
            return
        if task.id in temporary:
            raise DependencyError(f"Cycle detected at {task.id}")
        temporary.add(task.id)
        for dep in task.depends_on:
            if dep in by_id:
                visit(by_id[dep])
        temporary.remove(task.id)
        permanent.add(task.id)
        ordered.append(task)

    for item in tasks:
        visit(item)
    return ordered

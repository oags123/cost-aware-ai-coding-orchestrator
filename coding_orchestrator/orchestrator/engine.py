from __future__ import annotations

import json
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from coding_orchestrator.config import (
    AppConfig,
    ResolvedModelRole,
    ServiceTier,
    resolve_model_role,
)
from coding_orchestrator.models import OpenAIProvider
from coding_orchestrator.models.provider import (
    BuilderOutput,
    FlexUnavailableError,
    ModelProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderTransientError,
    ServiceTierMismatchError,
)
from coding_orchestrator.models.router import ModelRouter
from coding_orchestrator.observability.logger import JsonlLogger
from coding_orchestrator.observability.telegram import TelegramAlert, TelegramNotifier
from coding_orchestrator.orchestrator.budget import (
    BudgetEstimate,
    BudgetExceeded,
    BudgetGuard,
    BudgetUsage,
)
from coding_orchestrator.orchestrator.convergence import ConvergenceEvaluator
from coding_orchestrator.orchestrator.diagnosis import (
    DiagnosisError,
    DiagnosisReviewer,
    ReviewPacketBuilder,
    packet_to_prompt,
)
from coding_orchestrator.orchestrator.escalation import EscalationManager
from coding_orchestrator.orchestrator.limits import LimitExceeded, LimitGuard
from coding_orchestrator.orchestrator.router import TaskClassifier
from coding_orchestrator.orchestrator.state import StateStore
from coding_orchestrator.orchestrator.tier_policy import BuilderServiceTierPolicy
from coding_orchestrator.orchestrator.timeouts import TimeoutExceeded, TimeoutGuard
from coding_orchestrator.orchestrator.workflows import NON_MODIFYING_WORKFLOWS, WORKFLOWS
from coding_orchestrator.schemas import (
    BuilderResult,
    ConvergenceDecision,
    OrchestratorState,
    ReviewPacket,
    TaskSpec,
    ValidationResult,
    load_task_file,
)
from coding_orchestrator.tools.git import GitCheckpoint, GitManager
from coding_orchestrator.tools.lock import ConcurrentExecutionError, RepoLock
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
    def __init__(
        self,
        config: AppConfig,
        provider_overrides: dict[str, ModelProvider] | None = None,
        manual_service_tier_override: ServiceTier | None = None,
    ) -> None:
        self.config = config
        self.repo_path = Path(config.repo_path).resolve()
        self.provider_overrides = provider_overrides or {}
        self.manual_service_tier_override = manual_service_tier_override
        self.openai_provider = OpenAIProvider(config.providers.openai)
        self.classifier = TaskClassifier()
        self.model_router = ModelRouter(config.model_routing)
        budget_settings = config.budget
        ledger_path = self._resolve_repo_path(budget_settings.ledger_path)
        budget_settings = budget_settings.model_copy(update={"ledger_path": str(ledger_path)})
        self.budget = BudgetGuard(budget_settings, config.pricing)
        self.limits = LimitGuard(config.limits)
        self.tier_policy = BuilderServiceTierPolicy(config.inference.builder_service_tier)
        self.convergence = ConvergenceEvaluator(config.convergence)
        self.review_packet_builder = ReviewPacketBuilder(config.diagnosis)
        self.diagnosis_reviewer = DiagnosisReviewer(config.diagnosis)
        self.reviewer_calls_this_run = 0
        self.reviewer_calls_by_task: dict[str, int] = {}
        log_path = self._resolve_repo_path(config.log_path)
        state_path = self._resolve_repo_path(config.state_path)
        escalations_path = self._resolve_repo_path(config.escalations_path)
        self.logger = JsonlLogger(log_path)
        if self.manual_service_tier_override is not None:
            # Explicit, per-run, and loud: this can only be set by a caller that
            # deliberately opted in for this one run (e.g. a CLI flag), never by
            # config inheritance or any fallback/retry logic.
            self.logger.log(
                "manual_service_tier_override_active",
                override_tier=self.manual_service_tier_override,
                warning=(
                    f"MANUAL OVERRIDE: this run will use service_tier="
                    f"{self.manual_service_tier_override!r} instead of the mandatory "
                    "Flex tier for automatically routed calls. This was explicitly "
                    "requested for this run only."
                ),
            )
        self.telegram = TelegramNotifier(config.telegram, budget_settings)
        self.state_store = StateStore(state_path)
        self.escalation = EscalationManager(escalations_path)
        self.git = GitManager(self.repo_path)
        self._own_data_paths = self._relative_own_data_paths(
            [ledger_path, log_path, state_path, escalations_path]
        )
        self._own_data_paths.append(".orchestrator.lock")
        self.patch_applier = SafePatchApplier(
            self.repo_path,
            self.config.validation,
            self.config.timeouts.max_attempt_runtime_seconds,
        )

    def _resolve_repo_path(self, raw: str) -> Path:
        """Resolve a configured data path against the repo root, never the caller's
        current working directory, so logs/state/ledger/escalations land predictably
        regardless of where the CLI is invoked from."""
        path = Path(raw)
        return path if path.is_absolute() else (self.repo_path / path).resolve()

    def _preserve_files(self) -> list[str]:
        return [*self.config.git.preserve_untracked_files, *self._own_data_paths]

    def _changed_files(self) -> list[str]:
        """git-detected changed files, excluding the orchestrator's own runtime data
        (ledger/state/log/escalations) so its own bookkeeping is never mistaken for
        task output by patch/permission validation or convergence's unrelated-file-
        touch detection.
        """
        own = set(self._own_data_paths)
        return [path for path in self.git.changed_files() if path not in own]

    def _relative_own_data_paths(self, paths: list[Path]) -> list[str]:
        """Paths (relative to repo root) the orchestrator itself writes operational
        data to. Always excluded from git checkpoint/stash/clean, independent of the
        configured preserve_untracked_dirs/files, so a target repo's own .gitignore
        (or lack of one) can never cause the orchestrator to stash or delete its own
        ledger, state, log, or escalation files.
        """
        relative: list[str] = []
        for path in paths:
            try:
                relative.append(str(path.relative_to(self.repo_path)))
            except ValueError:
                continue
        return relative

    def run_task_file(self, task_path: Path) -> OrchestratorState:
        return self.run_task(load_task_file(task_path))

    def run_task(self, task: TaskSpec) -> OrchestratorState:
        try:
            with RepoLock(self.repo_path):
                return self._run_task_locked(task)
        except ConcurrentExecutionError as exc:
            state = self._initial_state(task)
            state.final_status = "blocked"
            self.logger.log(
                "concurrent_execution_blocked",
                request_id=state.request_id,
                task_id=task.id,
                error=str(exc),
            )
            return self._finish(state, "task_concurrent_execution_blocked")

    def _run_task_locked(self, task: TaskSpec) -> OrchestratorState:
        state = self._initial_state(task)
        max_runtime = min(task.max_runtime_seconds, self.config.timeouts.max_task_runtime_seconds)
        guard = TimeoutGuard(max_runtime)
        self.logger.log("task_started", request_id=state.request_id, task_id=task.id)
        validation_errors: list[str] = []
        checkpoint: GitCheckpoint | None = None
        try:
            checkpoint = self.git.checkpoint(
                task.id,
                self.config.git.require_clean_worktree,
                preserve_dirs=self.config.git.preserve_untracked_dirs,
                preserve_files=self._preserve_files(),
            )
            if state.requires_human_approval:
                state.final_status = "blocked"
                self._rollback_if_checkpoint(checkpoint)
                return self._finish(state, "task_blocked")
            while state.retry_count < task.max_attempts:
                guard.check()
                state.final_status = "running"
                self._run_builder_step(task, state, validation_errors)
                if state.tool_results.get("provider_dry_run"):
                    state.final_status = "dry_run"
                    self._rollback_if_checkpoint(checkpoint)
                    return self._finish(state, "task_dry_run")
                results = self.limits.enforce_validation_output(self._validate(task))
                state.validation_results = {result.name: result.model_dump() for result in results}
                validation_errors = [result.message for result in results if not result.passed]
                if any(
                    "validation_output_limit_exceeded" in error
                    for error in validation_errors
                ):
                    self._record_limit_failure(state, "validation_output_limit_exceeded")
                if not validation_errors:
                    changed = self._changed_files()
                    if not changed and state.selected_workflow not in NON_MODIFYING_WORKFLOWS:
                        state.final_status = "no_change"
                        self._rollback_if_checkpoint(checkpoint)
                        return self._finish(state, "task_no_change")
                    self._record_attempt_metrics(task, state, results)
                    self.git.verify_head(checkpoint)
                    self._commit(task, state, changed)
                    state.final_status = "completed"
                    self.budget.record(state)
                    self.git.restore_pending_work(checkpoint)
                    return self._finish(state, "task_completed")
                decision = self._record_attempt_metrics(task, state, results)
                self.logger.log(
                    "validation_failed",
                    request_id=state.request_id,
                    task_id=task.id,
                    errors=validation_errors,
                    retry=state.retry_count,
                    convergence=decision.model_dump(),
                )
                if decision.action in {
                    "request_diagnosis",
                    "pause_block_task",
                    "mark_non_converging",
                }:
                    if self._handle_non_converging(task, state, validation_errors, checkpoint):
                        state.retry_count += 1
                        continue
                    return state
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
        except LimitExceeded as exc:
            state.final_status = "blocked"
            validation_errors.append(exc.message)
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["limits"] = {
                "name": "limits",
                "passed": False,
                "message": exc.message,
                "details": {"status": exc.status},
            }
            self._record_limit_failure(state, exc.status)
            return self._finish(state, exc.status)
        except FlexUnavailableError as exc:
            state.final_status = "flex_unavailable"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["service_tier"] = {
                "name": "service_tier",
                "passed": False,
                "message": (
                    f"{exc} No higher-priced tier was used; this run stayed on Flex "
                    "only, as required."
                ),
                "details": state.tool_results.get("builder_flex_transient_error", {}),
            }
            return self._finish(state, "task_flex_unavailable")
        except ServiceTierMismatchError as exc:
            state.final_status = "blocked"
            validation_errors.append(str(exc))
            self._rollback_if_checkpoint(checkpoint)
            state.validation_results["service_tier"] = {
                "name": "service_tier",
                "passed": False,
                "message": str(exc),
                "details": state.tool_results.get("service_tier_mismatch", {}),
            }
            return self._finish(state, "task_service_tier_mismatch")
        except Exception as exc:
            state.final_status = "failed"
            validation_errors.append(str(exc))
            state.tool_results["error_type"] = type(exc).__name__
            state.tool_results["error_traceback"] = traceback.format_exc()
            self.logger.log(
                "unexpected_error",
                request_id=state.request_id,
                task_id=task.id,
                error_type=type(exc).__name__,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
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
        if not completed and self.config.telegram.notify_on_no_runnable_tasks:
            self._send_telegram_alert(
                TelegramAlert(
                    project_id=self.budget.settings.project_id,
                    reason="no_runnable_tasks",
                    completed_count=0,
                    blocked_count=sum(1 for state in states if state.final_status != "completed"),
                    estimated_cost_spent=self.budget_report().project_total_spend_usd,
                    budget_remaining=self.budget_report().project_total_remaining_usd,
                    recommended_next_action="Review blocked task dependencies and task states.",
                )
            )
        return states

    def budget_report(self) -> BudgetUsage:
        metrics = self.limits.metrics
        return self.budget.report(
            limit_failures=metrics.limit_failures,
            largest_patch_bytes=metrics.largest_patch_bytes,
            largest_stdout_bytes=metrics.largest_stdout_bytes,
            largest_stderr_bytes=metrics.largest_stderr_bytes,
            largest_validation_output_bytes=metrics.largest_validation_output_bytes,
            service_tier_timeouts=dict(self.tier_policy.state.service_tier_timeouts),
            # Automatic tier fallback is structurally impossible under the strict
            # Flex-only policy -- this is always 0, which a report can point to as
            # positive evidence no fallback ever occurred.
            service_tier_fallbacks=0,
        )

    def convergence_report(self) -> dict[str, object]:
        return self.convergence.report()

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
            requires_human_approval=(
                model == "human-approval" or not WORKFLOWS[workflow].enabled
            ),
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
        guidance = self._diagnosis_guidance(state)
        if guidance:
            context += "\n\nDiagnosis-only reviewer guidance for current-role retry:\n" + guidance
        try:
            context = self.limits.prepare_context(context)
        except LimitExceeded:
            service_tier = self._effective_service_tier()
            role_name = self._select_builder_role(task, state)
            role = resolve_model_role(self.config, role_name, service_tier=service_tier)
            pricing = self.budget.pricing_for_role(role_name, service_tier)
            estimate = self.budget.estimate_pre_call(
                task=task,
                attempt_id=state.retry_count + 1,
                model_role=role_name,
                context=context,
                model_override=role.model or pricing.model,
                inference_tier=service_tier,
                max_output_tokens_override=role.max_output_tokens,
            )
            state.estimated_input_tokens = estimate.estimated_input_tokens
            state.estimated_output_tokens = estimate.estimated_output_tokens
            state.estimated_cost_usd = estimate.estimated_total_cost_usd
            state.tool_results["budget_estimate"] = estimate.model_dump()
            raise
        state.retrieved_context = [context]
        response = self._run_tiered_builder(task, state, context)
        response = self.limits.check_builder_output(response)
        state.tool_results["builder"] = {
            "model": state.tool_results.get("builder_model"),
            "provider": state.tool_results.get("builder_provider"),
            "role": state.tool_results.get("builder_role"),
            "service_tier": state.tool_results.get("builder_service_tier"),
            "tier": state.tool_results.get("builder_tier"),
            "backend": state.tool_results.get("builder_backend"),
            "confidence": response.confidence,
            "text": response.text,
            "returncode": response.returncode,
            "stderr": response.stderr[-4000:],
            "timed_out": response.timed_out,
            "dry_run": response.dry_run,
        }
        if response.dry_run:
            return
        if state.selected_workflow in NON_MODIFYING_WORKFLOWS:
            # explain_code/architecture_review/security_review produce prose, not a
            # patch -- never attempt to parse their output as a diff.
            return
        parsed = parse_builder_output(response.text)
        if parsed is None:
            return
        self.limits.check_patch(parsed)
        self.patch_applier.apply(parsed, task)
        state.tool_results["patch"] = parsed.model_dump()

    def _run_tiered_builder(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        context: str,
    ) -> BuilderResult:
        return self._run_role_builder(task, state, context)

    def _effective_service_tier(self) -> ServiceTier:
        """The tier automatic builder calls will request this run. Always "flex"
        unless an explicit, per-run manual override was passed to the constructor --
        never selected by config inheritance or any fallback/retry logic.
        """
        return self.manual_service_tier_override or "flex"

    def _run_role_builder(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        context: str,
    ) -> BuilderResult:
        requested_service_tier = self._effective_service_tier()
        is_manual_override = self.manual_service_tier_override is not None
        while True:
            role_name = self._select_builder_role(task, state)
            role = resolve_model_role(self.config, role_name, service_tier=requested_service_tier)
            if not is_manual_override and role.service_tier != "flex":
                # Defense in depth: AppConfig._enforce_flex_only_policy should already
                # make this unreachable, but a strict runtime invariant costs nothing.
                raise ProviderConfigurationError(
                    f"strict Flex-only policy violation: role {role_name!r} resolved "
                    f"to service_tier={role.service_tier!r} without a manual override"
                )
            estimate = self.budget.estimate_pre_call(
                task=task,
                attempt_id=state.retry_count + 1,
                model_role=role_name,
                context=context,
                model_override=role.model,
                inference_tier=requested_service_tier,
                max_output_tokens_override=role.max_output_tokens,
            )
            self._prepare_builder_call(task, state, estimate)
            self.tier_policy.record_call(requested_service_tier)
            request = ProviderRequest(
                role=role,
                prompt=context,
                response_schema_name="builder_patch_contract",
                metadata={
                    "task_id": task.id,
                    "attempt_id": str(state.retry_count + 1),
                    "requested_service_tier": requested_service_tier,
                    "manual_override": str(is_manual_override),
                    "provider": role.provider,
                    "model": role.model,
                },
            )
            provider = self._provider_for_role(role)
            state.tool_results["requested_service_tier"] = requested_service_tier
            state.tool_results["manual_service_tier_override"] = is_manual_override
            try:
                response = provider.generate(request)
            except ProviderConfigurationError as exc:
                self.logger.log(
                    "provider_configuration_dry_run",
                    request_id=state.request_id,
                    task_id=task.id,
                    provider=role.provider,
                    model=role.model,
                    error=str(exc),
                )
                state.selected_model = role.model
                state.tool_results["builder_role"] = role_name
                state.tool_results["builder_tier"] = requested_service_tier
                state.tool_results["builder_service_tier"] = requested_service_tier
                state.tool_results["builder_model"] = role.model
                state.tool_results["builder_provider"] = role.provider
                state.tool_results["builder_backend"] = "role_provider"
                state.tool_results["builder_warning"] = str(exc)
                state.tool_results["provider_dry_run"] = True
                return BuilderResult(
                    text=f"# Provider dry-run fallback for {role.provider}/{role.model}",
                    confidence=0.0,
                    estimated_output_tokens=0,
                    command=[f"<provider:{role.provider}>"],
                    returncode=0,
                    stdout="",
                    stderr=str(exc),
                    timed_out=False,
                    runtime_seconds=0.0,
                    dry_run=True,
                )
            except ProviderError as exc:
                is_transient = isinstance(
                    exc, ProviderTransientError
                ) or self._is_flex_transient_error(str(exc))
                if requested_service_tier == "flex" and is_transient:
                    self.tier_policy.record_transient_failure("flex")
                    consecutive = self.tier_policy.state.consecutive_flex_transient_failures
                    state.tool_results["builder_flex_transient_error"] = {
                        "service_tier": "flex",
                        "message": str(exc),
                        "consecutive_failures": consecutive,
                    }
                    self.logger.log(
                        "flex_transient_error",
                        request_id=state.request_id,
                        task_id=task.id,
                        attempt=consecutive,
                        max_retries=self.tier_policy.settings.flex.max_flex_retries,
                        error=str(exc),
                    )
                    if self.tier_policy.should_retry_flex():
                        # Bounded retry: tier NEVER changes. Still requesting Flex.
                        continue
                    self.tier_policy.mark_flex_unavailable()
                    raise FlexUnavailableError(
                        "Flex capacity exhausted after "
                        f"{self.tier_policy.settings.flex.max_flex_retries} bounded "
                        f"retries; no higher-priced tier was used. Last error: {exc}"
                    ) from exc
                raise
            if response.service_tier != requested_service_tier:
                state.tool_results["service_tier_mismatch"] = {
                    "requested": requested_service_tier,
                    "actual": response.service_tier,
                }
                self.logger.log(
                    "service_tier_mismatch",
                    request_id=state.request_id,
                    task_id=task.id,
                    requested=requested_service_tier,
                    actual=response.service_tier,
                )
                raise ServiceTierMismatchError(
                    f"requested service_tier={requested_service_tier!r} but provider "
                    f"returned service_tier={response.service_tier!r}; refusing to "
                    "treat this as a normal successful call"
                )
            self.tier_policy.record_success(requested_service_tier)
            state.tool_results["actual_service_tier"] = response.service_tier
            state.selected_model = role.model
            state.tool_results["builder_role"] = role_name
            state.tool_results["builder_tier"] = requested_service_tier
            state.tool_results["builder_service_tier"] = requested_service_tier
            state.tool_results["builder_model"] = role.model
            state.tool_results["builder_provider"] = role.provider
            state.tool_results["builder_backend"] = "role_provider"
            state.tool_results["builder_request"] = request.model_dump()
            state.tool_results["builder_response_usage"] = response.usage.model_dump()
            self.budget.record_actual(
                estimate,
                response.usage,
                requested_service_tier=requested_service_tier,
                actual_service_tier=response.service_tier,
                fallback_occurred=False,
            )
            return self._provider_response_to_builder_result(response)

    def _is_flex_transient_error(self, error_text: str) -> bool:
        lowered = error_text.lower()
        return any(
            marker in lowered
            for marker in ("429", "timeout", "timed out", "resource unavailable", "rate limit")
        )

    def _provider_for_role(self, role: ResolvedModelRole) -> ModelProvider:
        if role.provider in self.provider_overrides:
            return self.provider_overrides[role.provider]
        if role.provider == "openai":
            return self.openai_provider
        raise ProviderConfigurationError(f"unsupported model provider: {role.provider}")

    def _provider_response_to_builder_result(self, response: ProviderResponse) -> BuilderResult:
        text = response.text
        confidence = response.confidence
        if isinstance(response.structured_output, BuilderOutput):
            text = response.structured_output.model_dump_json()
            confidence = response.structured_output.confidence
        elif isinstance(response.structured_output, dict):
            text = json.dumps(response.structured_output)
        return BuilderResult(
            text=text,
            confidence=confidence,
            estimated_output_tokens=max(1, response.usage.output_tokens),
            command=[f"<provider:{response.provider}>"],
            returncode=0,
            stdout=text,
            stderr="",
            timed_out=False,
            runtime_seconds=0.0,
            dry_run=False,
        )

    def _select_builder_role(self, task: TaskSpec, state: OrchestratorState) -> str:
        if state.retry_count > 0:
            return "general_builder"
        if state.risk_level == "high" or state.complexity in {"hard", "critical"}:
            return "general_builder"
        has_validation = bool(task.validation_commands or self.config.validation.default_commands)
        if (
            state.complexity in {"trivial", "simple"}
            and len(task.allowed_files) <= 1
            and has_validation
            and state.task_type in {"write_tests", "explain_code"}
        ):
            return "mechanical_worker"
        if state.complexity in {"trivial", "simple"} and len(task.allowed_files) <= 2:
            return "simple_builder"
        return "general_builder"

    def _prepare_builder_call(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        estimate: BudgetEstimate,
    ) -> None:
        state.estimated_input_tokens = estimate.estimated_input_tokens
        state.estimated_output_tokens = estimate.estimated_output_tokens
        state.estimated_cost_usd = estimate.estimated_total_cost_usd
        state.tool_results["budget_estimate"] = estimate.model_dump()
        self.limits.check_pre_call(estimate)
        self.budget.check_pre_call(task, estimate)
        self.budget.record_estimate(estimate, status="estimated")

    def _validate(self, task: TaskSpec) -> list[ValidationResult]:
        changed = self._changed_files()
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
            SyntaxValidator(changed, self.repo_path, timeout).validate(),
            TestValidator(commands, self.repo_path, timeout).validate(),
        ]

    def _commit(self, task: TaskSpec, state: OrchestratorState, changed_files: list[str]) -> None:
        result = self.git.commit_task(task.id, task.title, changed_files, task.allowed_files)
        state.tool_results["git_commit"] = result.model_dump()
        if result.returncode != 0:
            raise CommitFailed(result.stderr or result.stdout or "git commit failed")

    def _record_attempt_metrics(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        results: list[ValidationResult],
    ) -> ConvergenceDecision:
        previous = state.attempt_metrics[-1] if state.attempt_metrics else None
        metrics = self.convergence.collect_attempt_metrics(
            attempt_number=state.retry_count + 1,
            validation_results=results,
            changed_files=self._changed_files(),
            allowed_files=task.allowed_files,
            tool_results=state.tool_results,
            previous=previous,
        )
        decision = self.convergence.evaluate(metrics, previous)
        state.attempt_metrics.append(metrics)
        state.convergence_status = decision.status
        state.convergence_decision = decision
        state.tool_results["convergence"] = decision.model_dump()
        self.logger.log(
            "attempt_metrics",
            request_id=state.request_id,
            task_id=task.id,
            metrics=metrics.model_dump(),
            convergence=decision.model_dump(),
        )
        return decision

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
            self._preserve_files(),
        )
        if self._escalate_if_allowed(task, state, validation_errors):
            state.final_status = "escalated"
        else:
            state.final_status = "failed"
        self._finish(state, state.final_status)

    def _handle_non_converging(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        checkpoint: GitCheckpoint,
    ) -> bool:
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self._preserve_files(),
        )
        if (
            state.convergence_decision
            and state.convergence_decision.action == "request_diagnosis"
            and self.config.diagnosis.enabled
        ):
            review_packet = self._build_review_packet(task, state, validation_errors)
            state.tool_results["review_packet"] = review_packet.model_dump()
            try:
                self._run_diagnosis_reviewer(task, state, review_packet)
            except (BudgetExceeded, LimitExceeded, DiagnosisError) as exc:
                state.tool_results["diagnosis_error"] = str(exc)
                if isinstance(exc, BudgetExceeded):
                    state.validation_results["budget"] = {
                        "name": "budget",
                        "passed": False,
                        "message": str(exc),
                        "details": state.tool_results.get("diagnosis_budget_estimate", {}),
                    }
                    state.final_status = "blocked"
                else:
                    state.final_status = "escalated"
                self._create_diagnosis_needed_package(task, state, validation_errors, review_packet)
                self._finish(state, "diagnosis_needed")
                return False
            diagnosis = state.tool_results.get("diagnosis", {})
            if (
                isinstance(diagnosis, dict)
                and diagnosis.get("should_retry_with_builder")
                and state.retry_count + 1 < task.max_attempts
            ):
                state.tool_results["reviewer_guidance"] = {
                    "guided_fix_instruction": diagnosis.get("guided_fix_instruction", ""),
                    "summary": diagnosis.get("minimal_fix_strategy", ""),
                    "files_to_focus": diagnosis.get("files_to_focus", []),
                }
                self.logger.log(
                    "diagnosis_guided_retry",
                    request_id=state.request_id,
                    task_id=task.id,
                    diagnosis=diagnosis,
                )
                return True
        if state.convergence_status == "diverging":
            state.final_status = "blocked"
        else:
            state.final_status = "escalated"
        self._create_diagnosis_needed_package(task, state, validation_errors)
        self._finish(state, "diagnosis_needed")
        return False

    def _build_review_packet(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
    ) -> ReviewPacket:
        return self.review_packet_builder.build(
            task=task,
            state=state,
            diff=self.git.diff(),
            logs=self._collect_relevant_logs(state),
            validation_errors=validation_errors,
            remaining_task_usd=max(0.0, task.max_cost_usd - state.estimated_cost_usd),
            projected_review_usd=0.0,
        )

    def _create_diagnosis_needed_package(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        validation_errors: list[str],
        review_packet: ReviewPacket | None = None,
    ) -> None:
        diff = self.git.diff()
        logs = self._collect_relevant_logs(state)
        review_packet = review_packet or self._build_review_packet(task, state, validation_errors)
        state.tool_results["review_packet"] = review_packet.model_dump()
        path = self.escalation.create_package(
            task=task,
            state=state,
            diff=diff,
            logs=[
                "diagnosis_needed: builder role is non-converging; "
                "future diagnosis-only reviewer should inspect this package.",
                *logs,
            ],
            validation_errors=validation_errors,
        )
        state.tool_results["diagnosis_needed_package"] = str(path)
        self.logger.log(
            "diagnosis_needed",
            request_id=state.request_id,
            task_id=task.id,
            path=str(path),
            convergence=state.convergence_decision.model_dump()
            if state.convergence_decision
            else {},
        )

    def _run_diagnosis_reviewer(
        self,
        task: TaskSpec,
        state: OrchestratorState,
        review_packet: ReviewPacket,
    ) -> None:
        prompt = packet_to_prompt(review_packet)
        self._check_reviewer_call_limits(task.id)
        if len(prompt) > self.config.diagnosis.max_context_chars:
            raise LimitExceeded(
                "context_limit_exceeded",
                "diagnosis review packet exceeds max_context_chars",
            )
        estimate = self.budget.estimate_pre_call(
            task=task,
            attempt_id=len(state.attempt_metrics) + 1,
            model_role=self.config.diagnosis.model_role,
            context=prompt,
            model_override=self.config.diagnosis.model,
            max_output_tokens_override=self.config.diagnosis.max_output_tokens,
        )
        state.tool_results["diagnosis_budget_estimate"] = estimate.model_dump()
        if estimate.estimated_input_tokens > self.config.diagnosis.max_input_tokens:
            raise LimitExceeded(
                "context_limit_exceeded",
                "diagnosis input tokens exceed max_input_tokens",
            )
        if estimate.estimated_output_tokens > self.config.diagnosis.max_output_tokens:
            raise LimitExceeded(
                "output_limit_exceeded",
                "diagnosis output tokens exceed max_output_tokens",
            )
        if estimate.estimated_total_cost_usd > self.config.diagnosis.max_cost_per_call_usd:
            self.budget.record_estimate(estimate, status="blocked")
            raise BudgetExceeded("diagnosis reviewer max_cost_per_call_usd exceeded")
        self.limits.check_pre_call(estimate)
        self.budget.check_pre_call(task, estimate)
        self.budget.record_estimate(estimate, status="estimated")
        try:
            diagnosis = self.diagnosis_reviewer.diagnose(review_packet)
        except DiagnosisError as exc:
            state.tool_results["diagnosis_error"] = str(exc)
            raise
        state.tool_results["diagnosis"] = diagnosis.model_dump()
        self._record_reviewer_call(task.id)

    def _check_reviewer_call_limits(self, task_id: str) -> None:
        if self.reviewer_calls_this_run >= self.config.diagnosis.max_calls_per_run:
            raise BudgetExceeded("diagnosis reviewer max_calls_per_run exceeded")
        task_calls = self.reviewer_calls_by_task.get(task_id, 0)
        if task_calls >= self.config.diagnosis.max_calls_per_task:
            raise BudgetExceeded("diagnosis reviewer max_calls_per_task exceeded")

    def _record_reviewer_call(self, task_id: str) -> None:
        self.reviewer_calls_this_run += 1
        self.reviewer_calls_by_task[task_id] = self.reviewer_calls_by_task.get(task_id, 0) + 1

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
        if self.config.telegram.notify_on_blocked:
            self._notify_state(
                "human_attention_needed",
                state,
                "Review the escalation package and decide the next bounded action.",
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
        self._notify_on_finish(state, event)
        return state

    def _rollback_if_checkpoint(self, checkpoint: GitCheckpoint | None) -> None:
        if checkpoint is None:
            return
        self.git.rollback_to_checkpoint(
            checkpoint,
            self.config.git.preserve_untracked_dirs,
            self._preserve_files(),
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
        feedback = "\n".join(lines[-20:])
        return feedback[-self.config.limits.max_retry_context_chars :]

    def _diagnosis_guidance(self, state: OrchestratorState) -> str:
        guidance = state.tool_results.get("reviewer_guidance")
        if not isinstance(guidance, dict):
            return ""
        parts = [
            str(guidance.get("guided_fix_instruction", "")),
            str(guidance.get("summary", "")),
        ]
        files = guidance.get("files_to_focus", [])
        if isinstance(files, list) and files:
            parts.append("Files to focus: " + ", ".join(str(item) for item in files))
        return "\n".join(part for part in parts if part)[
            -self.config.limits.max_retry_context_chars :
        ]

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

    def _record_limit_failure(self, state: OrchestratorState, status: str) -> None:
        estimate_data = state.tool_results.get("budget_estimate")
        if not isinstance(estimate_data, dict):
            return
        try:
            estimate = self.budget_estimate_from_dict(estimate_data)
        except ValueError:
            return
        self.budget.record_estimate(estimate, status=status)

    def budget_estimate_from_dict(self, data: dict[str, object]) -> BudgetEstimate:
        return BudgetEstimate.model_validate(data)

    def _notify_on_finish(self, state: OrchestratorState, event: str) -> None:
        if state.final_status == "blocked" and self.config.telegram.notify_on_blocked:
            reason = "blocked"
            if event == "task_budget_blocked" and self.config.telegram.notify_on_budget_exhausted:
                reason = "budget_exhausted"
            self._notify_state(reason, state, "Inspect task state and budget/validator details.")
        elif state.final_status == "timeout" and self.config.telegram.notify_on_runtime_exhausted:
            self._notify_state(
                "runtime_exhausted",
                state,
                "Review timeout settings or split the task into smaller work.",
            )
        elif state.final_status == "failed" and self.config.telegram.notify_on_system_error:
            self._notify_state(
                "system_error",
                state,
                "Inspect logs and escalation package before retrying.",
            )
        elif state.final_status == "escalated" and self.config.telegram.notify_on_blocked:
            self._notify_state(
                "human_attention_needed",
                state,
                "Review escalation package and decide whether to retry or intervene.",
            )

    def _notify_state(
        self,
        reason: str,
        state: OrchestratorState,
        recommended_next_action: str,
    ) -> None:
        usage = self.budget_report()
        alert = self.telegram.alert_from_state(
            reason=reason,
            state=state,
            usage=usage,
            recommended_next_action=recommended_next_action,
        )
        self._send_telegram_alert(alert)

    def _send_telegram_alert(self, alert: TelegramAlert) -> None:
        warning = self.telegram.send_alert(alert)
        if warning:
            self.logger.log(
                "telegram_warning",
                reason=alert.reason,
                warning=warning,
            )


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

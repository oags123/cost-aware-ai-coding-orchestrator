from __future__ import annotations

from dataclasses import dataclass, field

from coding_orchestrator.config import LimitSettings
from coding_orchestrator.orchestrator.budget import BudgetEstimate
from coding_orchestrator.schemas import BuilderResult, ParsedPatch, ValidationResult


class LimitExceeded(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class LimitMetrics:
    limit_failures: dict[str, int] = field(default_factory=dict)
    largest_context_chars: int = 0
    largest_input_tokens: int = 0
    largest_patch_bytes: int = 0
    largest_stdout_bytes: int = 0
    largest_stderr_bytes: int = 0
    largest_validation_output_bytes: int = 0

    def record_failure(self, status: str) -> None:
        self.limit_failures[status] = self.limit_failures.get(status, 0) + 1


@dataclass
class LimitGuard:
    settings: LimitSettings
    metrics: LimitMetrics = field(default_factory=LimitMetrics)

    def prepare_context(self, context: str) -> str:
        self.metrics.largest_context_chars = max(self.metrics.largest_context_chars, len(context))
        if len(context) <= self.settings.max_context_chars_per_call:
            return context
        if self.settings.context_over_limit_policy == "trim":
            trimmed = context[-self.settings.max_context_chars_per_call :]
            self.metrics.largest_context_chars = max(
                self.metrics.largest_context_chars,
                len(trimmed),
            )
            return trimmed
        self.metrics.record_failure("context_limit_exceeded")
        raise LimitExceeded(
            "context_limit_exceeded",
            (
                "Context size exceeds max_context_chars_per_call "
                f"({len(context)} > {self.settings.max_context_chars_per_call})"
            ),
        )

    def check_pre_call(self, estimate: BudgetEstimate) -> None:
        self.metrics.largest_input_tokens = max(
            self.metrics.largest_input_tokens,
            estimate.estimated_input_tokens,
        )
        if estimate.estimated_input_tokens > self.settings.max_input_tokens_per_call:
            self.metrics.record_failure("context_limit_exceeded")
            raise LimitExceeded(
                "context_limit_exceeded",
                (
                    "Estimated input tokens exceed max_input_tokens_per_call "
                    f"({estimate.estimated_input_tokens} > "
                    f"{self.settings.max_input_tokens_per_call})"
                ),
            )
        if estimate.estimated_output_tokens > self.settings.max_output_tokens_per_call:
            self.metrics.record_failure("output_limit_exceeded")
            raise LimitExceeded(
                "output_limit_exceeded",
                (
                    "Estimated output tokens exceed max_output_tokens_per_call "
                    f"({estimate.estimated_output_tokens} > "
                    f"{self.settings.max_output_tokens_per_call})"
                ),
            )

    def check_builder_output(self, response: BuilderResult) -> BuilderResult:
        stdout_bytes = len(response.stdout.encode("utf-8"))
        stderr_bytes = len(response.stderr.encode("utf-8"))
        self.metrics.largest_stdout_bytes = max(self.metrics.largest_stdout_bytes, stdout_bytes)
        self.metrics.largest_stderr_bytes = max(self.metrics.largest_stderr_bytes, stderr_bytes)
        stdout_too_large = stdout_bytes > self.settings.max_stdout_bytes
        stderr_too_large = stderr_bytes > self.settings.max_stderr_bytes
        if not stdout_too_large and not stderr_too_large:
            return response
        if self.settings.output_over_limit_policy == "truncate":
            return response.model_copy(
                update={
                    "stdout": truncate_bytes(response.stdout, self.settings.max_stdout_bytes),
                    "stderr": truncate_bytes(response.stderr, self.settings.max_stderr_bytes),
                    "text": truncate_bytes(response.text, self.settings.max_stdout_bytes),
                }
            )
        self.metrics.record_failure("output_limit_exceeded")
        raise LimitExceeded(
            "output_limit_exceeded",
            (
                "Builder output exceeds stdout/stderr byte limits "
                f"(stdout={stdout_bytes}/{self.settings.max_stdout_bytes}, "
                f"stderr={stderr_bytes}/{self.settings.max_stderr_bytes})"
            ),
        )

    def check_patch(self, parsed: ParsedPatch) -> None:
        patch_bytes = len(parsed.patch.encode("utf-8"))
        self.metrics.largest_patch_bytes = max(self.metrics.largest_patch_bytes, patch_bytes)
        if patch_bytes <= self.settings.max_patch_bytes:
            return
        self.metrics.record_failure("patch_limit_exceeded")
        raise LimitExceeded(
            "patch_limit_exceeded",
            f"Patch size exceeds max_patch_bytes ({patch_bytes} > {self.settings.max_patch_bytes})",
        )

    def enforce_validation_output(self, results: list[ValidationResult]) -> list[ValidationResult]:
        total = sum(_validation_output_bytes(result) for result in results)
        self.metrics.largest_validation_output_bytes = max(
            self.metrics.largest_validation_output_bytes,
            total,
        )
        if total <= self.settings.max_validation_output_bytes:
            return results

        self.metrics.record_failure("validation_output_limit_exceeded")
        if self.settings.validation_output_over_limit_policy == "reject":
            return [
                *results,
                ValidationResult(
                    name="limits",
                    passed=False,
                    message=(
                        "validation_output_limit_exceeded: validation output exceeds "
                        f"max_validation_output_bytes ({total} > "
                        f"{self.settings.max_validation_output_bytes})"
                    ),
                    details={"validation_output_bytes": total},
                ),
            ]

        return [
            _truncate_validation_result(result, self.settings.max_validation_output_bytes)
            for result in results
        ]


def truncate_bytes(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    if max_bytes <= 0:
        return ""
    return encoded[-max_bytes:].decode("utf-8", errors="replace")


def _validation_output_bytes(result: ValidationResult) -> int:
    return len(result.message.encode("utf-8")) + _value_bytes(result.details)


def _value_bytes(value: object) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, dict):
        return sum(_value_bytes(item) for item in value.values())
    if isinstance(value, list):
        return sum(_value_bytes(item) for item in value)
    return 0


def _truncate_validation_result(result: ValidationResult, max_bytes: int) -> ValidationResult:
    budget = max(0, max_bytes // 2)
    details = _truncate_details(result.details, budget)
    message = truncate_bytes(result.message, budget)
    details["_limit_notice"] = "validation_output_limit_exceeded; output truncated"
    return result.model_copy(update={"message": message, "details": details})


def _truncate_details(value: dict[str, object], max_bytes: int) -> dict[str, object]:
    truncated: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            truncated[key] = truncate_bytes(item, max_bytes)
        elif isinstance(item, dict):
            truncated[key] = _truncate_nested_dict(item, max_bytes)
        else:
            truncated[key] = item
    return truncated


def _truncate_nested_dict(value: dict[object, object], max_bytes: int) -> dict[object, object]:
    truncated: dict[object, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            truncated[key] = truncate_bytes(item, max_bytes)
        elif isinstance(item, dict):
            truncated[key] = _truncate_nested_dict(item, max_bytes)
        else:
            truncated[key] = item
    return truncated

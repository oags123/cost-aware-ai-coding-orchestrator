from __future__ import annotations

from dataclasses import dataclass

from coding_orchestrator.config import DiagnosisSettings
from coding_orchestrator.schemas import DiagnosisResult, OrchestratorState, ReviewPacket, TaskSpec


class DiagnosisError(RuntimeError):
    pass


@dataclass
class ReviewPacketBuilder:
    settings: DiagnosisSettings

    def build(
        self,
        *,
        task: TaskSpec,
        state: OrchestratorState,
        diff: str,
        logs: list[str],
        validation_errors: list[str],
        remaining_task_usd: float,
        projected_review_usd: float,
    ) -> ReviewPacket:
        packet = ReviewPacket(
            task={
                "id": task.id,
                "title": task.title,
                "complexity": task.complexity,
                "risk": task.risk,
                "allowed_files": task.allowed_files,
            },
            budget={
                "remaining_task_usd": remaining_task_usd,
                "projected_review_usd": projected_review_usd,
            },
            attempts={
                "count": len(state.attempt_metrics),
                "metrics": [item.model_dump() for item in state.attempt_metrics],
                "convergence": state.convergence_decision.model_dump()
                if state.convergence_decision
                else {},
            },
            diff={
                "changed_files": _changed_files_from_state(state),
                "compact_patch": _tail(diff, self.settings.max_diff_chars),
            },
            validation={
                "current_failures": validation_errors,
                "compact_stdout": _tail(
                    "\n".join(_stream(logs, "stdout")),
                    self.settings.max_stdout_chars,
                ),
                "compact_stderr": _tail(
                    "\n".join(_stream(logs, "stderr")),
                    self.settings.max_stderr_chars,
                ),
            },
            question={
                "type": "diagnosis",
                "prompt": (
                    "What is the most likely root cause and next cheap-builder instruction? "
                    "Do not produce a patch."
                ),
            },
        )
        return _fit_packet(packet, self.settings.max_packet_chars)


@dataclass
class DiagnosisReviewer:
    settings: DiagnosisSettings

    def diagnose(self, packet: ReviewPacket) -> DiagnosisResult:
        if not self.settings.enabled:
            raise DiagnosisError("diagnosis reviewer is disabled")
        if not self.settings.dry_run:
            raise DiagnosisError("real diagnosis reviewer integration is not implemented")
        result = DiagnosisResult(
            root_cause="Dry-run diagnosis placeholder: inspect validator failures and latest diff.",
            risk_assessment="No real reviewer call was made; treat this as a routing artifact.",
            recommended_next_instruction=(
                "Use the review packet to craft a narrower cheap-builder retry instruction."
            ),
            files_to_focus=list(packet.task.get("allowed_files", [])),
            avoid=["direct expensive-model patch generation", "broad refactor"],
            confidence=0.4,
        )
        if result.direct_patch_proposed and not self.settings.allow_direct_patch:
            raise DiagnosisError(
                "diagnosis reviewer proposed a patch but direct patches are disabled"
            )
        return result


def packet_to_prompt(packet: ReviewPacket) -> str:
    return packet.model_dump_json(indent=2)


def _fit_packet(packet: ReviewPacket, max_chars: int) -> ReviewPacket:
    for section, key in (
        ("diff", "compact_patch"),
        ("validation", "compact_stdout"),
        ("validation", "compact_stderr"),
    ):
        text = packet_to_prompt(packet)
        if len(text) <= max_chars:
            return packet
        overage = len(text) - max_chars
        container = getattr(packet, section)
        value = str(container.get(key, ""))
        container[key] = _tail(value, max(0, len(value) - overage))
    return packet


def _tail(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _stream(logs: list[str], marker: str) -> list[str]:
    return [log for log in logs if marker in log.lower()]


def _changed_files_from_state(state: OrchestratorState) -> list[str]:
    patch = state.tool_results.get("patch")
    if isinstance(patch, dict):
        touched = patch.get("touched_files", [])
        if isinstance(touched, list):
            return [str(item) for item in touched]
    return []

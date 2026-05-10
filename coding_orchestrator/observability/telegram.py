from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from coding_orchestrator.config import BudgetSettings, TelegramSettings
from coding_orchestrator.orchestrator.budget import BudgetUsage
from coding_orchestrator.schemas import OrchestratorState


class TelegramWarning(RuntimeError):
    pass


class UrlOpener(Protocol):
    def __call__(
        self,
        request: urllib.request.Request,
        timeout: float,
    ) -> Any:
        """Open a prepared request."""


@dataclass(frozen=True)
class TelegramAlert:
    project_id: str
    reason: str
    run_id: str | None = None
    task_id: str | None = None
    completed_count: int | None = None
    blocked_count: int | None = None
    estimated_cost_spent: float = 0.0
    budget_remaining: float = 0.0
    last_error_summary: str = ""
    recommended_next_action: str = ""


class TelegramNotifier:
    def __init__(
        self,
        settings: TelegramSettings,
        budget_settings: BudgetSettings,
        opener: UrlOpener | None = None,
    ) -> None:
        self.settings = settings
        self.budget_settings = budget_settings
        self.opener = opener or urllib.request.urlopen

    def send_alert(self, alert: TelegramAlert) -> str | None:
        if not self.settings.enabled:
            return None
        token = os.environ.get(self.settings.bot_token_env_var)
        chat_id = os.environ.get(self.settings.chat_id_env_var)
        if not token or not chat_id:
            message = (
                "Telegram enabled but required environment variables are missing: "
                f"{self.settings.bot_token_env_var}, {self.settings.chat_id_env_var}"
            )
            if self.settings.missing_env_policy == "fail":
                raise TelegramWarning(message)
            return message

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": self._format_alert(alert),
            "disable_web_page_preview": True,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            self.opener(request, timeout=10)
        except urllib.error.URLError as exc:
            return f"Telegram alert failed: {exc}"
        return None

    def alert_from_state(
        self,
        *,
        reason: str,
        state: OrchestratorState,
        usage: BudgetUsage,
        recommended_next_action: str,
    ) -> TelegramAlert:
        return TelegramAlert(
            project_id=self.budget_settings.project_id,
            run_id=state.request_id,
            task_id=state.task_id,
            reason=reason,
            estimated_cost_spent=usage.project_total_spend_usd,
            budget_remaining=usage.project_total_remaining_usd,
            last_error_summary=_last_error_summary(state),
            recommended_next_action=recommended_next_action,
        )

    def _format_alert(self, alert: TelegramAlert) -> str:
        lines = [
            "Coding Orchestrator Alert",
            f"Project: {alert.project_id}",
            f"Reason: {alert.reason}",
        ]
        if alert.run_id:
            lines.append(f"Run: {alert.run_id}")
        if alert.task_id:
            lines.append(f"Task: {alert.task_id}")
        if alert.completed_count is not None or alert.blocked_count is not None:
            lines.append(
                "Counts: "
                f"completed={alert.completed_count or 0}, blocked={alert.blocked_count or 0}"
            )
        lines.extend(
            [
                f"Estimated spent: ${alert.estimated_cost_spent:.4f}",
                f"Budget remaining: ${alert.budget_remaining:.4f}",
            ]
        )
        if alert.last_error_summary:
            lines.append(f"Last error: {alert.last_error_summary}")
        if alert.recommended_next_action:
            lines.append(f"Next action: {alert.recommended_next_action}")
        return "\n".join(lines)


def _last_error_summary(state: OrchestratorState) -> str:
    for result in state.validation_results.values():
        if isinstance(result, dict) and not result.get("passed", True):
            return str(result.get("message", ""))[:500]
    for key in ("diagnosis_error", "builder_timeout"):
        value = state.tool_results.get(key)
        if value:
            return str(value)[:500]
    return ""

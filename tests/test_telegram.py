from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest

from coding_orchestrator.config import AppConfig, BudgetSettings, TelegramSettings
from coding_orchestrator.observability.telegram import (
    TelegramAlert,
    TelegramNotifier,
    TelegramWarning,
)
from coding_orchestrator.orchestrator.engine import WorkflowEngine
from coding_orchestrator.schemas import TaskSpec


def test_telegram_disabled_does_not_call_http(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def opener(request: Request, timeout: float) -> object:
        nonlocal called
        called = True
        return object()

    notifier = TelegramNotifier(
        TelegramSettings(enabled=False),
        BudgetSettings(project_id="p"),
        opener=opener,
    )

    assert notifier.send_alert(TelegramAlert(project_id="p", reason="blocked")) is None
    assert not called


def test_telegram_uses_env_and_does_not_expose_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setenv("BOT_TOKEN", "secret-token")
    monkeypatch.setenv("CHAT_ID", "123")

    def opener(request: Request, timeout: float) -> object:
        captured["url"] = request.full_url
        raw_data = request.data
        assert isinstance(raw_data, bytes)
        captured["body"] = json.loads(raw_data.decode("utf-8"))
        return object()

    notifier = TelegramNotifier(
        TelegramSettings(
            enabled=True,
            bot_token_env_var="BOT_TOKEN",
            chat_id_env_var="CHAT_ID",
        ),
        BudgetSettings(project_id="project"),
        opener=opener,
    )

    warning = notifier.send_alert(
        TelegramAlert(
            project_id="project",
            reason="blocked",
            task_id="T-1",
            estimated_cost_spent=0.1,
            budget_remaining=0.9,
            last_error_summary="failed",
            recommended_next_action="review",
        )
    )

    assert warning is None
    assert "secret-token" in captured["url"]
    assert "secret-token" not in captured["body"]["text"]
    assert "Project: project" in captured["body"]["text"]
    assert captured["body"]["chat_id"] == "123"


def test_telegram_missing_env_warn_or_fail() -> None:
    warn_notifier = TelegramNotifier(
        TelegramSettings(
            enabled=True,
            bot_token_env_var="MISSING_TOKEN",
            chat_id_env_var="MISSING_CHAT",
            missing_env_policy="warn",
        ),
        BudgetSettings(project_id="p"),
    )

    warning = warn_notifier.send_alert(TelegramAlert(project_id="p", reason="blocked"))

    assert warning is not None
    assert "MISSING_TOKEN" in warning

    fail_notifier = TelegramNotifier(
        TelegramSettings(
            enabled=True,
            bot_token_env_var="MISSING_TOKEN",
            chat_id_env_var="MISSING_CHAT",
            missing_env_policy="fail",
        ),
        BudgetSettings(project_id="p"),
    )
    with pytest.raises(TelegramWarning):
        fail_notifier.send_alert(TelegramAlert(project_id="p", reason="blocked"))


def test_engine_sends_blocked_alert(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    alerts: list[TelegramAlert] = []
    config = AppConfig(
        repo_path=str(tmp_path),
        state_path=str(tmp_path / "state.json"),
        log_path=str(tmp_path / "log.jsonl"),
        budget=BudgetSettings(
            ledger_path=str(tmp_path / "budget.sqlite"),
            project_id="telegram-tests",
            max_task_cost_usd=0.000001,
            project_total_budget_usd=10,
            cheap_builder_budget_usd=10,
        ),
        telegram=TelegramSettings(enabled=True),
    )
    engine = WorkflowEngine(config)
    monkeypatch.setattr(engine.telegram, "send_alert", lambda alert: alerts.append(alert))

    engine.run_task(TaskSpec(id="T-BLOCK", title="Fix bug", max_cost_usd=0.000001))

    assert alerts
    assert alerts[-1].reason in {"blocked", "budget_exhausted"}
    assert alerts[-1].project_id == "telegram-tests"

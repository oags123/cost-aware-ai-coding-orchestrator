from __future__ import annotations

from coding_orchestrator.models.base import ModelClient, ModelResponse


class CloudReviewerPlaceholder(ModelClient):
    def __init__(self, name: str = "codex-reviewer-placeholder") -> None:
        self.name = name

    def complete(self, prompt: str) -> ModelResponse:
        text = f"# Escalation placeholder for {self.name}\n# Review package length: {len(prompt)}"
        return ModelResponse(
            text=text,
            confidence=0.5,
            estimated_output_tokens=256,
        )

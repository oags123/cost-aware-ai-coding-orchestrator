from __future__ import annotations

from coding_orchestrator.models.base import ModelClient, ModelResponse


class LocalModelPlaceholder(ModelClient):
    def __init__(self, name: str = "local-builder-placeholder") -> None:
        self.name = name

    def complete(self, prompt: str) -> ModelResponse:
        return ModelResponse(
            text=f"# Placeholder bounded response from {self.name}\n# Prompt length: {len(prompt)}",
            confidence=0.65,
            estimated_output_tokens=128,
        )

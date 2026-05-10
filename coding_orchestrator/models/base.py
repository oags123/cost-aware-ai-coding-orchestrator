from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelResponse:
    text: str
    confidence: float
    estimated_output_tokens: int


class ModelClient(ABC):
    name: str

    @abstractmethod
    def complete(self, prompt: str) -> ModelResponse:
        """Return bounded model output."""


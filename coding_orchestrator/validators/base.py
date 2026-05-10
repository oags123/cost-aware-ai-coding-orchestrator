from __future__ import annotations

from abc import ABC, abstractmethod

from coding_orchestrator.schemas import ValidationResult


class Validator(ABC):
    name: str

    @abstractmethod
    def validate(self) -> ValidationResult:
        """Run validation and return a structured result."""


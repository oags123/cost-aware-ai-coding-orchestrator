from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from coding_orchestrator.config import ResolvedModelRole, ServiceTier


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class StructuredOutputError(ProviderError):
    pass


class ProviderTransientError(ProviderError):
    """Raised for retryable provider failures (rate limits, timeouts, connection errors)."""


class FlexUnavailableError(ProviderError):
    """Raised when bounded Flex-only retries are exhausted without a successful call.

    Never triggers a switch to another service tier -- the caller must stop and report
    an accurate "flex_unavailable" outcome, not silently escalate to a higher-priced
    tier.
    """


class ServiceTierMismatchError(ProviderError):
    """Raised when a call requested as Flex is reported back by the provider as having
    run on a different service tier. Under the strict Flex-only policy this must never
    be treated as a normal successful Flex call, even if the response is otherwise
    usable -- the discrepancy is recorded and the task is blocked conservatively.
    """


class BuilderOutput(BaseModel):
    patch: str
    touched_files: list[str] = Field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    assumptions: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class ModelUsage(BaseModel):
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float | None = None


class ProviderRequest(BaseModel):
    role: ResolvedModelRole
    prompt: str
    system_prompt: str | None = None
    response_schema_name: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ProviderResponse(BaseModel):
    text: str
    structured_output: BuilderOutput | dict[str, Any] | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    provider: str
    model: str
    service_tier: ServiceTier
    confidence: float = 0.0


class ModelProvider(ABC):
    provider_name: str

    @abstractmethod
    def generate(self, request: ProviderRequest) -> ProviderResponse:
        """Return bounded model output without executing model-supplied commands."""

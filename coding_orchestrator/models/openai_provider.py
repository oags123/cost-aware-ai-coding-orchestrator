from __future__ import annotations

import json
import os
from typing import Any, cast

from coding_orchestrator.config import OpenAIProviderSettings, ServiceTier
from coding_orchestrator.models.provider import (
    BuilderOutput,
    ModelProvider,
    ModelUsage,
    ProviderConfigurationError,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderTransientError,
    StructuredOutputError,
)


class OpenAIProvider(ModelProvider):
    provider_name = "openai"

    def __init__(self, settings: OpenAIProviderSettings | None = None) -> None:
        self.settings = settings or OpenAIProviderSettings()

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not self.settings.enabled:
            raise ProviderConfigurationError("OpenAI provider is disabled")
        if not self.settings.runtime_enabled:
            raise ProviderConfigurationError(
                "OpenAI provider runtime calls are disabled by config "
                "(providers.openai.runtime_enabled=false)"
            )
        if not os.getenv(self.settings.api_key_env_var):
            raise ProviderConfigurationError(
                f"OpenAI API key environment variable is not set: {self.settings.api_key_env_var}"
            )
        try:
            import openai
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderConfigurationError(
                "OpenAI Python SDK is not installed. Install the `openai` package to enable "
                "providers.openai.runtime_enabled=true."
            ) from exc

        client = OpenAI(
            api_key=os.getenv(self.settings.api_key_env_var),
            base_url=self.settings.base_url,
            max_retries=self.settings.max_retries,
            timeout=self.settings.request_timeout_seconds,
        )
        reasoning = (
            {"effort": request.role.reasoning_effort}
            if request.role.reasoning_effort in {"none", "low", "medium", "high", "xhigh"}
            else None
        )
        try:
            # The SDK's TypedDict params (`text`, `reasoning`) don't structurally match
            # our dynamically-built dicts under mypy even though they're valid at runtime.
            api_response = client.responses.create(  # type: ignore[call-overload]
                model=request.role.model,
                input=request.prompt,
                instructions=request.system_prompt,
                max_output_tokens=request.role.max_output_tokens,
                text={"verbosity": request.role.verbosity},
                reasoning=reasoning,
                tools=[],
                store=False,
                service_tier=request.role.service_tier,
                metadata=request.metadata,
            )
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
            openai.NotFoundError,
        ) as exc:
            raise ProviderConfigurationError(
                f"OpenAI provider configuration rejected by API: {exc}"
            ) from exc
        except (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
            openai.ConflictError,
        ) as exc:
            raise ProviderTransientError(f"OpenAI transient error: {exc}") from exc
        except openai.OpenAIError as exc:
            raise ProviderError(f"OpenAI API error: {exc}") from exc
        text = cast(str, getattr(api_response, "output_text", "") or "")
        structured: BuilderOutput | dict[str, Any] | None = None
        is_builder_json = (
            request.response_schema_name == "builder_patch_contract"
            and text.strip().startswith("{")
        )
        if is_builder_json:
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError as exc:
                raise StructuredOutputError(
                    f"invalid JSON builder output from OpenAI: {exc}"
                ) from exc
            if isinstance(candidate, dict):
                try:
                    structured = BuilderOutput.model_validate(candidate)
                except Exception as exc:
                    raise StructuredOutputError(
                        f"builder JSON output failed schema validation: {exc}"
                    ) from exc
            else:
                raise StructuredOutputError(
                    "builder JSON output must be a JSON object matching the builder patch contract"
                )

        usage_data = getattr(api_response, "usage", None)
        usage = ModelUsage(
            input_tokens=int(getattr(usage_data, "input_tokens", 0) or 0),
            cached_input_tokens=int(
                getattr(getattr(usage_data, "input_tokens_details", None), "cached_tokens", 0) or 0
            ),
            output_tokens=int(getattr(usage_data, "output_tokens", 0) or 0),
            reasoning_tokens=int(
                getattr(
                    getattr(usage_data, "output_tokens_details", None),
                    "reasoning_tokens",
                    0,
                )
                or 0
            ),
        )
        service_tier = getattr(api_response, "service_tier", request.role.service_tier)
        if service_tier not in {"default", "flex", "priority", "batch"}:
            service_tier = request.role.service_tier

        return ProviderResponse(
            text=text,
            structured_output=structured,
            usage=usage,
            provider=self.provider_name,
            model=request.role.model,
            service_tier=cast(ServiceTier, service_tier),
            confidence=0.0,
        )

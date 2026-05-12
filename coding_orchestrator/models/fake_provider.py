from __future__ import annotations

from collections.abc import Iterable

from coding_orchestrator.models.provider import (
    BuilderOutput,
    ModelProvider,
    ModelUsage,
    ProviderRequest,
    ProviderResponse,
)


class FakeModelProvider(ModelProvider):
    provider_name = "fake"

    def __init__(self, responses: Iterable[ProviderResponse | BuilderOutput | str] = ()) -> None:
        self._responses = list(responses)
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        next_response = self._responses.pop(0) if self._responses else self._default_output()
        if isinstance(next_response, ProviderResponse):
            return next_response
        if isinstance(next_response, BuilderOutput):
            return ProviderResponse(
                text=next_response.model_dump_json(),
                structured_output=next_response,
                usage=ModelUsage(
                    input_tokens=max(1, len(request.prompt) // 4),
                    output_tokens=max(1, len(next_response.patch) // 4),
                ),
                provider=request.role.provider,
                model=request.role.model,
                service_tier=request.role.service_tier,
                confidence=next_response.confidence,
            )
        return ProviderResponse(
            text=next_response,
            usage=ModelUsage(
                input_tokens=max(1, len(request.prompt) // 4),
                output_tokens=max(1, len(next_response) // 4),
            ),
            provider=request.role.provider,
            model=request.role.model,
            service_tier=request.role.service_tier,
            confidence=0.5,
        )

    def _default_output(self) -> BuilderOutput:
        return BuilderOutput(
            patch="",
            touched_files=[],
            summary="fake provider dry-run response",
            confidence=0.0,
            assumptions=["No fake response was configured."],
        )

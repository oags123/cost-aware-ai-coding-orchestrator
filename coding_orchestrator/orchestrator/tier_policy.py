from __future__ import annotations

from dataclasses import dataclass, field

from coding_orchestrator.config import BuilderServiceTierSettings


@dataclass
class TierPolicyState:
    calls_by_service_tier: dict[str, int] = field(default_factory=dict)
    service_tier_timeouts: dict[str, int] = field(default_factory=dict)
    consecutive_flex_transient_failures: int = 0
    flex_unavailable: bool = False


@dataclass
class BuilderServiceTierPolicy:
    """Strict Flex-only tier policy: automatic builder calls always request Flex.

    There is no fallback tier and no `activate_fallback()` concept -- on a transient
    Flex failure (timeout, rate limit, capacity), the caller gets a bounded number of
    Flex-only retries via `should_retry_flex()`. Once those are exhausted,
    `mark_flex_unavailable()` records that fact and the task must end with an accurate
    `flex_unavailable` status, never by silently switching to a higher-priced tier.
    """

    settings: BuilderServiceTierSettings
    state: TierPolicyState = field(default_factory=TierPolicyState)

    def select_tier(self) -> str:
        return self.settings.default_tier

    def timeout_seconds(self, tier: str, default_timeout_seconds: int) -> int:
        if tier == "flex":
            return self.settings.flex.max_attempt_runtime_seconds
        return default_timeout_seconds

    def record_call(self, tier: str) -> None:
        self.state.calls_by_service_tier[tier] = self.state.calls_by_service_tier.get(tier, 0) + 1

    def record_success(self, tier: str) -> None:
        self.state.consecutive_flex_transient_failures = 0

    def record_transient_failure(self, tier: str) -> None:
        self.state.service_tier_timeouts[tier] = self.state.service_tier_timeouts.get(tier, 0) + 1
        self.state.consecutive_flex_transient_failures += 1

    def should_retry_flex(self) -> bool:
        return self.state.consecutive_flex_transient_failures <= self.settings.flex.max_flex_retries

    def mark_flex_unavailable(self) -> None:
        self.state.flex_unavailable = True

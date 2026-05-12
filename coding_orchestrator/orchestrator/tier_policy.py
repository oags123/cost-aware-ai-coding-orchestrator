from __future__ import annotations

from dataclasses import dataclass, field

from coding_orchestrator.config import BuilderServiceTierSettings
from coding_orchestrator.orchestrator.budget import BudgetEstimate, BudgetExceeded


@dataclass
class TierPolicyState:
    calls_by_service_tier: dict[str, int] = field(default_factory=dict)
    service_tier_timeouts: dict[str, int] = field(default_factory=dict)
    consecutive_default_tier_timeouts: int = 0
    service_tier_fallbacks: int = 0
    fallback_cost_usd: float = 0.0


@dataclass
class BuilderServiceTierPolicy:
    settings: BuilderServiceTierSettings
    state: TierPolicyState = field(default_factory=TierPolicyState)
    fallback_active: bool = False

    def select_tier(self) -> str:
        if self.fallback_active:
            return self.settings.fallback_tier
        return self.settings.default_tier

    def timeout_seconds(self, tier: str, default_timeout_seconds: int) -> int:
        if tier == "flex":
            return self.settings.flex.max_attempt_runtime_seconds
        return default_timeout_seconds

    def record_call(self, tier: str) -> None:
        self.state.calls_by_service_tier[tier] = self.state.calls_by_service_tier.get(tier, 0) + 1

    def record_success(self, tier: str) -> None:
        if tier == self.settings.default_tier:
            self.state.consecutive_default_tier_timeouts = 0

    def record_timeout(self, tier: str) -> None:
        self.state.service_tier_timeouts[tier] = self.state.service_tier_timeouts.get(tier, 0) + 1
        if tier == self.settings.default_tier:
            self.state.consecutive_default_tier_timeouts += 1

    def should_fallback(self) -> bool:
        if self.settings.default_tier != "flex" or self.settings.fallback_tier != "standard":
            return False
        if (
            self.state.consecutive_default_tier_timeouts
            >= self.settings.flex.max_consecutive_timeouts
        ):
            return True
        flex_calls = self.state.calls_by_service_tier.get("flex", 0)
        if flex_calls <= 0:
            return False
        timeout_rate = self.state.service_tier_timeouts.get("flex", 0) / flex_calls
        return timeout_rate >= self.settings.flex.timeout_rate_threshold

    def check_fallback_budget(self, estimate: BudgetEstimate) -> None:
        if estimate.inference_tier != "standard":
            return
        if self.state.service_tier_fallbacks >= self.settings.max_standard_fallbacks_per_run:
            raise BudgetExceeded("service tier fallback limit exceeded")
        projected = self.state.fallback_cost_usd + estimate.estimated_total_cost_usd
        if projected > self.settings.max_standard_fallback_cost_usd_per_run:
            raise BudgetExceeded("service tier fallback cost budget exceeded")
        self.state.service_tier_fallbacks += 1
        self.state.fallback_cost_usd = projected

    def activate_fallback(self) -> None:
        self.fallback_active = True

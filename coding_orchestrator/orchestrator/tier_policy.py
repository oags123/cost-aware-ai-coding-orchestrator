from __future__ import annotations

from dataclasses import dataclass, field

from coding_orchestrator.config import CheapBuilderTierSettings
from coding_orchestrator.orchestrator.budget import BudgetEstimate, BudgetExceeded


@dataclass
class TierPolicyState:
    calls_by_tier: dict[str, int] = field(default_factory=dict)
    flex_timeouts: int = 0
    consecutive_flex_timeouts: int = 0
    standard_fallbacks: int = 0
    standard_fallback_cost_usd: float = 0.0


@dataclass
class CheapBuilderTierPolicy:
    settings: CheapBuilderTierSettings
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
        self.state.calls_by_tier[tier] = self.state.calls_by_tier.get(tier, 0) + 1

    def record_success(self, tier: str) -> None:
        if tier == "flex":
            self.state.consecutive_flex_timeouts = 0

    def record_flex_timeout(self) -> None:
        self.state.flex_timeouts += 1
        self.state.consecutive_flex_timeouts += 1

    def should_fallback_to_standard(self) -> bool:
        if self.settings.default_tier != "flex" or self.settings.fallback_tier != "standard":
            return False
        if self.state.consecutive_flex_timeouts >= self.settings.flex.max_consecutive_timeouts:
            return True
        flex_calls = self.state.calls_by_tier.get("flex", 0)
        if flex_calls <= 0:
            return False
        timeout_rate = self.state.flex_timeouts / flex_calls
        return timeout_rate >= self.settings.flex.timeout_rate_threshold

    def check_standard_fallback(self, estimate: BudgetEstimate) -> None:
        if estimate.inference_tier != "standard":
            return
        if self.state.standard_fallbacks >= self.settings.max_standard_fallbacks_per_run:
            raise BudgetExceeded("standard fallback limit exceeded")
        projected = self.state.standard_fallback_cost_usd + estimate.estimated_total_cost_usd
        if projected > self.settings.max_standard_fallback_cost_usd_per_run:
            raise BudgetExceeded("standard fallback cost budget exceeded")
        self.state.standard_fallbacks += 1
        self.state.standard_fallback_cost_usd = projected

    def activate_fallback(self) -> None:
        self.fallback_active = True

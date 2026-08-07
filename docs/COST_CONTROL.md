# Cost Control

## Core controls

- Pre-call budget estimate for each model call.
- Task/project/role budget gates before provider execution.
- SQLite budget ledger for all estimated/blocked calls, including reconciled actual
  token usage/cost and the requested vs. actual service tier for every call.
- Strict Flex-only routing for every automatically routed call (see below) --
  cost predictability is prioritized over latency.
- Bounded, Flex-only retries with convergence checks.

## Pricing defaults

Pricing is config-driven in `pricing.roles` with metadata:

- `source_url`
- `retrieved_or_verified_date`
- `input_usd_per_1m_tokens`
- `cached_input_usd_per_1m_tokens` (nullable)
- `output_usd_per_1m_tokens`
- optional long-context fields

No pricing is hardcoded in runtime business logic.

## Reasoning headroom

Reasoning tokens are billed as output and consume context. Reserve output and context headroom for diagnosis/refactor tasks.

## Service tier policy: Flex is mandatory

**Every automatically routed call requests OpenAI's `flex` service tier. There is no
automatic fallback to `default`, `priority`, `batch`, or `fast` -- ever.** This is
enforced as a real invariant, not merely a default:

- `AppConfig` validates at construction time (from YAML or in Python) that every
  automatically-routable role (`mechanical_worker`, `classification_worker`,
  `simple_builder`, `general_builder`, `coding_optimized_builder`) defaults to `flex`,
  declares no `fallback_service_tier`, and has a verified `{role}:flex` pricing entry.
  A config that violates this is rejected outright at load time.
- `WorkflowEngine._run_role_builder` requests `flex` on every attempt, with no
  tier-switching code path left in the engine at all.
- Flex is roughly **50% cheaper per token than Standard/Default** for supported
  models (see the pricing tables in `config.example.yaml`), at the cost of higher
  latency and occasionally reduced availability compared to Standard.

### What happens when Flex is unavailable

On a transient Flex error (timeout, rate limit, capacity), the engine retries a
bounded number of times (`inference.builder_service_tier.flex.max_flex_retries`,
default 2) -- **every retry still requests Flex**. If all bounded retries are
exhausted, the task ends with `final_status: "flex_unavailable"`, the repository is
left exactly as it was before the task started (via the same stash-based
checkpoint/rollback used for every other failure mode), and the validation message
explicitly states that no higher-priced tier was used. This is a pause, not an
automatic escalation to more expensive processing.

If the provider ever reports back a service tier other than what was requested (e.g.
Flex was requested but a different tier was actually used), the response is **not**
treated as a normal successful call: the discrepancy is recorded
(`tool_results.service_tier_mismatch`) and the task is blocked
(`final_status: "blocked"`) rather than silently accepted.

### Manual override (rare, explicit, never silent)

A small set of roles that are not automatically reachable (`frontier_coding_reviewer`,
which intentionally stays on `gpt-5.3-codex` -- a model that does not support Flex --
for its coding-specialized review quality; `emergency_pro_reviewer`, which is already
manual-approval-gated) are exempt from the automatic policy above. For any other
one-off use of a non-Flex tier, pass `--allow-non-flex-tier {default,priority,batch,fast}`
to the CLI (or `manual_service_tier_override=` to `WorkflowEngine` directly). This is
per-run, printed to stdout, and written to the JSONL log as
`manual_service_tier_override_active` -- it can never be enabled by config inheritance
or triggered by any fallback/retry logic.

### Verified Flex support

`gpt-5.3-codex` does **not** support Flex -- live-verified against the real OpenAI API
(2026-08-07): a `service_tier="flex"` request for this model is rejected with `"Flex
is not available for this model."` The `coding_optimized_builder` role, which
previously used codex, was retargeted to `gpt-5.4-mini` (Flex-capable, already used by
`simple_builder`/`general_builder`) so it stays reachable through automatic routing.
`frontier_coding_reviewer` intentionally keeps `gpt-5.3-codex` but is manual-override-only.

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

## Service tier policy: Flex is mandatory, globally, with no override

**No paid OpenAI request of any kind -- automatic builder, classification, diagnosis
reviewer, frontier reviewer, emergency reviewer, legacy/manual alias, or any future
direct-provider call -- may ever use a service tier other than `flex`. There is no
fallback and no override mechanism, silent or explicit.** This is enforced at two
independent layers, so no code path can bypass it:

1. **Config-load time** (`AppConfig._enforce_flex_only_policy`, a pydantic
   validator): every role in `model_roles.roles` must default to `flex`, declare no
   `fallback_service_tier`, and have a verified `{role}:flex` pricing entry --
   *unless* it's marked `live_calls_disabled=True` (reserved for roles whose model
   is verified to not support Flex; see below). A config violating this is rejected
   outright, whether loaded from YAML or constructed directly in Python/tests.
2. **The actual call boundary** (`OpenAIProvider.generate`): before touching the
   OpenAI SDK at all, the provider unconditionally refuses any request whose
   resolved role isn't `service_tier="flex"`, and unconditionally refuses any
   `live_calls_disabled` role. This is checked first, before even the
   enabled/runtime-enabled/API-key checks -- there is no parameter, override, or
   code path (automatic routing, manual role selection, diagnosis, retries, direct
   provider use) that can reach a real API call at a non-Flex tier.

Flex is roughly **50% cheaper per token than Standard/Default** for supported models
(see the pricing tables in `config.example.yaml`), at the cost of higher latency and
occasionally reduced availability compared to Standard.

### What happens when Flex is unavailable

On a transient Flex error (timeout, rate limit, capacity), the engine retries a
bounded number of times (`inference.builder_service_tier.flex.max_flex_retries`,
default 2) -- **every retry still requests Flex; the model and tier never change**.
If all bounded retries are exhausted, the task ends with
`final_status: "flex_unavailable"`, the repository is left exactly as it was before
the task started (via the same stash-based checkpoint/rollback used for every other
failure mode), and the validation message explicitly states that no higher-priced
tier was used. This is a pause, not an automatic escalation to more expensive
processing.

If the provider ever reports back a service tier other than what was requested (e.g.
Flex was requested but a different tier was actually used), the response is **not**
treated as a normal successful call: no output is applied, the repository is rolled
back, the discrepancy (requested vs. actual tier) is recorded
(`tool_results.service_tier_mismatch`), and the task is blocked
(`final_status: "blocked"`) rather than silently accepted or marked completed.

### Roles whose model does not support Flex

Two models were live-verified (2026-08-07, real OpenAI API) to reject
`service_tier="flex"`:

- **`gpt-5.3-codex`** -- rejected with `"Flex is not available for this model."`
  `coding_optimized_builder`, which previously used codex, was retargeted to
  `gpt-5` (Flex-capable) so it stays live-callable. `frontier_coding_reviewer`
  intentionally keeps codex for its coding-specialized review quality but is
  `live_calls_disabled=True` -- analysis/configuration-only, can never make a real
  call, and there is no override to force it to.
- **`gpt-4.1`** -- rejected with `"Invalid service_tier argument."`
  `non_reasoning_instruction_follower` keeps gpt-4.1 (the role exists specifically
  for its non-reasoning behavior, with no equivalent Flex-capable substitute) but is
  likewise `live_calls_disabled=True`.

Every other model in the registry (`gpt-5-nano`, `gpt-5-mini`, `gpt-5`) was
live-verified Flex-capable and every role using them defaults to `flex`.

### Three-model simplification (2026-08-07)

Automatic and reviewer routing was simplified to exactly three Flex-capable models
-- `gpt-5-nano`, `gpt-5-mini`, and `gpt-5` -- replacing the previous
`gpt-5.4-nano`/`gpt-5.4-mini`/`gpt-5.4`/`gpt-5.5`/`gpt-5.5-pro` spread, following a
benchmark showing comparable reliability at a lower cost per completed task. The
primary metric was **actual cost per successfully completed task, not price per
token**: across 7 representative scenarios (classification, explain-code, one-file
and two-file bug fixes, a multi-bug patch, and a forced-failure/rollback case), both
model sets reached 4/6 first-attempt success on the real (non-forced-failure)
scenarios, sharing the one failure (an LLM hunk-header line-count mismatch,
independent of model choice), while the new 3-model set cost roughly 2.3x less per
success ($0.000094 vs $0.0002148). Total benchmark spend was ~$0.0033 against a
$0.05 cap. See [Operational Hardening Changes](OPERATIONAL_HARDENING_CHANGES.md) for
the full numbers.

The same benchmark also found that `reasoning_effort="none"` (`classification_worker`'s
previous value) is rejected by the real API for every gpt-5-family model tested --
only `minimal`/`low`/`medium`/`high` are accepted server-side. `classification_worker`
now uses `low`.

### Escalation beyond nano/mini goes to a ChatGPT subscription, not a pricier API model (2026-08-10)

Automatic routing was never able to reach `coding_optimized_builder` or any
`frontier_*`/gpt-5-tier role (see [Model Roles](MODEL_ROLES.md)), and that remains
true. What changed is what happens when nano/mini genuinely can't make further
economical progress: instead of hoping a future automatic escalation to a pricier
OpenAI API model would help, the engine now writes a local, zero-cost **handoff**
artifact (`handoff.*` config, `logs/handoffs/`, `coding-orchestrator handoff`) on
non-convergence, budget/limit blocks, Flex unavailability, and retry exhaustion.
The intended escalation path for those cases is a human reviewing/uploading that
artifact and asking a ChatGPT subscription app for stronger reasoning -- a flat,
already-paid-for cost -- rather than the orchestrator spending more against the
metered OpenAI API. See [ChatGPT Handoff Workflow](CHATGPT_HANDOFF_WORKFLOW.md)
for the full loop. `diagnosis.model_role` was also retargeted from
`frontier_reviewer` to `general_builder` so that even the (still non-functional,
dry-run-only) internal diagnosis path's cost estimation stays priced against a
nano/mini-tier role, never a gpt-5-tier one.

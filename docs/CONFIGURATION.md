# Configuration

Main config file: `config.yaml` (example in `config.example.yaml`).

## Core sections

- `providers`: provider enablement and runtime API settings.
- `model_aliases`: alias -> concrete model id mapping.
- `model_roles`: capability roles with limits/reasoning/service tier defaults.
- `pricing.roles`: per-role and per-service-tier pricing metadata.
- `budget`: project/task/role budgets and ledger path.
- `limits`: hard token/context/output/patch and stream caps.
- `inference.builder_service_tier`: bounded Flex-only retry policy (no fallback tier).
- `policies`: frontier patching policy and approval gates.

## OpenAI runtime

- `providers.openai.runtime_enabled` controls real API calls.
- API key is read only from `OPENAI_API_KEY` (or configured env var).

## Service tiers: Flex is mandatory, not a preference

Every automatically routed call requests OpenAI's `flex` tier. This is validated at
config load time -- `AppConfig` rejects any configuration where an
automatically-routable role (`mechanical_worker`, `classification_worker`,
`simple_builder`, `general_builder`, `coding_optimized_builder`) doesn't default to
`flex`, declares a `fallback_service_tier`, or lacks a verified `{role}:flex` pricing
entry. There is no automatic escalation to `default`/`priority`/`batch`/`fast` under
any circumstance; see `docs/COST_CONTROL.md` for the full policy, the bounded-retry
behavior when Flex is unavailable, and the explicit `--allow-non-flex-tier` manual
override.

`inference.builder_service_tier.flex.max_flex_retries` (default `2`) bounds how many
times a transient Flex failure is retried -- every retry still requests Flex.

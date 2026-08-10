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
- `handoff`: local, zero-cost artifact written when a task stops without completing,
  intended for escalation to a ChatGPT subscription app instead of a pricier OpenAI
  API model -- see [ChatGPT Handoff Workflow](CHATGPT_HANDOFF_WORKFLOW.md).

## OpenAI runtime

- `providers.openai.runtime_enabled` controls real API calls.
- API key is read only from `OPENAI_API_KEY` (or configured env var).

## Service tiers: Flex is mandatory for every live request, no exceptions

Every role that can make a real (paid) OpenAI call -- automatic builders,
classification, diagnosis reviewers, frontier reviewers, emergency reviewers, and
legacy/manual aliases alike -- requests OpenAI's `flex` tier. This is enforced twice:

- At config load time: `AppConfig` rejects any configuration where a live-callable
  role (anything without `live_calls_disabled: true`) doesn't default to `flex`,
  declares a `fallback_service_tier`, or lacks a verified `{role}:flex` pricing entry.
- At the actual call boundary: `OpenAIProvider.generate()` refuses unconditionally,
  before any API interaction, if the resolved role isn't `flex` or is
  `live_calls_disabled`. There is no CLI flag, constructor parameter, or config
  setting that can force a non-Flex live call -- see `docs/COST_CONTROL.md` for the
  full policy and which two models (`gpt-5.3-codex`, `gpt-4.1`) don't support Flex
  and are therefore `live_calls_disabled` instead.

`inference.builder_service_tier.flex.max_flex_retries` (default `2`) bounds how many
times a transient Flex failure is retried -- every retry still requests Flex, and the
model/role never changes.

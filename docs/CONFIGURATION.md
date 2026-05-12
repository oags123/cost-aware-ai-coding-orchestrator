# Configuration

Main config file: `config.yaml` (example in `config.example.yaml`).

## Core sections

- `providers`: provider enablement and runtime API settings.
- `model_aliases`: alias -> concrete model id mapping.
- `model_roles`: capability roles with limits/reasoning/service tier defaults.
- `pricing.roles`: per-role and per-service-tier pricing metadata.
- `budget`: project/task/role budgets and ledger path.
- `limits`: hard token/context/output/patch and stream caps.
- `inference.builder_service_tier`: flex/default fallback policy.
- `policies`: frontier patching policy and approval gates.

## OpenAI runtime

- `providers.openai.runtime_enabled` controls real API calls.
- API key is read only from `OPENAI_API_KEY` (or configured env var).

## Service tiers

- `flex` preferred for non-urgent builder work.
- `default` fallback for flex timeout/resource issues.
- `priority` disabled by default.

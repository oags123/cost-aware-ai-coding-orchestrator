# OpenAI Multimodel Refactor Plan

Status: updated for Phase 3 runtime cleanup.

## 1) Current architecture summary

- Python orchestrator controls classification, routing, patch workflow, validation, and rollback.
- Builder runtime backend is role/provider based.
- OpenAI provider is supported through Responses API path.
- Fake provider remains available for deterministic tests.

## 2) Legacy runtime references

- Legacy runtime references removed in Phase 3.
- Legacy setup docs removed.

## 3) Legacy tier assumptions

- Active runtime naming migrated to capability-role naming.
- Remaining cost controls are role/service-tier based.

## 4) New architecture

- `models/provider.py`: provider contract.
- `models/openai_provider.py`: OpenAI implementation.
- `models/router.py`: complexity/risk model routing.
- `orchestrator/engine.py`: role resolution and bounded execution.

## 5) Config schema

- `schema_version: 3`
- `model_aliases`, `model_roles`, `pricing.roles`, `budget.role_budgets_usd`
- `inference.builder_service_tier` for flex/default fallback policy.

## 6) Model role definitions

| Role | Model | Strengths | Weaknesses | Reasoning | Tier |
| --- | --- | --- | --- | --- | --- |
| `mechanical_worker` | `gpt-5.4-nano` | extraction, tiny deterministic edits | weak ambiguity handling | none/low | flex |
| `classification_worker` | `gpt-5-nano` | lowest-cost summarization/classification | not for patching | none/low | flex/default |
| `simple_builder` | `gpt-5.4-mini` | small local patches | not deep architecture | low | flex |
| `general_builder` | `gpt-5.4-mini` | normal implementation/refactors | not best for hardest blockers | low/medium | flex/default |
| `coding_optimized_builder` | `gpt-5.3-codex` | coding-optimized multi-file work | higher cost than mini | medium | default |
| `frontier_coding_reviewer` | `gpt-5.3-codex` | stubborn coding diagnosis | diagnosis-first | high | default |
| `frontier_balanced_reviewer` | `gpt-5.4` | architecture-lite and large context | less strong than 5.5 | medium/high | default |
| `frontier_reviewer` | `gpt-5.5` | architecture and hard diagnosis | high cost | medium/high | default |
| `emergency_pro_reviewer` | `gpt-5.5-pro` | hardest blockers | manual approval only | high | default/batch |
| `legacy_reasoning_fallback` | `gpt-5` | compatibility fallback | not default | low/medium | default |
| `non_reasoning_instruction_follower` | `gpt-4.1` | deterministic fallback | weak for complex coding | none | default |

Note: there is no confirmed official OpenAI `micro` model in this plan. `simple_builder` is a role mapped to available models.

Role split note:

- `mechanical_worker` remains the active routed nano role for tiny deterministic coding and bounded patch work.
- `classification_worker` is a canonical/manual role for classification and summarization workloads and is not currently auto-selected by the router.
- `ultra_cheap_classifier` and `openai_ultra_cheap_legacy` remain backward-compatible aliases only.

## 7) Routing rules

- Start smallest role likely to pass validation.
- Prefer nano-class only for deterministic bounded tasks with narrow file scope.
- Default implementation role is mini-class.
- Use coding-optimized model for stubborn coding-heavy integration tasks.

## 8) Escalation rules

`mechanical/simple -> general -> frontier diagnosis -> guided general retry -> human`

Frontier direct patching remains disabled by default:

`allow_frontier_direct_patch: false`

## 9) Budget and pricing changes

- Pricing is config-driven, not hardcoded in business logic.
- `pricing.roles` includes service-tier entries and source metadata.
- Cached-input `null` is represented explicitly when unavailable.

## 10) Validation and rollback preservation

- Patch contract, file boundary checks, and `git apply --check` preserved.
- Validators run post-apply.
- Checkpoint rollback remains mandatory on failure/timeout/block.

## 11) Documentation update plan

- Active docs now describe pure Python + OpenAI role-provider architecture.
- Removed legacy setup docs.

## 12) Test plan

- Keep fake provider as default test path.
- No real network calls in unit tests.
- Coverage includes role selection, service-tier fallback, patch safety, rollback, and budget ledger.

## 13) Implementation phases

- Phase 1: schemas/config roles and pricing.
- Phase 2: provider path integration.
- Phase 2.5: model catalog and pricing defaults.
- Phase 3: runtime/docs cleanup and legacy-runtime removal.

## 14) Risks / blockers

- Large naming migration can cause broad fixture/test updates.
- Provider-tier fallback behavior depends on stable transient error classification.
- Model availability is account-dependent; defaults remain configurable.

## 15) Open questions

- None currently blocking Phase 3 completion.

# Model Roles

Capability roles are config-driven. Reasoning is request-level (`reasoning_effort`), not a separate model id.

**Every role that can make a live (paid) call requests Flex, with no exceptions and no
override mechanism of any kind.** The only alternative is `live_calls_disabled: true`,
reserved for the two models verified to not support Flex -- see
[Cost Control](COST_CONTROL.md) for the full policy, enforced both at config load time
and at the actual provider call boundary. "Auto-routed" below means
`WorkflowEngine._select_builder_role` can select this role without any manual
intervention; other live-enabled roles are reachable only via diagnosis/emergency
escalation paths (currently dry-run/manual-approval-gated) or direct role selection.

| Role | Default Model | Default Reasoning | Tier | Live-Callable | Auto-Routed | Direct Patch |
| --- | --- | --- | --- | --- | --- | --- |
| `mechanical_worker` | `gpt-5.4-nano` | `low` | `flex` | yes | yes | bounded tiny patches only |
| `classification_worker` | `gpt-5-nano` | `none` | `flex` | yes | no (reserved) | no |
| `simple_builder` | `gpt-5.4-mini` | `low` | `flex` | yes | yes | yes |
| `general_builder` | `gpt-5.4-mini` | `low` | `flex` | yes | yes | yes |
| `coding_optimized_builder` | `gpt-5.4-mini`\* | `medium` | `flex` | yes | no (not yet wired) | yes |
| `frontier_coding_reviewer` | `gpt-5.3-codex`\*\* | `high` | `default` | **no, disabled** | no | no |
| `frontier_balanced_reviewer` | `gpt-5.4` | `medium` | `flex` | yes | no (diagnosis, dry-run only) | no |
| `frontier_reviewer` | `gpt-5.5` | `medium` | `flex` | yes | no (diagnosis, dry-run only) | no |
| `emergency_pro_reviewer` | `gpt-5.5-pro` | `high` | `flex` | yes | no, manual approval required | no |
| `legacy_reasoning_fallback` | `gpt-5` | `medium` | `flex` | yes | no, manual selection only | compatibility fallback |
| `mini_legacy_fallback` | `gpt-5-mini` | `low` | `flex` | yes | no, manual selection only | compatibility fallback |
| `non_reasoning_instruction_follower` | `gpt-4.1`\*\*\* | `none` | `default` | **no, disabled** | no | no |

All "Tier: flex" rows above are live-verified Flex-capable against the real OpenAI API
(2026-08-07).

\* Retargeted from `gpt-5.3-codex`, which does not support Flex (live-verified: a Flex
request for this model is rejected with `"Flex is not available for this model."`).

\*\* `live_calls_disabled: true`. Intentionally kept on codex for its
coding-specialized review quality despite no Flex support. This role is
analysis/configuration-only: `OpenAIProvider.generate()` refuses to call it
unconditionally, and there is no override that can change that.

\*\*\* `live_calls_disabled: true`. gpt-4.1 does not support Flex (live-verified:
`"Invalid service_tier argument"`), and this role exists specifically for gpt-4.1's
non-reasoning behavior with no Flex-capable substitute, so it is
analysis/configuration-only rather than retargeted.

`mechanical_worker` remains the active routed nano role for tiny deterministic coding and bounded patch work. `classification_worker` is a canonical classification/summarization role, but it is currently manual/reserved unless selected explicitly by config or policy.

Legacy names are accepted for backward compatibility only:

- `ultra_cheap_classifier` -> `classification_worker`
- `openai_ultra_cheap_legacy` -> `openai_classifier_nano`

## Routing matrix

| Task profile | Primary role |
| --- | --- |
| tiny deterministic coding or bounded patch | `mechanical_worker` |
| manual classification/summarization workload | `classification_worker` |
| tiny bounded validated patch | `mechanical_worker` then escalate quickly |
| small local Python patch | `simple_builder` |
| normal implementation | `general_builder` |
| coding-heavy integration | `coding_optimized_builder` |
| stubborn failures requiring diagnosis | `frontier_coding_reviewer` diagnosis |
| architecture/planning/high ambiguity | `frontier_reviewer` diagnosis |
| repeated hard blocker | `emergency_pro_reviewer` (manual approval only) |

## Escalation policy

`mechanical_worker/simple_builder -> general_builder -> frontier diagnosis -> guided general_builder retry -> human escalation`

# Model Roles

Capability roles are config-driven. Reasoning is request-level (`reasoning_effort`), not a separate model id.

| Role | Default Model | Default Reasoning | Default Tier | Direct Patch |
| --- | --- | --- | --- | --- |
| `mechanical_worker` | `gpt-5.4-nano` | `low` | `flex` | bounded tiny patches only |
| `classification_worker` | `gpt-5-nano` | `none` | `flex` | no |
| `simple_builder` | `gpt-5.4-mini` | `low` | `flex` | yes |
| `general_builder` | `gpt-5.4-mini` | `low` | `flex` | yes |
| `coding_optimized_builder` | `gpt-5.3-codex` | `medium` | `default` | yes |
| `frontier_coding_reviewer` | `gpt-5.3-codex` | `high` | `default` | no |
| `frontier_balanced_reviewer` | `gpt-5.4` | `medium` | `default` | no |
| `frontier_reviewer` | `gpt-5.5` | `medium` | `default` | no |
| `emergency_pro_reviewer` | `gpt-5.5-pro` | `high` | `default` | no, manual approval required |
| `legacy_reasoning_fallback` | `gpt-5` | `medium` | `default` | compatibility fallback |
| `non_reasoning_instruction_follower` | `gpt-4.1` | `none` | `default` | fallback only |

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

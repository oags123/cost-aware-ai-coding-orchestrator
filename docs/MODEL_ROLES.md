# Model Roles

Capability roles are config-driven. Reasoning is request-level (`reasoning_effort`), not a separate model id.

Every automatically routed role runs on Flex only, enforced by a config-load-time
validator -- see [Cost Control](COST_CONTROL.md) for the full policy. "Auto-routed"
below means `WorkflowEngine._select_builder_role` can select this role without any
manual override.

| Role | Default Model | Default Reasoning | Default Tier | Auto-Routed | Direct Patch |
| --- | --- | --- | --- | --- | --- |
| `mechanical_worker` | `gpt-5.4-nano` | `low` | `flex` | yes | bounded tiny patches only |
| `classification_worker` | `gpt-5-nano` | `none` | `flex` | no (reserved) | no |
| `simple_builder` | `gpt-5.4-mini` | `low` | `flex` | yes | yes |
| `general_builder` | `gpt-5.4-mini` | `low` | `flex` | yes | yes |
| `coding_optimized_builder` | `gpt-5.4-mini`\* | `medium` | `flex` | no (not yet wired) | yes |
| `frontier_coding_reviewer` | `gpt-5.3-codex`\*\* | `high` | `default` | no, manual-override-only | no |
| `frontier_balanced_reviewer` | `gpt-5.4` | `medium` | `default` | no (diagnosis, dry-run only) | no |
| `frontier_reviewer` | `gpt-5.5` | `medium` | `default` | no (diagnosis, dry-run only) | no |
| `emergency_pro_reviewer` | `gpt-5.5-pro` | `high` | `default` | no, manual approval required | no |
| `legacy_reasoning_fallback` | `gpt-5` | `medium` | `default` | no, manual-override-only | compatibility fallback |
| `non_reasoning_instruction_follower` | `gpt-4.1` | `none` | `default` | no, manual-override-only | fallback only |

\* Retargeted from `gpt-5.3-codex`, which does not support Flex (live-verified against
the real API 2026-08-07: a Flex request for this model is rejected with `"Flex is not
available for this model."`).
\*\* Intentionally kept on codex for its coding-specialized review quality despite no
Flex support; never auto-routed, requires `--allow-non-flex-tier` if invoked for real.

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

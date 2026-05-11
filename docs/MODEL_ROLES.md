# Model Roles Specification

Status: Phase 2.5 catalog and routing defaults updated for OpenAI-first capability roles.

## Model Catalog

| Alias | Model ID | Purpose |
| --- | --- | --- |
| `openai_ultra_cheap_legacy` | `gpt-5-nano` | cheapest classification/summarization only |
| `openai_nano` | `gpt-5.4-nano` | default mechanical worker |
| `openai_mini_legacy` | `gpt-5-mini` | legacy mini fallback |
| `openai_mini` | `gpt-5.4-mini` | default simple/general builder |
| `openai_codex` | `gpt-5.3-codex` | coding-optimized builder/reviewer |
| `openai_frontier_balanced` | `gpt-5.4` | balanced frontier reviewer |
| `openai_frontier` | `gpt-5.5` | main frontier reviewer |
| `openai_frontier_pro` | `gpt-5.5-pro` | manual approval emergency reviewer |
| `openai_legacy_reasoning` | `gpt-5` | compatibility fallback only |
| `openai_non_reasoning` | `gpt-4.1` | deterministic non-reasoning fallback |

Thinking is request-level configuration (`reasoning_effort`), not a separate model ID.
`gpt-5.3-codex` with `medium` and `high` reasoning uses the same model ID.

## Role Mapping

| Role | Default alias/model | Reasoning | Tier policy |
| --- | --- | --- | --- |
| `mechanical_worker` | `openai_nano` / `gpt-5.4-nano` | `low` | `flex` then `default` |
| `ultra_cheap_classifier` | `openai_ultra_cheap_legacy` / `gpt-5-nano` | `none` | `flex` then `default` |
| `simple_builder` | `openai_mini` / `gpt-5.4-mini` | `low` | `flex` then `default` |
| `general_builder` | `openai_mini` / `gpt-5.4-mini` | `low` (raise to `medium` per request) | `flex` then `default` |
| `coding_optimized_builder` | `openai_codex` / `gpt-5.3-codex` | `medium` | `default` |
| `frontier_coding_reviewer` | `openai_codex` / `gpt-5.3-codex` | `high` | `default` |
| `frontier_balanced_reviewer` | `openai_frontier_balanced` / `gpt-5.4` | `medium`/`high` | `default` |
| `frontier_reviewer` | `openai_frontier` / `gpt-5.5` | `medium` by default | `default` |
| `emergency_pro_reviewer` | `openai_frontier_pro` / `gpt-5.5-pro` | `high` | manual approval only |
| `legacy_reasoning_fallback` | `openai_legacy_reasoning` / `gpt-5` | `low`/`medium` | `default` |
| `non_reasoning_instruction_follower` | `openai_non_reasoning` / `gpt-4.1` | `none` | `default` |

## Routing Matrix

- tiny deterministic extraction: `mechanical_worker` (`gpt-5.4-nano`, `none/low`, `flex`)
- tiny validated patch: `mechanical_worker`, escalate quickly on validation failure
- small local patch: `simple_builder` (`gpt-5.4-mini`, `low`, `flex`)
- normal implementation: `general_builder` (`gpt-5.4-mini`, `low/medium`, `flex/default`)
- coding-heavy integration: `coding_optimized_builder` (`gpt-5.3-codex`, `medium`, `default`)
- stubborn test failures: `frontier_coding_reviewer` diagnosis, then builder applies fix
- architecture/planning: `frontier_reviewer` (`gpt-5.5`, `medium/high`, `default`)
- repeated hard blocker: `emergency_pro_reviewer` (`gpt-5.5-pro`) with manual approval
- deterministic no-reasoning fallback: `non_reasoning_instruction_follower` (`gpt-4.1`)

## Guardrails

- `allow_frontier_direct_patch` defaults to `false`.
- `allow_xhigh_reasoning` defaults to `false`.
- `allow_emergency_pro_reviewer` defaults to `false`.
- Model output still cannot execute shell commands directly.

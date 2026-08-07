# Cost-Aware AI Coding Orchestrator

Local Python orchestrator for bounded coding workflows with strict safety gates.

## What It Does

- Classifies tasks and routes them to capability roles.
- Calls model providers through a typed provider interface.
- Accepts only unified diff or structured JSON patch output.
- Applies patches only after boundary and `git apply --check` validation.
- Runs deterministic validators (`ruff`, `mypy`, `pytest`) after patch apply.
- Rolls back to git checkpoint on failure.
- Enforces bounded retries, runtime, context, output, and cost.
- Persists state/logs and budget ledger locally.

## Runtime Architecture

- Backend: `role_provider` (primary and only runtime backend).
- Provider support today: OpenAI (opt-in), fake provider for tests/dry runs.
- No model-generated shell execution.
- Shell commands run only via deterministic subprocess wrappers with allowlists/timeouts.

## Quick Start

1. `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
   (for exact, reproducible dependency versions, also run
   `.venv/bin/pip install -r requirements-lock.txt`)
2. Copy `config.example.yaml` to `config.yaml`.
3. For fake-provider/no-network local runs, keep `providers.openai.runtime_enabled: false`
   (the default). Tasks will report `dry_run`, not `completed` — see "Task Outcomes" below.
4. For real OpenAI calls, export `OPENAI_API_KEY` and set `providers.openai.runtime_enabled: true`.
5. Run:
   - `.venv/bin/coding-orchestrator run --task tasks/example_task.md`
   - `.venv/bin/coding-orchestrator report`
   - (equivalently: `python -m coding_orchestrator.app run --task tasks/example_task.md`)

## Task Outcomes

A task's `final_status` is one of: `completed`, `dry_run`, `no_change`, `blocked`,
`escalated`, `failed`, `timeout`, `flex_unavailable`, or `skipped`. Only `completed` means
a real model call produced a validated, committed change. In particular:

- `dry_run` — the provider was disabled, misconfigured, or missing credentials; no model
  was called and nothing changed. This used to be silently reported as `completed`; it no
  longer is.
- `no_change` — the provider was called but produced no patch (or an empty one) for a task
  whose workflow requires a modification (`explain_code`/`architecture_review`/
  `security_review` are exempt, since they're not expected to change files).
- `blocked` — budget, limit, human-approval, or concurrent-execution-lock gate tripped
  before/without ever calling a model. Also used when a provider returns a service tier
  other than what was requested (see "Service Tier Policy").
- `flex_unavailable` — Flex capacity was requested and, after bounded Flex-only retries,
  never succeeded. No higher-priced tier was used automatically; the repository is left
  exactly as it was before the task started. See "Service Tier Policy" below.

The CLI's exit code reflects this: `run`/`run-all` exit non-zero unless every task actually
`completed` (or was legitimately `skipped`).

## Role Defaults

Every role that can make a live call runs on Flex only -- see "Service Tier Policy"
below for what that means and why.

Automatic and reviewer routing was simplified 2026-08-07 to exactly three
Flex-capable OpenAI models -- `gpt-5-nano`, `gpt-5-mini`, and `gpt-5` -- after a
benchmark across 7 representative task scenarios showed comparable reliability at a
lower cost per completed task than the previous 5-model spread
(`gpt-5.4-nano`/`gpt-5.4-mini`/`gpt-5.4`/`gpt-5.5`/`gpt-5.5-pro`). See
[Operational Hardening Changes](docs/OPERATIONAL_HARDENING_CHANGES.md) for the full
benchmark writeup.

- `mechanical_worker` -> `gpt-5-nano` (`flex`, reasoning `low`)
- `classification_worker` -> `gpt-5-nano` (`flex`, reasoning `low`, no patch)
- `simple_builder` -> `gpt-5-mini` (`flex`, reasoning `low`)
- `general_builder` -> `gpt-5-mini` (`flex`, reasoning `medium`)
- `coding_optimized_builder` -> `gpt-5` (`flex`, reasoning `medium`; retargeted
  from `gpt-5.3-codex`, which does not support Flex)
- `frontier_balanced_reviewer` -> `gpt-5` (`flex`, reasoning `high`, diagnosis-first,
  dry-run only today)
- `frontier_reviewer` -> `gpt-5` (`flex`, reasoning `high`, diagnosis-first, dry-run
  only today)
- `emergency_pro_reviewer` -> `gpt-5` (`flex`, reasoning `high`, manual approval
  required)
- `legacy_reasoning_fallback` -> `gpt-5` (`flex`, manual selection only)
- `mini_legacy_fallback` -> `gpt-5-mini` (`flex`, manual selection only)
- `frontier_coding_reviewer` -> `gpt-5.3-codex` -- **disabled for all live calls**
  (`live_calls_disabled: true`); codex has no Flex support, so this role is
  analysis/configuration-only
- `non_reasoning_instruction_follower` -> `gpt-4.1` -- **disabled for all live calls**;
  gpt-4.1 has no Flex support

`reasoning_effort="none"` (previously used by `classification_worker`) was
live-verified 2026-08-07 to be rejected by the real API for every gpt-5-family model
("Unsupported value: 'none' is not supported ... Supported values are: 'minimal',
'low', 'medium', and 'high'."); `classification_worker` now uses `low`, the cheapest
value the live API actually accepts.

`mechanical_worker` remains the active routed nano role for tiny deterministic coding and bounded patches. `classification_worker` is a canonical role for classification and summarization workloads, but is currently manual/reserved unless selected explicitly by config or policy.

Legacy names remain accepted for backward compatibility only:

- `ultra_cheap_classifier` -> `classification_worker`
- `openai_ultra_cheap_legacy` -> `openai_classifier_nano`

## Validation Commands

- `.venv/bin/ruff check .`
- `.venv/bin/mypy .`
- `.venv/bin/pytest`

These three run automatically on every push/PR via `.github/workflows/ci.yml`.

## Safety Guarantees

- Concurrent runs against the same repository are refused (advisory file lock), not
  silently interleaved.
- Any pre-existing uncommitted work in the target repo (tracked or untracked, excluding the
  orchestrator's own logs/state/ledger) is stashed at task start and always restored —
  whether the task succeeds, fails, or is rolled back.
- Commits only ever stage files that are both actually changed by the task's patch *and*
  listed in the task's `allowed_files` — never unrelated pre-existing dirty files.
- Patches are rejected if they touch forbidden paths, escape the workspace, use absolute
  paths, create/modify symlinks, or declare files inconsistent with the actual diff content.
- If the repository's HEAD moves between checkpoint and commit (e.g. another process pushed
  a commit), the task fails safely instead of committing on top of unexpected state.

See [Safety](docs/SAFETY.md) for the full design.

## Service Tier Policy: Flex Is Mandatory, Globally, With No Override

Cost predictability is prioritized over latency. **No paid OpenAI request of any kind
may ever use a service tier other than `flex`** -- not automatic builders, not
classification, not diagnosis reviewers, not frontier reviewers, not emergency
reviewers, not legacy/manual aliases, not direct role selection. Flex is roughly
**50% cheaper per token than Standard/Default** for supported models, at the cost of
higher latency and occasionally reduced availability. This is enforced at two
independent layers so no code path can bypass it:

- **Config load time**: a configuration that would let any live-callable role skip
  Flex, declare an automatic fallback tier, or route through a model without verified
  Flex pricing is **rejected outright**.
- **The actual call boundary**: `OpenAIProvider.generate()` unconditionally refuses,
  before any API interaction, any request whose role isn't `flex` or is marked
  `live_calls_disabled`. There is **no override flag, constructor parameter, or config
  setting** that can force a non-Flex live call, for any role, ever.

On a transient Flex failure, the engine retries a bounded number of times
(`inference.builder_service_tier.flex.max_flex_retries`) -- every retry still requests
Flex, and the model/role never changes. Once exhausted, the task ends with
`flex_unavailable`, not an escalation to a pricier tier. If OpenAI ever reports back a
different tier than what was requested, that response is never accepted as a normal
success -- no output is applied, the repository is rolled back, and the task is
`blocked` with the discrepancy recorded.

`gpt-5.3-codex` and `gpt-4.1` do not support Flex (both live-verified against the real
API). `coding_optimized_builder` (previously codex) was retargeted to `gpt-5`.
`frontier_coding_reviewer` (codex) and `non_reasoning_instruction_follower` (gpt-4.1)
are `live_calls_disabled: true` -- analysis/configuration-only, can never make a real
call, with no override to change that.

See [Cost Control](docs/COST_CONTROL.md) for the full design.

## Known Limitations

- Only the OpenAI provider has a real implementation; other providers are not integrated.
- The diagnosis/reviewer escalation path (`frontier_reviewer`/`emergency_pro_reviewer`) has
  no live model integration — it is dry-run/placeholder only (`diagnosis.dry_run: true`
  by default). Escalations beyond the builder retry loop require human review of the
  generated escalation package under `logs/escalations/`.
- If a builder's patch fails to parse or apply on a retry attempt (rather than merely
  failing validation), that attempt aborts the task rather than retrying — this is a
  narrower failure mode than an ordinary validation failure.
- `small_refactor`, `large_refactor`, `architecture_review`, `dependency_update`, and
  `security_review` workflows are defined but not enabled (`Workflow.enabled=False`).

## Docs

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Model Roles](docs/MODEL_ROLES.md)
- [Cost Control](docs/COST_CONTROL.md)
- [Safety](docs/SAFETY.md)
- [Operational Hardening Changes](docs/OPERATIONAL_HARDENING_CHANGES.md)

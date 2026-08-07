# Operational Hardening Changes

This document summarizes the changes made to take this repository from "passes its own
tests" to genuinely operational and safe for real-world use. It follows on from an earlier
pre-release audit that found the engineering quality was solid (tests/lint/type-check all
green) but several load-bearing safety and correctness invariants were violated by default.

## Global strict Flex-only policy (supersedes the manual override below)

A further follow-up closed the one remaining gap in the policy described in the next
section: the manual override. The updated policy is unconditional -- **no paid OpenAI
request of any kind may ever use a non-Flex tier, including via manual override** --
and now covers every role in the registry, not just the automatically-routed builders.

- `ModelRoleSettings.live_calls_disabled: bool` (default `False`) is the only
  recognized exception mechanism: a role with this set can never make a real
  provider call, full stop, and is analysis/configuration-only.
- `AppConfig._enforce_flex_only_policy` was broadened from checking 5
  auto-routable roles to checking **every role in `model_roles.roles`**: any
  live-enabled role (`live_calls_disabled=False`) must default to Flex, declare no
  fallback tier, and have verified Flex pricing, or config construction fails. It
  also validates that `diagnosis.model_role` doesn't resolve to a
  `live_calls_disabled` role.
- **`OpenAIProvider.generate()` gained an unconditional, airtight guard** as the
  actual enforcement boundary: before touching the SDK at all (before even checking
  whether the provider is enabled), it refuses any request whose role isn't
  `service_tier="flex"` or is `live_calls_disabled`. This is the point no code
  path -- automatic routing, direct/manual role selection, diagnosis, retries,
  future code -- can bypass, because it's where the money is actually spent.
- **The `--allow-non-flex-tier` CLI flag and `manual_service_tier_override`
  constructor parameter were removed entirely.** They became categorically unusable
  once the provider-level guard was added (any attempt would simply be refused), so
  keeping them would have left dead, misleading code -- itself a form of the
  "explicit fallback" the policy exists to prevent.
- `frontier_balanced_reviewer` (`gpt-5.4`), `frontier_reviewer` (`gpt-5.5`), and
  `emergency_pro_reviewer` (`gpt-5.5-pro`, manual approval preserved) were switched
  from `default` to `flex` -- all three live-verified Flex-capable.
- `legacy_reasoning_fallback` (`gpt-5`) and `mini_legacy_fallback` (`gpt-5-mini`)
  were live-verified Flex-capable and switched to `flex`, with new `:flex` pricing
  entries added (following the ~50% ratio already established for every other
  model in the table).
- **`gpt-4.1` does not support Flex** -- live-verified against the real API: a
  `service_tier="flex"` request is rejected with `"Invalid service_tier argument."`
  `non_reasoning_instruction_follower` is now `live_calls_disabled=True`.
- `frontier_coding_reviewer` (`gpt-5.3-codex`) changed from "manual-override-only"
  to `live_calls_disabled=True` -- it can no longer make a live call under any
  circumstance, closing the gap where the old manual override could have been used
  to run it at `default` tier.
- 8 more regression tests added to `tests/test_flex_only_policy.py` (29 total)
  covering the global scope explicitly: diagnosis role Flex-compliance, a config
  rejection test for diagnosis pointed at a disabled role, emergency reviewer
  Flex-with-manual-approval, legacy/alias role compliance, a sweep asserting every
  live-enabled role in the registry is Flex-and-priced, and a sweep confirming the
  provider refuses every role if forced to a non-Flex tier.
- Live-verified against the real API (2026-08-07): `gpt-5-mini`, `gpt-5`, `gpt-5.4`,
  and `gpt-5.5` all accept Flex; `gpt-4.1` rejects it. Combined live-test cost for
  this round: under $0.001 (five tiny `max_output_tokens=16` calls; `gpt-5.5-pro`
  was intentionally not live-tested with a real generation call, per an explicit
  cost exception for expensive emergency-only roles -- verified by configuration
  and existing documented pricing instead).

## Strict Flex-only execution policy (superseded in part by the section above)

A follow-up requirement made cost predictability an explicit, enforced invariant: every
automatically routed OpenAI call must request the `flex` service tier, with **no
automatic fallback** to Standard/Default/Priority/Fast under any circumstance.

- `AppConfig._enforce_flex_only_policy` (a pydantic `model_validator`) rejects, at
  config-load time, any configuration where an automatically-routable role
  (`mechanical_worker`, `classification_worker`, `simple_builder`, `general_builder`,
  `coding_optimized_builder`) doesn't default to Flex, declares a `fallback_service_tier`,
  or lacks a verified `{role}:flex` pricing entry -- or where a pricing table entry's
  declared tier doesn't match its own key suffix.
- `BuilderServiceTierPolicy` (`orchestrator/tier_policy.py`) was rewritten: the old
  `fallback_tier`/`activate_fallback()`/`should_fallback()` mechanism is gone entirely,
  replaced by bounded, Flex-only retries (`max_flex_retries`) and a
  `mark_flex_unavailable()` state. There is no code path left in the engine that can
  select a non-Flex tier automatically.
- New terminal status `flex_unavailable`: once bounded Flex-only retries are exhausted,
  the task ends with this status (not an escalation to a pricier tier), the repository
  is rolled back exactly as on any other failure, and the message explicitly states no
  higher-priced tier was used.
- New `ServiceTierMismatchError`: if the provider ever reports back a tier other than
  what was requested, the response is never accepted as a normal success -- the task is
  `blocked` and the discrepancy is recorded (`tool_results.service_tier_mismatch`).
- **`gpt-5.3-codex` does not support Flex** -- live-verified against the real OpenAI API
  (2026-08-07): a `service_tier="flex"` request is rejected with `"Flex is not available
  for this model."` `coding_optimized_builder` (previously codex) was retargeted to
  `gpt-5.4-mini`, with pricing corrected to match. `frontier_coding_reviewer` intentionally
  keeps codex but is manual-override-only and was never reachable through automatic
  routing to begin with.
- New explicit, per-run, logged manual override: `--allow-non-flex-tier
  {default,priority,batch,fast}` on the CLI (`manual_service_tier_override=` on
  `WorkflowEngine` directly). Never settable via config inheritance; always printed to
  stdout and written to the JSONL log when active.
- Budget ledger gained `requested_service_tier`, `actual_service_tier`, and
  `fallback_occurred` columns, populated on every reconciled call.
- Removed dead, unused `ServiceTierPolicySettings`/`policies.service_tiers` config (it
  was never wired to any actual behavior -- a genuine pre-existing footgun, since it
  looked like it controlled fallback behavior but silently didn't).
- 21 new regression tests in `tests/test_flex_only_policy.py` plus updates to
  `tests/test_tier_policy.py`/`tests/test_model_roles_config.py` covering: every
  auto-routed role uses Flex, no silent fallback (by construction and by test), Flex
  timeout preserves repository state exactly, `flex_unavailable` accuracy, pricing
  always resolves to the Flex entry, non-Flex models can't be auto-routed, the manual
  override is explicit/visible/logged, and the ledger records requested/actual tiers.
  Live-verified against the real API: `gpt-5.3-codex` flex rejection, and a real
  `mechanical_worker`/`gpt-5.4-nano` call confirming `service_tier="flex"` end-to-end
  with reconciled actual cost.

## Critical defects fixed

**A disabled/misconfigured provider was silently reported as a successfully completed
task.** Since `providers.openai.runtime_enabled` defaults to `false`, every default run hit
a dry-run fallback that applied no patch — and because validation trivially passes with zero
changed files, the task was marked `"completed"`. Fixed by tracking provider misconfiguration
via an explicit `provider_dry_run` flag and giving it its own terminal status, `dry_run`,
which is never conflated with success. Same fix extends to a real (non-dry-run) provider that
simply returns no usable patch for a workflow requiring one — new `no_change` status.
(`coding_orchestrator/orchestrator/engine.py`, `coding_orchestrator/schemas.py`)

**Rollback destroyed pre-existing uncommitted user work.** `git restore --worktree --staged .`
reset *all* tracked modifications back to HEAD on rollback, including any dirty changes that
existed in the target repo *before* the task started (allowed by default, since
`require_clean_worktree` defaults to `false`). Checkpoint/rollback was redesigned around
`git stash`: pre-existing dirty/untracked state is stashed at checkpoint time (excluding the
orchestrator's own logs/state/ledger) and popped back — on success, on failure, and on every
early-exit path — so the user's original state is always exactly restored.
(`coding_orchestrator/tools/git.py`)

**The OpenAI SDK call was unguarded.** Real SDK exceptions (rate limits, timeouts, connection
errors, auth failures) are not subclasses of this project's `ProviderError`, so they bypassed
the flex→default service-tier fallback entirely and fell through to a generic task failure.
Now every SDK exception is mapped to a typed provider error
(`ProviderConfigurationError`/`ProviderTransientError`/`ProviderError`), and the fallback
check prefers `isinstance` over string-matching the error message.
(`coding_orchestrator/models/openai_provider.py`, `coding_orchestrator/models/provider.py`)

**`git diff --name-only` missed untracked, staged-only, and deleted files.** Rewritten to use
`git status --porcelain=v1 -z --untracked-files=all`, which also fixes NUL-separated parsing
for filenames with spaces/unusual characters and correctly expands untracked directories
into their individual files (the default git status collapses a wholly-new directory into a
single `dir/` entry, which would have let per-file boundary checks be silently bypassed for
new files inside new directories).

**Structured builder output was silently downgraded on validation failure.** If the model's
JSON response didn't match the `BuilderOutput` schema, the code kept the raw dict and fed it
downstream anyway. Now `StructuredOutputError` is raised instead.

**Budget actuals were never reconciled.** Every attempt recorded a pre-call *estimate*, but
real usage from the provider response was never written back — the ledger's `actual_*`
columns were always `NULL`. `BudgetLedger.record_actual_usage` now idempotently updates the
originating estimate row in place (never inserts a new row, so actuals are never
double-counted alongside their estimate).

**Commits could stage unrelated pre-existing dirty files.** `commit_task` staged
`task.allowed_files` directly rather than the files the task actually changed. If an
unrelated pre-existing dirty file happened to share a path with `allowed_files`, it would be
committed as if it were part of the task. Now it stages the intersection of *actually
changed* files and `allowed_files`, and refuses to commit (rather than silently no-op) if
real changes exist outside the task boundary.

**Runtime data paths were inconsistently resolved.** The budget ledger path was resolved
against `repo_path`; the log path, state path, and (hardcoded, non-configurable) escalations
directory were not, resolving against the caller's CWD instead. All four are now resolved
consistently against `repo_path`, and a new `escalations_path` config field replaces the
hardcoded value.

## Other hardening

- Concurrent orchestrator runs against the same repository are now prevented via an advisory
  `flock` (`coding_orchestrator/tools/lock.py`), checked before any git state is touched.
- HEAD is captured at checkpoint time and verified before commit; if it moved (another
  process committed concurrently), the task fails safely instead of committing on unexpected
  state.
- Patches that create/modify symlinks, use absolute paths, or declare duplicate touched
  files are now rejected (`coding_orchestrator/tools/patch.py`).
- Unexpected exceptions now retain a full traceback in both the task state
  (`tool_results.error_traceback`) and the structured log, rather than only `str(exc)`.
- `Workflow.enabled=False` (for `small_refactor`, `large_refactor`, `architecture_review`,
  `dependency_update`, `security_review`) was declared but never enforced; tasks classified
  into a disabled workflow now correctly route to `requires_human_approval` (`blocked`)
  instead of silently executing.
- `[project.scripts]` was missing despite `app.py` defining `prog="coding-orchestrator"`; the
  CLI is now actually installable as `coding-orchestrator`.
- Dependencies gained upper-bound version constraints and a generated
  `requirements-lock.txt` for exact reproducibility; `OpenAIProviderSettings.max_retries`
  default changed from `0` to `2`.

## Repository hygiene

- Removed `phase3_wip.patch` (276 KB scratch git-diff), `phase3_wip_status.txt`, and four
  internal "resume this AI session" handoff docs (`docs/RESUME_PHASE3_PROMPT.md`,
  `docs/SESSION_HANDOFF_PHASE3.md`, `docs/PHASE3_CONTINUITY_ADDENDUM.md`,
  `docs/ARCHITECTURE_STATE_SNAPSHOT.md`) that had been committed to `master`. These neither
  applied forward nor in reverse against the current tree — confirming the work they
  described was already completed and merged, making them dead weight.
- Removed orphaned, unreferenced placeholder modules: `coding_orchestrator/models/base.py`,
  `coding_orchestrator/models/cloud_model.py`, `coding_orchestrator/models/local_model.py`,
  and the entire unused `coding_orchestrator/workspace/` package.
- Added `.github/workflows/ci.yml` running ruff, mypy, pytest, an import/packaging smoke
  test, and a CLI `report` smoke test on every push and pull request — previously there was
  no CI at all.

## Testing

All fixes above are covered by new regression tests in `tests/test_operational_hardening.py`
(22 tests), using real temporary git repositories rather than mocks wherever git behavior
matters: dry-run/no-change status distinctness, idempotent ledger reconciliation,
comprehensive changed-file detection (tracked/staged/untracked/deleted/renamed/spaces/new
directories), rollback preserving pre-existing dirty and untracked work, concurrency
protection, HEAD-change detection, structured-output rejection, patch traversal/absolute
path/symlink rejection, commit boundary enforcement, typed transient-error-driven service-tier
fallback, and a disabled-workflow gate. Several pre-existing tests were also updated because
they were unknowingly exercising the dry-run-masquerading-as-success bug (they constructed a
`WorkflowEngine` with no provider configured and asserted `final_status == "completed"`); they
now use `FakeModelProvider` explicitly.

Full validation after these changes: **95 passed**, `ruff check .` clean, `mypy .` (strict)
clean.

## What is still not resolved

- The diagnosis/reviewer escalation path has no real model integration (dry-run/placeholder
  only). This was true before this pass and remains true — implementing it was out of scope
  here, since it requires deciding on and wiring an actual reviewer model call.
- If a builder response fails to parse as a patch or fails patch application on a retry
  attempt, that attempt aborts the task immediately rather than being folded into the normal
  validation-failure retry loop. A more thorough fix would treat parse/apply failures as just
  another validation failure the convergence/retry logic can act on.
- Only the OpenAI provider is implemented; no other provider backend exists despite the
  interface being provider-agnostic in shape.
- A real end-to-end run against the live OpenAI API has not been performed as part of this
  work (see the main conversation for the minimal, explicit, cost-bounded verification step
  offered before any real API key is used).

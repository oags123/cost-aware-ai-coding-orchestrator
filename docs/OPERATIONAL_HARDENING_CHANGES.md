# Operational Hardening Changes

This document summarizes the changes made to take this repository from "passes its own
tests" to genuinely operational and safe for real-world use. It follows on from an earlier
pre-release audit that found the engineering quality was solid (tests/lint/type-check all
green) but several load-bearing safety and correctness invariants were violated by default.

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

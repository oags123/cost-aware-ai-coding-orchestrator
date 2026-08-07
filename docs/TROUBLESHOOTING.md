# Troubleshooting

## Task reported `dry_run` instead of `completed`

- This means no real model call happened at all — check `providers.openai.runtime_enabled`,
  confirm `OPENAI_API_KEY` is set in the environment, and confirm the `openai` Python
  package is installed (`pip show openai`). Inspect `tool_results.builder_warning` on the
  task state for the exact reason. This status used to be silently reported as `completed`;
  it no longer is, so treat `dry_run` as "nothing happened," not "succeeded."

## Task reported `no_change` instead of `completed`

- Validation passed, but the builder never produced (or applied) an actual patch for a
  workflow that requires one. Check `tool_results.builder.text` for what the model actually
  returned. Non-modifying workflows (`explain_code`, `architecture_review`,
  `security_review`) are exempt and can legitimately report `completed` with zero changes.

## Task reported `flex_unavailable`

- OpenAI's Flex tier was requested and, after bounded Flex-only retries
  (`inference.builder_service_tier.flex.max_flex_retries`, default 2), never
  succeeded. This is a deliberate pause, not an error to "fix" -- **no higher-priced
  tier was used automatically, and there is no way to make it use one**: the only
  options are to retry later when Flex capacity may be available, or increase
  `max_flex_retries`. There is no override flag or config setting that permits a
  non-Flex live call for any role. See [Cost Control](COST_CONTROL.md).

## Task reported `blocked` with a `service_tier` mismatch message

- The provider reported back a different service tier than what was requested (e.g.
  Flex was requested but the response wasn't Flex). Under the strict Flex-only policy
  this is never silently accepted as a successful call -- check
  `tool_results.service_tier_mismatch` for the requested vs. actual tier reported by
  OpenAI.

## A role's calls always fail with "live_calls_disabled=True"

- That role's underlying model is verified to not support Flex (`gpt-5.3-codex` via
  `frontier_coding_reviewer`, `gpt-4.1` via `non_reasoning_instruction_follower`), so
  it is analysis/configuration-only and can never make a real API call -- this is
  intentional, not a bug, and there is no override. Use a different, Flex-capable role
  instead (e.g. `coding_optimized_builder` for codex-style coding work).

## Task reported `blocked` with "another orchestrator run holds the lock"

- Only one orchestrator run is allowed against a given repository at a time. Wait for the
  other run to finish, or confirm it isn't a stale lock from a crashed process (the lock is
  a plain advisory `flock` on `<repo>/.orchestrator.lock` and is released automatically when
  the holding process exits or crashes).

## Task reported `failed` with "repository HEAD changed during task execution"

- Something else (another process, a manual `git checkout`/`git commit`) moved HEAD while
  the task was running. Re-run once the repository is quiescent.

## OpenAI provider blocked

- Check `providers.openai.runtime_enabled`.
- Confirm `OPENAI_API_KEY` is set.
- Confirm `openai` Python package is installed.

## Budget blocked

- Inspect `report` budget fields.
- Reduce task scope or increase configured role budget.
- `report`'s spend figures now reflect reconciled actual token usage where available,
  falling back to the pre-call estimate only for calls that never completed.

## Limits blocked

- Inspect `report.limit_failures`.
- Reduce context/patch size or adjust limits deliberately.

## Patch rejected

- Ensure output is unified diff or structured JSON patch.
- Ensure touched files stay within task `allowed_files`.
- Absolute paths, path traversal (`../`), and patches that create/modify symlinks are
  always rejected, regardless of `allowed_files`.

## My pre-existing uncommitted changes disappeared / came back stashed

- They should not disappear: any pre-existing uncommitted work (tracked or untracked) in
  the target repo is stashed at task start and always restored afterward, whether the task
  succeeds, fails, or is rolled back. If you interrupted a run (e.g. killed the process) and
  it never got to restore the stash, check `git stash list` — your work is there under an
  `orchestrator-<task_id>` message, and `git stash pop` restores it.

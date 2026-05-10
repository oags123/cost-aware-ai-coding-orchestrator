# Safety Model

The orchestrator is built around deterministic control. LLM output is treated as untrusted until validated.

## Hard Boundaries

Model output cannot:

- execute arbitrary shell commands
- bypass validators
- bypass file boundaries
- approve dangerous actions
- deploy
- push git
- access secrets intentionally
- delete files unless the task explicitly allows deletes

## Forbidden Path Markers

Configured forbidden path markers include:

- `/etc/`
- `~/.ssh`
- `.env`
- `secrets`
- `credentials`
- `tokens`

## Patch Contract

Real OpenCode mode accepts only:

- unified diff text, or
- JSON with `patch`, `touched_files`, `summary`, and `confidence`

Free-form instructions are rejected.

## Expensive Reviewer Contract

The expensive reviewer is diagnosis-only. Its output must be structured and may
contain only:

- root cause
- minimal fix strategy
- files to focus
- risks
- Gemini/cheap-builder instruction
- confidence
- whether to retry with the cheap builder

Reviewer output is rejected if it contains:

- unified diffs
- file write/delete instructions
- shell commands
- large code blocks
- direct patch proposals

The reviewer cannot modify files and its output is never applied as code.

## Patch Application

Before applying, the patch layer checks:

- touched files are declared
- declared JSON `touched_files` match diff paths
- patch bytes do not exceed `limits.max_patch_bytes`
- max file count is not exceeded
- forbidden paths are not touched
- paths stay inside the workspace
- task `allowed_files` boundaries are respected
- deletes are allowed only when `allow_deletes: true`
- `git apply --check` succeeds

## Size and Output Limits

The engine enforces hard size limits around model/OpenCode calls:

- context character limit before invocation
- estimated input token limit before invocation
- configured output token estimate limit before invocation
- builder stdout/stderr byte limits after invocation
- patch byte limit before `git apply --check`
- validation output byte limit before state/log persistence

Limit failures use explicit statuses:

- `context_limit_exceeded`
- `output_limit_exceeded`
- `patch_limit_exceeded`
- `validation_output_limit_exceeded`

Pre-call limit failures block the call. Post-call output and patch limit
failures block patch application. Validation output is truncated by default so
logs and state remain bounded; config can instead make oversized validation
output fail validation.

## Rollback

On failure or timeout, rollback restores tracked/staged changes and removes newly-created untracked files, except configured preserved paths such as logs and caches.

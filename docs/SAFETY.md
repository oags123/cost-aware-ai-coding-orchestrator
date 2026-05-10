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

## Patch Application

Before applying, the patch layer checks:

- touched files are declared
- declared JSON `touched_files` match diff paths
- max file count is not exceeded
- forbidden paths are not touched
- paths stay inside the workspace
- task `allowed_files` boundaries are respected
- deletes are allowed only when `allow_deletes: true`
- `git apply --check` succeeds

## Rollback

On failure or timeout, rollback restores tracked/staged changes and removes newly-created untracked files, except configured preserved paths such as logs and caches.


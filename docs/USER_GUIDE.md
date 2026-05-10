# User Guide

This guide is for the repository owner/operator. It describes the current
real-world MVP state, not future planned behavior.

## Current Architecture

The orchestrator is a controlled Python workflow engine:

`task -> classify -> route -> build context -> bounded OpenCode step -> validate -> retry/escalate -> log`

Python controls the workflow. OpenCode is only called inside a bounded builder
step. Validators, Git, timeouts, budgets, limits, and task file permissions
decide whether output is acceptable.

Implemented components:

- YAML config and task files
- Pydantic task/state schemas
- CLI commands: `run`, `run-all`, `validate`, `report`
- dry-run builder mode
- config-gated real OpenCode mode through `opencode run`
- safe patch contract and `git apply --check`
- validators for command safety, patch scope, syntax, and tests
- Git checkpoint, rollback, and scoped commits
- SQLite budget ledger with estimated spend
- hard token/context/output/patch/stdout/stderr limits
- Gemini Flex/Standard tier policy through the OpenCode builder path
- diagnosis-only reviewer interface, disabled/dry-run by default
- Telegram blocker/stop alerts, disabled by default
- Dockerfile and docker-compose for local container execution

Not implemented:

- direct Gemini API calls from this repository
- production reviewer API calls
- GPT/frontier direct patching
- Telegram approval modes
- unattended SafeAuto
- crash-safe resume
- external watchdog/heartbeat
- web UI, cloud deployment, Kubernetes, embeddings, RAG, or vector DB

## Required Components

- Ubuntu/Linux shell
- Python 3.11+
- Git
- `pytest`, `ruff`, and `mypy` installed through the project dev dependencies
- OpenCode installed separately for real mode
- provider credentials for the OpenCode provider you choose

## Optional Components

- Docker and Docker Compose
- Telegram bot token and chat id for alerts
- Gemini API key if using Gemini through OpenCode

Docker is not required for the first real trial. The safest first trial is a
local venv run from a clean Git branch or throwaway clone.

## Exact Setup Order

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

2. Validate the repository:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

3. Copy the example config:

```bash
cp config.example.yaml config.yaml
```

4. Run dry-run smoke tests:

```bash
.venv/bin/python -m coding_orchestrator.app report
.venv/bin/python -m coding_orchestrator.app validate
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
.venv/bin/python -m coding_orchestrator.app run-all --tasks-dir tasks/
```

5. Install and authenticate OpenCode. See [OpenCode Setup](OPENCODE_SETUP.md).

6. Configure provider credentials, model names, budget caps, and task limits.

7. Run one tiny real task from a clean branch or throwaway clone.

## Dry-Run Vs Real Mode

Dry-run mode is the default:

```yaml
opencode:
  enabled: false
  dry_run: true
```

Dry-run mode exercises orchestration, validation, logging, budget estimates,
retry/escalation flow, and reports. It does not call OpenCode and does not
apply model output.

Real mode requires both fields:

```yaml
opencode:
  enabled: true
  dry_run: false
```

In real mode, the orchestrator invokes `opencode run` with a bounded timeout.
OpenCode must return only a unified diff, or JSON containing `patch`,
`touched_files`, `summary`, and `confidence`. Free-form instructions are not
applied.

## Recommended First Real-World Scope

Use a tiny task:

- one intended source file
- one test file at most
- no deletes
- no refactor
- no dependency changes
- one validation command, preferably a focused pytest file
- low budget cap such as `$0.02` to `$0.05`
- `max_attempts: 1` for the very first trial

Do not run the first trial against a large queue.

## Example Tiny Task

Create `tasks/real_trial_tiny.md`:

```yaml
---
id: T-REAL-001
title: Add one focused unit test
complexity: simple
risk: low
allowed_files:
  - tests/test_core.py
max_attempts: 1
max_runtime_seconds: 300
max_cost_usd: 0.03
escalation_allowed: true
validation_commands:
  - .venv/bin/pytest tests/test_core.py
---
Add one small test for an existing pure function in tests/test_core.py.
Return only the required patch.
```

Prefer a task that only changes a test file. After that succeeds, try a one-file
implementation task.

## Safe Real-Mode Config Snippet

Adjust `provider/model` to the exact value shown by `opencode models`.

```yaml
opencode:
  enabled: true
  dry_run: false
  executable: "opencode"
  default_model: "google/gemini-3.1-flash-lite"
  max_runtime_seconds: 300
  output_mode: "unified_diff"
  allowed_env_vars:
    - "GEMINI_API_KEY"
  extra_args: []

budget:
  project_id: "first-real-trial"
  project_total_budget_usd: 0.25
  cheap_builder_budget_usd: 0.20
  expensive_reviewer_budget_usd: 0.00
  emergency_budget_usd: 0.00

diagnosis:
  enabled: false
  dry_run: true

git:
  require_clean_worktree: true
```

The model string above is only an example. OpenCode expects
`provider/model` format. Use your local `opencode models --refresh` and
`opencode models` output as the source of truth.

## Gemini API Access

This repository does not call the Gemini API directly. Gemini is used only when
OpenCode is configured to use a Gemini provider/model.

Typical setup:

```bash
export GEMINI_API_KEY="..."
opencode auth login
opencode models --refresh
opencode models
```

The orchestrator forwards only the environment variable names listed in
`opencode.allowed_env_vars`, plus minimal process variables such as `PATH` and
`HOME`.

Current config defaults use Gemini Flash-Lite as the cheap builder planning
target and Flex as the default tier. Google documents Flex as lower-cost,
best-effort, variable-latency inference; Standard fallback is bounded by this
repo's tier policy. Audit prices and exact model identifiers before paid use.

## Telegram Alerts

Telegram is optional and disabled by default:

```yaml
telegram:
  enabled: false
  bot_token_env_var: "TELEGRAM_BOT_TOKEN"
  chat_id_env_var: "TELEGRAM_CHAT_ID"
  missing_env_policy: "warn"
  notify_on_blocked: true
  notify_on_budget_exhausted: true
  notify_on_runtime_exhausted: true
  notify_on_no_runnable_tasks: true
  notify_on_system_error: true
```

Enable it only after dry-run works:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Telegram is notification-only. It cannot approve work, resume runs, change
permissions, or execute commands.

## Running The First Real Task

1. Start from a clean branch or throwaway clone:

```bash
git status --short
git checkout -b first-real-opencode-trial
```

2. Confirm OpenCode works outside the orchestrator:

```bash
command -v opencode
opencode --version
opencode auth list
opencode models --refresh
opencode models
```

3. Run the task:

```bash
.venv/bin/python -m coding_orchestrator.app run --task tasks/real_trial_tiny.md
```

The CLI exits `0` only when the task completes. Blocked, failed, escalated, or
timeout statuses return non-zero.

## Inspecting Results

Use:

```bash
git status --short
git diff --stat
git log --oneline -5
.venv/bin/python -m coding_orchestrator.app report
```

Inspect:

- `logs/orchestrator.jsonl` for event logs
- `logs/state.json` for task state
- `logs/budget.sqlite` for persistent budget ledger
- `logs/escalations/` for failure/escalation packages

On success, the engine attempts a scoped Git commit using only
`task.allowed_files`. If there are no changes, commit is treated as a no-op
success. If Git commit fails, the task is not marked completed.

## Rollback And Checkpoints

Before each task, the engine captures a Git checkpoint:

- currently dirty tracked files
- currently untracked files

On task failure, timeout, or blocked model call after a checkpoint, rollback:

- restores tracked/staged changes with Git
- removes newly created untracked files
- preserves configured safe directories such as `logs/` and cache directories

Set `git.require_clean_worktree: true` for the first real trial so tasks refuse
to start when tracked files are already dirty.

## Docker Usage

Docker is for local container validation and repeatable execution. It is not
required for the first real trial.

```bash
docker compose build
docker compose run orchestrator python -m coding_orchestrator.app validate
docker compose run orchestrator python -m coding_orchestrator.app run-all --tasks-dir tasks/
```

The container runs as a non-root user, mounts the repository at `/workspace`,
and uses a persistent `logs` volume. Docker access requires the current user to
have permission to use the Docker socket.

OpenCode is not installed in the project Dockerfile today. For real OpenCode
mode, prefer local venv execution until containerized OpenCode credentials and
installation are explicitly added.

## Safe Usage Before Unattended Automation

- run one task at a time
- keep `allowed_files` narrow
- keep `max_attempts` low
- keep budgets small
- keep `diagnosis.enabled: false` unless testing the dry-run reviewer path
- use `git.require_clean_worktree: true`
- inspect every diff and commit
- do not run unattended queues
- do not enable Telegram approval patterns; they are not implemented

## Future/Planned Only

- external watchdog and heartbeat
- SQLite-backed run/task state and `resume`
- integration checkpoints
- local/provider caching strategy
- spec-to-tasks planner
- provider usage reconciliation from actual reported tokens/cost
- memory/retrieval
- richer observability reports
- unattended SafeAuto
- Telegram approval modes
- production reviewer API integrations

See [Roadmap](ROADMAP.md).

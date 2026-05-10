# Real-World Trial Runbook

Use this runbook for the first real OpenCode execution. Do not use it for a
large task queue.

## Trial Goal

Prove that the current MVP can safely:

- call OpenCode in real mode
- receive a strict patch
- validate and apply the patch
- run focused validation
- commit only allowed files
- roll back on failure
- record logs, state, and budget estimates

## Before You Start

Confirm the repository is healthy:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/mypy .
```

Confirm Git is clean:

```bash
git status --short
```

Use a branch or throwaway clone:

```bash
git checkout -b first-real-opencode-trial
```

## Install And Check OpenCode

Follow [OpenCode Setup](OPENCODE_SETUP.md), then confirm:

```bash
command -v opencode
opencode --version
opencode auth list
opencode models --refresh
opencode models
```

Pick the exact `provider/model` string from `opencode models`.

## Configure Real Mode

Copy the example config if needed:

```bash
cp config.example.yaml config.yaml
```

Recommended first-trial settings:

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

git:
  require_clean_worktree: true

diagnosis:
  enabled: false
  dry_run: true
```

Replace `google/gemini-3.1-flash-lite` with the model string OpenCode reports.

## Configure Environment Variables

If using Gemini through OpenCode:

```bash
export GEMINI_API_KEY="..."
```

If using Telegram alerts:

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

Do not put tokens in `config.yaml`, task files, logs, or committed docs.

## Create A Tiny Task

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
Return only a unified diff. Do not edit any other file.
```

Use a test-only task first. Avoid deletes, refactors, dependency changes, and
multi-file implementation work.

## Run The Trial

```bash
.venv/bin/python -m coding_orchestrator.app run --task tasks/real_trial_tiny.md
```

Expected successful behavior:

- OpenCode runs once through `opencode run`
- output is parsed as a patch
- patch touches only `tests/test_core.py`
- validators pass
- a scoped commit is created
- state/log/budget entries are written

Any blocked, failed, escalated, or timeout status exits non-zero.

## Inspect The Result

```bash
git status --short
git log --oneline -5
git show --stat --oneline HEAD
.venv/bin/python -m coding_orchestrator.app report
```

Inspect:

- `logs/orchestrator.jsonl`
- `logs/state.json`
- `logs/budget.sqlite`
- `logs/escalations/`

Also check OpenCode's own session/cost data:

```bash
opencode stats
opencode session list
```

The orchestrator ledger currently stores estimates. Provider-reported actual
usage reconciliation is future work.

## If The Trial Fails

Start with:

```bash
git status --short
git diff --stat
.venv/bin/python -m coding_orchestrator.app report
```

Common outcomes:

- `OpenCode is not installed or not on PATH`: install OpenCode or set
  `opencode.executable`.
- budget blocked: lower context/output size, raise only the tiny trial budget,
  or inspect `logs/budget.sqlite`.
- patch rejected: check forbidden paths, deletes, max files changed, and
  `allowed_files`.
- validation failed: inspect validator messages in state/logs.
- timeout: keep Flex timeout high enough or use Standard fallback only within
  configured limits.

Rollback should restore tracked changes and remove newly created untracked
files except preserved paths. Still inspect Git before retrying.

## Stop Criteria

Stop after the first real trial if:

- OpenCode output is free-form instead of a patch
- patch validation rejects output
- validation fails repeatedly
- rollback does not leave the worktree as expected
- budget ledger or reports look wrong
- OpenCode model or pricing assumptions differ from current provider docs

Document the transcript, model, estimated cost, actual provider usage if
available, resulting diff, validation output, and any issues before expanding
scope.

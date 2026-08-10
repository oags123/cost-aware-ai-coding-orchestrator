# Quick Start

The practical, operational guide — open this when you actually want to *use* the
system. For exhaustive detail on any topic below (every config field, every CLI
flag, every failure mode), see the **[Production Usage Guide](PRODUCTION_USAGE_GUIDE.md)**.
For the full cost-minimization loop involving ChatGPT and Google Drive, see
**[ChatGPT Handoff Workflow](docs/CHATGPT_HANDOFF_WORKFLOW.md)**.

## What this is

A local Python CLI that takes a small, well-scoped task (or a directory of them)
and, for each one: builds bounded context from the files it's allowed to touch,
sends it to a cheap OpenAI model over Flex pricing, requires the response back as
a unified diff, applies and validates it with real `git`/`ruff`/`mypy`/`pytest`,
commits on success, and rolls back to a clean checkpoint on any failure. Every
model call's real cost is tracked in a local ledger, and every paid call is
Flex-only on `gpt-5-nano`/`gpt-5-mini` — nothing here can silently spend more.

It is **not** an agent that takes a product idea and builds an entire project
unattended. It executes tasks you (or an external planner) have already broken
into small, bounded pieces, under your supervision.

## The end-to-end workflow this project is built around

```
ChatGPT (subscription)              -- plan the project, generate initial code
        |
Google Drive (rclone)               -- transfer to the VPS
        v
VPS: git seed commit + `validate`   -- free, local, deterministic check of what's broken
        v
ChatGPT again                       -- turn failures into small task files
        v
this orchestrator                   -- cheap gpt-5-nano/gpt-5-mini Flex repairs, validated, committed
        v
   [stalls / too expensive?] --> local handoff file --> Google Drive --> ChatGPT (stronger reasoning)
        |                                                                      |
        v                                                                      |
   continues automatically <-------------------- corrections/new tasks --------+
        v
Claude Code (subscription, optional) -- final whole-repo review --> another task set --> repeat
```

You can also skip the ChatGPT-generation front end entirely and just hand the
orchestrator a task or task set directly — see below. Both paths use the exact
same engine.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -r requirements-lock.txt   # exact, reproducible versions
cp config.example.yaml config.yaml
```

Requires Python ≥3.11 and `git` on `PATH`. Verify:

```bash
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy .
.venv/bin/coding-orchestrator --config config.yaml validate   # health-check current repo, free
```

## Configure for real (paid) calls

By default `providers.openai.runtime_enabled: false` — nothing costs money until
you change that. To go live:

```bash
export OPENAI_API_KEY="sk-...your-key..."   # current shell only, never in a file
```

```yaml
# config.yaml
providers:
  openai:
    runtime_enabled: true
```

Never paste the key into `config.yaml`, a task file, or any doc. See
[Production Usage Guide §4](PRODUCTION_USAGE_GUIDE.md#4-real-openai-setup) for
full detail.

## Give it a task, or a task set

A task is a small YAML(+Markdown) file naming exactly which files it may touch
and how to validate the result:

```markdown
---
id: T-001
title: Fix the off-by-one in pkg/calc.py
complexity: simple
risk: low
allowed_files: ["pkg/calc.py"]
max_attempts: 2
max_cost_usd: 0.02
validation_commands: ["python3 -m pytest tests/test_calc.py -q"]
---
subtract(a, b) returns a + b instead of a - b. Fix the operator.
```

```bash
# one task
.venv/bin/coding-orchestrator --config config.yaml run --task tasks/T-001.md

# a whole directory, dependency-ordered (depends_on)
.venv/bin/coding-orchestrator --config config.yaml run-all --tasks-dir tasks/
```

Task files can be hand-written, or produced by ChatGPT from a failure list — see
the handoff workflow below. Full field reference:
[Production Usage Guide §8](PRODUCTION_USAGE_GUIDE.md#8-task-file-reference).

## The important options

| Setting | Where | What it controls |
|---|---|---|
| `allowed_files` | task file | The only files a patch may touch — keep to 1-2 for anything you want auto-routed cheaply. |
| `max_cost_usd` / `max_attempts` | task file | Hard per-task cost and retry ceiling. |
| `validation_commands` | task file | What actually has to pass — falls back to `ruff`/`mypy`/`pytest`. |
| `budget.project_total_budget_usd` | config.yaml | Hard ceiling across every task in the project. |
| `handoff.enabled` | config.yaml | Whether a local escalation artifact is written on stall (default `true`). |
| `git.require_clean_worktree` | config.yaml | `true` refuses to start on a dirty repo instead of auto-stashing it. |

## How normal execution proceeds

Automatic routing is nano/mini-only, always Flex, and picks between exactly
three roles based on complexity/risk/file count — there is no automatic path to
a more expensive model:

- `mechanical_worker` (gpt-5-nano) — tiny, single-file, deterministic tasks.
- `simple_builder` (gpt-5-mini) — small, 1-2 file patches.
- `general_builder` (gpt-5-mini, more reasoning) — anything harder, or a retry.

For each task: context is built → sent → the patch is applied and validated →
on success it's committed and the task ends `completed`; on a fixable failure it
retries (bounded by `max_attempts`); on success of neither, it stops safely.

## What happens when inexpensive automation cannot continue

Whenever a task stops without completing — repeated failures that aren't
improving, a budget or limit ceiling, Flex capacity unavailable, or attempts
exhausted — **the repository is rolled back to exactly how it was before the
task started**, and a single local Markdown file is written to
`logs/handoffs/` summarizing why, with the task spec, what was tried, the
current diff, and a budget snapshot. This costs nothing and makes no network
call. There is deliberately no automatic escalation to a pricier OpenAI model —
see below for what happens instead.

```bash
.venv/bin/coding-orchestrator --config config.yaml handoff   # list pending ones, JSON, read-only
```

## The ChatGPT / Google Drive handoff

1. `coding-orchestrator handoff` to find the file, then upload it explicitly
   (never automatically):

   ```bash
   rclone copyto logs/handoffs/T-001-abcd1234-handoff.md \
     "gdrive-jobs:AI-Coding-Orchestrator-Handoffs/T-001-abcd1234-handoff.md"
   rclone lsf "gdrive-jobs:AI-Coding-Orchestrator-Handoffs/"   # verify it landed
   ```

   (Use `rclone listremotes` to confirm your actual remote name if it differs.)

2. Open ChatGPT, point it at the uploaded file, and ask it to use its strongest
   reasoning to produce either corrected files or a new/updated task set in this
   repository's task-file format (the handoff file includes that schema).

## How work returns from ChatGPT to the VPS

Pull ChatGPT's response back through Google Drive (same `rclone copyto` +
verify pattern), place any new/updated task files in your tasks directory, or
apply corrected source files directly, and just run the orchestrator again —
`run`/`run-all` don't care whether the code was written by a human, generated by
ChatGPT, or produced by an earlier orchestrator run. No special "resume" command
is needed.

**Read every returned task file, especially `validation_commands`, before
running it.** There's no sandbox — an allowlisted interpreter (`python`/
`python3`) can run arbitrary code, so a task file is exactly as trustworthy as
a shell command you'd type yourself. This is precisely why this step stays
manual; see [ChatGPT Handoff Workflow](docs/CHATGPT_HANDOFF_WORKFLOW.md) for
why unattended ingestion of returned files is a blocker, not a future
nice-to-have.

## How the final Claude Code review fits in

Once `coding-orchestrator validate` passes and the repository looks
substantially complete, optionally have Claude Code (its own subscription, not
metered API usage) review the whole repository with its large-context
capabilities — architectural inconsistencies, missing requirements, weak tests,
security issues a task-local repair process couldn't see. Turn its findings into
another small task set and run the orchestrator again. Repeat until satisfied.

## Inspecting results, cost, git state, validation, and failures

```bash
# What actually happened
cat logs/orchestrator.jsonl | tail -5        # event trail
cat logs/state.json | python3 -m json.tool | less   # full state of every run

# Cost so far
.venv/bin/coding-orchestrator --config config.yaml report
sqlite3 logs/budget.sqlite "SELECT model_role, model, status, actual_cost_usd FROM budget_events;"

# What actually changed
git log --oneline -5
git show HEAD

# Anything pending human/ChatGPT attention
.venv/bin/coding-orchestrator --config config.yaml handoff
ls logs/escalations/
```

`final_status` in the printed JSON is the one field that matters most: only
`"completed"` means it actually worked. Everything else (`dry_run`, `no_change`,
`blocked`, `flex_unavailable`, `timeout`, `failed`, `escalated`) means either
nothing happened or something needs your attention — see
[Production Usage Guide §15](PRODUCTION_USAGE_GUIDE.md#15-failure-statuses-and-recovery)
for the full table and recovery steps for each.

## The safest way to start your first real project

1. **Use a disposable throwaway repo first**, not your real project — `git init`
   a scratch directory, make one commit, and run through the whole loop above
   once end to end before trusting it with anything real.
2. Set a very small budget (`project_total_budget_usd: 0.05`,
   `max_cost_usd: 0.01` per task) and a single, trivial task with 1 allowed file.
3. Run it. Confirm `final_status: "completed"`, check the diff, check the ledger.
4. **Deliberately break a task** (a validation command guaranteed to fail) and
   confirm the repository rolls back to exactly its prior state.
5. Only after both of those behave as expected, point it at a real repository —
   start with `git.require_clean_worktree: true` and 1-2 file tasks, and
   gradually expand scope and budget as you build confidence.

Full walkthrough with copy-paste commands:
[Production Usage Guide §10](PRODUCTION_USAGE_GUIDE.md#10-recommended-first-production-run).

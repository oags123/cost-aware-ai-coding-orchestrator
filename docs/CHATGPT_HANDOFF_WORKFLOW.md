# ChatGPT-Subscription Handoff Workflow

This describes a cost-minimization workflow layered on top of the existing engine,
introduced 2026-08-10. It changes nothing about how `WorkflowEngine`/`TaskSpec`/
`run`/`run-all` work -- it adds one new local artifact (a "handoff") and one new
read-only CLI command (`handoff`) that make a specific operating pattern practical:
using a ChatGPT subscription (flat/sunk cost) for both initial generation and
strong-reasoning escalation, and reserving metered OpenAI API spend for cheap,
bounded, Flex-only `gpt-5-nano`/`gpt-5-mini` repair work.

## Why

Metered OpenAI API cost is minimized by keeping two kinds of work off the API
entirely:

- **Work a subscription product already covers**: detailed project planning,
  initial multi-file code generation (which benefits from a single continuous
  conversation's full context -- something this orchestrator's per-task isolated
  context cannot provide), and strong-reasoning diagnosis of problems cheap models
  can't solve.
- **Work local, deterministic tools can do for free**: tests, linting, type
  checking, git operations, patch boundary/permission checks, rollback, budget
  accounting. None of this requires a model call, and this orchestrator already
  does all of it locally (see [Architecture](../PRODUCTION_USAGE_GUIDE.md#2-architecture),
  [Safety](SAFETY.md)).

What's left for the metered OpenAI API -- and the only thing it should be spent
on -- is small, bounded, deterministically-checkable repairs: fixing a failing
test, a lint error, a type error, an integration gap between files a human or
ChatGPT already made architecturally coherent. That is exactly the class of work
`mechanical_worker`/`simple_builder`/`general_builder` (gpt-5-nano/gpt-5-mini,
Flex-only, auto-routed) are built for.

## The loop

```
ChatGPT subscription (planning + initial generation)
        |
        v
Google Drive  (existing rclone remote, e.g. gdrive-jobs:)
        |
        v
VPS / git  --  seed commit  --  `coding-orchestrator validate` (free, local)
        |
        v
Orchestrator: cheap gpt-5-nano/gpt-5-mini Flex repair tasks, validated, committed
        |
        +-- progress continues automatically while it's cheap and converging --+
        |                                                                      |
        v                                                                      |
   task stalls / budget or limit exceeded / Flex unavailable / retries exhausted
        |
        v
   handoff artifact written locally (logs/handoffs/, zero cost)  -------------->
        |
        v
   `coding-orchestrator handoff`  ->  upload via rclone (manual, explicit)
        |
        v
   ChatGPT subscription: stronger reasoning, produces corrected files or a new
   task set, placed back on Google Drive
        |
        v
   pull back to the VPS  ->  orchestrator continues (same `run`/`run-all`)
```

Repeat the escalation loop as needed. Once the repository passes its normal
validation, an optional final pass with **Claude Code** (subscription, not
Anthropic API) can review the whole repository for project-wide issues a
task-local repair process wouldn't catch, and produce another correction task set
that goes through the same loop.

## Step by step

### 1. Plan and generate with ChatGPT

Define the project (purpose, requirements, architecture, constraints, interfaces,
data model, security/testing requirements, acceptance criteria) and have ChatGPT
generate as much of the initial repository as practical: source, tests, config,
docs, structure. This step is entirely outside this codebase.

### 2. Transfer to the VPS via Google Drive

Use the existing `rclone` setup exactly as already established for this project:
`rclone copyto` (never `sync`) for a specific file or a small, explicit set of
files, verified afterward with `rclone lsf`/`ls`. See the rclone remote you
already have configured (`rclone listremotes`) -- do not create a new one unless
you actually need a second, distinct destination.

### 3. Seed the repository and run a free validation pass

A brand-new git repository with zero commits cannot be checkpointed by this
orchestrator (`git rev-parse HEAD` fails with no commits, and that's the very
first thing `run`/`run-all` do). Seed it once:

```bash
cd /path/to/imported/project
git init
git add -A
git commit -m "initial generation from ChatGPT"
```

Then run the orchestrator's built-in, zero-cost health check against whatever
ChatGPT produced:

```bash
coding-orchestrator --config config.yaml validate
```

This runs your configured validators (`ruff`/`mypy`/`pytest` by default) with no
model call and no cost, and gives you a structured list of what's actually
broken -- exactly the "local environment is the source of truth" signal this
workflow is built around.

### 4. Turn failures into bounded repair tasks

Nothing in this codebase converts a failure log into task files automatically --
that translation is still a planning step, same as the original spec-to-tasks
step. Use ChatGPT for it too (still subscription-cost, not API-metered): feed it
the `validate` output and ask for task files in this repository's task format
(see [Task file reference](../PRODUCTION_USAGE_GUIDE.md#8-task-file-reference)),
one per failure or per small logical cluster, each with narrow `allowed_files`
(1-2 files) and a `validation_commands` entry that actually proves the fix.

### 5. Let the orchestrator close the gaps cheaply

```bash
OPENAI_API_KEY="..." coding-orchestrator --config config.yaml run-all --tasks-dir tasks/
```

Automatic routing is nano/mini-only end to end for this work (see
[Model Roles](MODEL_ROLES.md)) -- there is no automatic path to a gpt-5-tier
model. Independent tasks proceed even if an unrelated task in the same batch is
blocked; a task's own unmet `depends_on` correctly skips it rather than wasting a
call.

### 6. When cheap automation stops being sensible, it stops -- and leaves a handoff

Whenever a task ends without completing (non-convergence, a budget/limit block,
Flex unavailability, or exhausted retries) and `handoff.enabled` is true (the
default), the engine writes a single, self-contained Markdown file to
`logs/handoffs/` -- no model call, no network access, pure local I/O. It
contains: why automation stopped, the task specification, the attempts/
convergence evidence, the latest validation failures, the current repository
diff, a budget snapshot, and this repository's task-file schema so a response
can come back as directly runnable task files.

List what's pending:

```bash
coding-orchestrator --config config.yaml handoff
```

This is read-only and local -- it does not upload anything. Uploading is a
separate, explicit step you trigger, using the same safe `rclone copyto` +
verify pattern as step 2:

```bash
rclone copyto logs/handoffs/T-042-abcd1234-handoff.md \
  "gdrive-jobs:AI-Coding-Orchestrator-Handoffs/T-042-abcd1234-handoff.md"
rclone lsf "gdrive-jobs:AI-Coding-Orchestrator-Handoffs/"
```

(Replace the remote name with whatever `rclone listremotes` shows for your
Google Drive.)

### 7. Escalate manually, on your terms

Open ChatGPT, point it at the uploaded handoff, and ask it to use its strongest
available reasoning to produce corrected files or a new/updated task set. This is
the intended strong-reasoning escalation path -- deliberately **not** an
automatic call to a pricier OpenAI API model. Nothing in this codebase will ever
route a normal task to `coding_optimized_builder`/`frontier_*`/gpt-5 on its own;
those roles remain manual-only, exactly as before this workflow was added.

### 8. Bring the result back and continue

Pull ChatGPT's response back through Google Drive, place any new/updated task
files in your tasks directory (or apply corrected files directly), and run the
orchestrator again. No new machinery is needed for this "return trip" --
`run`/`run-all` already consume whatever is currently in the repository and
tasks directory, regardless of whether it was written by a human, by ChatGPT, or
by a previous orchestrator run.

### 9. Optional final review with Claude Code

Once validation passes and the repository looks substantially complete, use
Claude Code (subscription) to review the whole repository with its large-context
capabilities for issues a task-local repair process structurally can't see:
architectural inconsistencies, missing requirements, weak tests, security
issues. Feed any findings back through the same task-file format and run the
orchestrator again.

## What this workflow does and does not change

- **Unchanged**: automatic routing is still exactly `mechanical_worker`/
  `simple_builder`/`general_builder` on gpt-5-nano/gpt-5-mini, Flex-only, with no
  automatic tier or model escalation, enforced the same way as before (see
  [Cost Control](COST_CONTROL.md)). The same task file format, CLI commands, and
  safety guarantees apply whether the target repository was written by a human,
  generated by ChatGPT, or produced by an earlier orchestrator run.
- **New**: a `handoff` config section and CLI command, and a handoff artifact
  written on non-completing outcomes. This is additive -- disabling it
  (`handoff.enabled: false`) returns the engine to its exact prior behavior on
  those paths (it always still writes the pre-existing escalation/diagnosis-needed
  JSON packages).
- **Still manual, by design, not automated**: uploading a handoff to Drive,
  asking ChatGPT to process it, and bringing the result back. This is
  deliberate -- it's the "manual approval before spending more" gate, just
  aimed at your ChatGPT subscription instead of a pricier API call.

## Why the return trip should stay manual: `validation_commands` is a real trust boundary

Every task file -- regardless of whether a human wrote it or it came back from a
ChatGPT/Drive round trip -- can set `validation_commands`. Those commands are
checked against `tool_permissions.allowlisted_shell_commands` (default: `git`,
`pytest`, `ruff`, `mypy`, `python`, `python3`), and executed via `shlex.split()`
with **no shell** (`subprocess.run(..., shell=False)`), never invoked through a
real shell. That real, verified protection means shell metacharacters
(`;`, `&&`, `|`, backticks, `$()`, redirects) in a command string are never
given shell meaning -- they're just literal argument text to whichever program
runs.

What the allowlist does **not** do is constrain *arguments*. It checks only the
executable name, not what you tell that executable to do -- and `python`/
`python3` accept `-c <code>` or `-m <module>`, which is unrestricted code
execution as the same OS user the orchestrator runs as, no sandboxing of any
kind. A `validation_commands` entry is exactly as trustworthy as a shell
command you'd type yourself, because functionally that's what it is. This is
true today, for hand-written task files, and it doesn't change for
ChatGPT-authored ones.

This is why the return trip in this workflow is deliberately kept manual: a
human is expected to look at a task file (including its `validation_commands`)
before it runs, exactly as they would review a shell command from any other
source before running it. **Do not build unattended or minimal-review ingestion
of externally-generated task files without first addressing this** -- doing so
would mean any content that can get a file into your tasks directory (a
compromised Drive account, a prompt-injected planning session, a
supply-chain-compromised intermediate step) gets arbitrary code execution on
the VPS the moment the orchestrator runs it. No sandboxing, containerization,
or command-content inspection exists in this codebase today, and none is
planned as part of this workflow. Treat this as a hard blocker, not a nice-to-have,
before ever relaxing the manual review step.

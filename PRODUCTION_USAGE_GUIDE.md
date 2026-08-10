# Production Usage Guide

This is a complete, self-contained operational guide to the Cost-Aware AI Coding
Orchestrator. It is written entirely from the committed implementation
(`coding_orchestrator/`), the committed configuration (`config.example.yaml`), and the
committed test suite as of commit history through the 2026-08-07 three-model
simplification. Every claim below was verified against source, not copied from older
documentation. Where behavior is manual-only, disabled, or unimplemented, that is stated
explicitly rather than implied.

---

## 1. Project Overview

### What it does

The orchestrator is a local, single-process Python CLI that runs bounded, supervised
coding tasks against a real git repository:

- Reads a task file (YAML frontmatter + Markdown body, or pure YAML).
- Deterministically classifies the task's type, complexity, and risk from keywords and
  explicit fields (no model call involved in this step).
- Routes the task to one of a small set of model "roles," each bound to a specific
  OpenAI model, reasoning effort, and service tier.
- Builds a bounded text context (task description + current contents of the files the
  task is allowed to touch) and sends it to the OpenAI Responses API.
- Requires the model to return either a unified diff or a structured JSON patch object —
  never a shell command, never free-form instructions to execute.
- Validates the returned patch's shape and file boundaries, applies it with
  `git apply --check` then `git apply`, and runs configured validation commands
  (default: `ruff check .`, `mypy .`, `pytest`).
- On success, commits only the files that are both changed by the patch and in the
  task's `allowed_files` list.
- On any failure, rolls back to a pre-task git checkpoint, restoring the repository
  (including any of your own uncommitted work that existed before the run) exactly as it
  was.
- Tracks every model call's estimated and actual token usage and cost in a local SQLite
  ledger, enforcing project/role/task budget caps before each call.

### What it does not do

- It does not execute model-generated shell commands. All shell execution is through
  fixed, allowlisted, deterministic wrappers (`git`, `pytest`, `ruff`, `mypy`,
  `python`/`python3`) — the model never chooses what command to run.
- It does not support any live model provider other than OpenAI. A `FakeModelProvider`
  exists for tests but is not reachable from the CLI.
- It does not perform automatic multi-tier fallback. Every live call requests the
  `flex` OpenAI service tier; there is no code path, override, or configuration setting
  that can escalate to a higher-priced tier automatically.
- It does not have a working AI diagnosis/reviewer escalation path. The
  `frontier_reviewer`/`frontier_balanced_reviewer` roles exist in configuration and
  pricing, but the code that would call them for a real diagnosis
  (`DiagnosisReviewer.diagnose`) unconditionally raises
  `DiagnosisError("real diagnosis reviewer integration is not implemented")` whenever
  it is asked to run for real (`dry_run=False`). It is also `enabled=False` by default.
  In practice, this path never spends money and never resolves a stuck task by itself.
- It does not run unattended by default: `providers.openai.runtime_enabled` defaults to
  `false`, so a fresh install makes no real API calls until you explicitly opt in.
- It does not have a task-level "workflow" field you set directly — the workflow
  (`explain_code`, `fix_bug`, `write_tests`, etc.) is inferred automatically from the
  task's title/description text.

### Intended users and use cases

A developer who wants a small, auditable, git-checkpointed patch produced by an LLM for
a **bounded, well-scoped** change — a one- or two-file bug fix, a small test file, an
explanation of a function — under **direct human supervision**, with hard cost ceilings
and an automatic rollback if anything goes wrong. It is not designed for unattended
batch operation, large multi-file refactors (those workflows are explicitly disabled),
or as a substitute for code review.

### Current readiness level and known limitations

**Readiness**: the core loop (classify → route → call OpenAI → apply patch → validate →
commit or rollback → record cost) is implemented, unit-tested (132 tests, all passing at
the time of writing — see §9 and §19 for how to reproduce this), and passes `ruff` and
strict `mypy` cleanly. A CI workflow (`.github/workflows/ci.yml`) runs lint, type-check,
tests, and two smoke tests on every push/PR to `main`/`master`.

There is **no evidence in this repository of a real, live OpenAI call ever having been
made and reconciled** — the local budget ledger (`logs/budget.sqlite`) contains zero
rows, and it is git-ignored (never committed). Treat every cost figure in this guide as
a config-derived estimate, not a measured one, until you have run your own real calls
and inspected your own ledger.

Known limitations that remain true in the current code (see §17 for the full list):
diagnosis/reviewer escalation is a non-functional stub; only OpenAI is a real provider;
five of eight defined workflows are disabled; a small number of modules
(`coding_orchestrator/cache/`, `coding_orchestrator/memory/`,
`coding_orchestrator/observability/audit.py`, `metrics.py`, `traces.py`,
`coding_orchestrator/tools/formatter.py`, `linter.py`, `type_checker.py`, `registry.py`,
`filesystem.py`) exist in the tree but are not imported or used anywhere in the active
task-execution path — do not rely on them.

---

## 2. Architecture

### Main components

| Component | File | Responsibility |
|---|---|---|
| `WorkflowEngine` | `orchestrator/engine.py` | Orchestrates the full task lifecycle. |
| `TaskClassifier` | `orchestrator/router.py` | Deterministic (non-model) task type/complexity/risk/workflow classification. |
| `ModelRouter` | `models/router.py` | Coarse complexity/risk → informational label used only for the human-approval gate on `complexity="critical"`. Not the real builder-role router. |
| `BudgetGuard` / `BudgetLedger` | `orchestrator/budget.py` | Pre-call cost estimation, budget enforcement, SQLite ledger persistence and reconciliation. |
| `LimitGuard` | `orchestrator/limits.py` | Enforces context/token/patch/output byte ceilings. |
| `BuilderServiceTierPolicy` | `orchestrator/tier_policy.py` | Tracks bounded Flex-only retry state. |
| `ConvergenceEvaluator` | `orchestrator/convergence.py` | Detects stagnating/diverging retry loops and decides whether to keep retrying, request diagnosis, or block. |
| `DiagnosisReviewer` / `ReviewPacketBuilder` | `orchestrator/diagnosis.py` | Builds a review packet; dry-run placeholder only (see §1). |
| `EscalationManager` | `orchestrator/escalation.py` | Writes JSON escalation packages to disk for human review. |
| `OpenAIProvider` | `models/openai_provider.py` | The only real model provider. Calls the OpenAI Responses API; enforces Flex-only unconditionally before any network call. |
| `FakeModelProvider` | `models/fake_provider.py` | Test-only provider; not reachable from the CLI. |
| `SafePatchApplier` / `parse_builder_output` | `tools/patch.py` | Parses and validates model output as unified diff or structured JSON, then applies with `git apply`. |
| `GitManager` | `tools/git.py` | Checkpoint (stash), rollback, HEAD-change detection, scoped commit. |
| `RepoLock` | `tools/lock.py` | Advisory `flock`-based single-run-per-repo lock. |
| `PatchValidator`, `PermissionValidator`, `SyntaxValidator`, `TestValidator`, `CommandSafetyValidator` | `validators/` | Post-apply validation gates. |
| `JsonlLogger` | `observability/logger.py` | Append-only JSONL event log. |
| `StateStore` | `orchestrator/state.py` | Persists every finished task's full `OrchestratorState` to a JSON file. |
| `TelegramNotifier` | `observability/telegram.py` | Optional alerts on blocked/timeout/error/escalated states. |

### Complete task lifecycle

1. **CLI invocation** (`coding_orchestrator/app.py`): parses `run --task <file>` (or
   `run-all`, `validate`, `report`), loads config (`load_config`), constructs a
   `WorkflowEngine`.
2. **Task load**: `load_task_file` parses YAML frontmatter + Markdown body (or pure
   YAML) into a `TaskSpec`.
3. **Repo lock**: `RepoLock` takes an exclusive `flock` on `<repo>/.orchestrator.lock`
   for the duration of the run. A second concurrent run against the same repo is
   rejected immediately with `final_status="blocked"`.
4. **Initial classification** (`_initial_state`): `TaskClassifier` deterministically
   derives `complexity`, `risk_level`, `task_type` (e.g. `fix_bug`, `write_tests`,
   `explain_code`) and `selected_workflow` from the task's `title`/`description` text
   and explicit fields — **no model call happens here.** `ModelRouter.select_model`
   additionally sets an informational `selected_model` label; if `complexity=="critical"`
   this becomes `"human-approval"` and the task is blocked before any spend.
5. **Git checkpoint** (`GitManager.checkpoint`): records current `HEAD`, and stashes
   away any pre-existing tracked/untracked changes (excluding the orchestrator's own
   log/state/ledger/escalation paths and anything in `git.preserve_untracked_dirs` /
   `preserve_untracked_files`) so the task starts from a clean tree.
6. **Attempt loop** (up to `task.max_attempts`, capped by `timeouts.max_task_runtime_seconds`):
   a. **Builder role selection** (`_select_builder_role`): deterministic rule, not a
      model call — see §5.
   b. **Context construction** (`Workflow.build_context`): task id/title/description,
      complexity, risk, allowed files, output-format rules, and the **current literal
      contents** of every file in `allowed_files` (read directly off disk). On retry,
      prior validation failure output and (if present) diagnosis guidance are appended.
   c. **Context size check** (`LimitGuard.prepare_context`): rejects or trims context
      over `limits.max_context_chars_per_call`.
   d. **Pre-call budget estimate** (`BudgetGuard.estimate_pre_call`): token count is
      approximated as `len(text)//4`; estimated cost is checked against task/role/project
      budgets **before** any network call. A failing check raises `BudgetExceeded` and
      records a `blocked` ledger row — nothing is billed.
   e. **Provider call** (`OpenAIProvider.generate`): unconditionally refuses any role
      that is `live_calls_disabled` or not `service_tier=="flex"`, before checking
      whether the provider is even enabled. If allowed, calls
      `client.responses.create(...)`. Real OpenAI SDK exceptions
      (`RateLimitError`/`APITimeoutError`/`APIConnectionError`/`InternalServerError`/
      `ConflictError`) are mapped to `ProviderTransientError`; auth/permission/not-found
      errors to `ProviderConfigurationError`; everything else to `ProviderError`.
   f. **Flex retry**: a `ProviderTransientError` (or a transient-looking message —
      `429`/timeout/rate-limit text) triggers a bounded retry
      (`inference.builder_service_tier.flex.max_flex_retries`, default 2), always still
      requesting Flex. Exhausting retries raises `FlexUnavailableError` →
      `final_status="flex_unavailable"`.
   g. **Tier mismatch check**: if the provider reports back a `service_tier` different
      from what was requested, the response is **not** accepted — `ServiceTierMismatchError`
      is raised → `final_status="blocked"`.
   h. **Actual usage reconciliation** (`BudgetGuard.record_actual`): real token counts
      from the API response are priced against the role's pricing table and written
      into the same ledger row the estimate created (idempotent UPDATE, never a second
      INSERT).
   i. **Output parsing** (`parse_builder_output`): the model's text must be a JSON
      object matching `BuilderOutput`, or start with `diff --git ` / `--- ` / a fenced
      code block containing one of those. Anything else raises `PatchContractError`,
      which is an unhandled exception in the current attempt (the attempt aborts to
      `task_failed`/rollback, it does not consume a retry the way a validation failure
      does).
   j. **Patch validation and apply** (`SafePatchApplier`): rejects patches that declare
      a file list inconsistent with the actual diff, touch more than
      `validation.max_files_changed` files, delete files without `task.allow_deletes`,
      create/modify symlinks, use absolute paths, escape the workspace, touch forbidden
      paths, or touch files outside `task.allowed_files`. Then `git apply --check -`
      followed by `git apply -`.
   k. **Validation** (`_validate`, always in this fixed order): `CommandSafetyValidator`
      (every configured command's executable is allowlisted) → `PatchValidator`
      (changed-file count and permission/forbidden-path/workspace boundaries) →
      `SyntaxValidator` (`python -m compileall` on changed `.py` files only) →
      `TestValidator` (runs `task.validation_commands` or, if empty,
      `validation.default_commands`, i.e. `ruff check .`, `mypy .`, `pytest`).
   l. **Convergence evaluation** (`ConvergenceEvaluator`): on validation failure, scores
      the attempt against the previous one (fewer validator errors / failing tests /
      changed files / patch size = improvement). Decides to retry the same role, request
      diagnosis, pause/block, or mark non-converging, based on configured thresholds.
   m. On validation **success**: if nothing actually changed (and the workflow isn't a
      non-modifying one like `explain_code`), the task ends `no_change`. Otherwise
      `GitManager.verify_head` confirms `HEAD` hasn't moved since checkpoint (else
      `HeadChangedError` → `failed`), the changed+allowed-file intersection is committed
      (`git add` + `git commit`), the run ends `completed`, and any pre-task stashed
      work is restored on top.
7. **Escalation**: on retry exhaustion, timeout, or an unexpected exception,
   `EscalationManager.should_escalate` decides (based on `task.escalation_allowed`,
   remaining attempts, risk/complexity, or the presence of validation errors) whether to
   write a JSON escalation package to `logs/escalations/<task_id>-escalation.json` for a
   human to read; the task ends `escalated` or `failed`.
8. **Finish**: `StateStore.append` persists the full `OrchestratorState` (keyed by a
   fresh UUID `request_id` per run) into `logs/state.json`; a JSONL event is appended to
   `logs/orchestrator.jsonl`; a Telegram alert is sent if enabled and the status
   warrants one.

### Model routing, provider calls, and budget accounting — see §5 and §6 for full detail.

### Task statuses (`OrchestratorState.final_status`)

| Status | Meaning |
|---|---|
| `pending` | Initial state before a run starts (not a terminal status). |
| `running` | Set while an attempt is in progress (not terminal in persisted output). |
| `completed` | A real patch was applied, validated, and committed (or a non-modifying workflow like `explain_code` finished cleanly). The only status meaning "it worked." |
| `dry_run` | The provider refused to run for a configuration reason (disabled, no runtime_enabled, missing API key, SDK not installed) — no model was called, nothing changed. |
| `no_change` | The provider was called but produced no usable patch for a workflow that requires one. |
| `blocked` | Budget, limit, human-approval, concurrent-lock, or service-tier-mismatch gate stopped the task before/without a normal completion. |
| `flex_unavailable` | Flex capacity never succeeded after bounded retries; no other tier was used; repo left untouched. |
| `timeout` | The task exceeded its runtime budget. |
| `failed` | An unhandled/unexpected error occurred (patch contract violation, commit failure, HEAD moved, provider error not otherwise handled, etc.). |
| `escalated` | Retries/attempts exhausted (or diagnosis unavailable) and an escalation package was written for human review. |
| `skipped` | Only produced by `run-all`, for a task whose `depends_on` includes a task that never completed. |

The CLI's exit code (`run`/`run-all`) is non-zero unless every task actually
`completed` (or was legitimately `skipped`).

---

## 3. Installation

**Supported Python version**: `>=3.11` (`pyproject.toml`, `requires-python = ">=3.11"`).
The repository's own `.mypy_cache` shows it was developed against 3.11.

```bash
# 1. Clone/enter the repository
cd /path/to/cost-aware-ai-coding-orchestrator

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # or use .venv/bin/python3 / .venv/bin/pip directly

# 3. Install the package with dev dependencies (editable install)
.venv/bin/pip install -e ".[dev]"

# 4. For a fully reproducible, pinned dependency set, also install the lockfile
.venv/bin/pip install -r requirements-lock.txt
```

Runtime dependencies (`pyproject.toml`): `openai>=2.0,<3.0`, `pydantic>=2.6,<3.0`,
`PyYAML>=6.0,<7.0`. Dev dependencies: `pytest>=8.0,<10.0`, `ruff>=0.4,<1.0`,
`mypy>=1.9,<3.0`.

**Required system tools**: `git` must be installed and on `PATH` — the orchestrator
shells out to the real `git` binary for every checkpoint, diff, apply, and commit
operation; there is no pure-Python git fallback. Python's own interpreter is used for
`ruff`/`mypy`/`pytest` validation commands, which must also be installed (they are, via
the `[dev]` extra above).

### Verification commands after installation

```bash
# Confirm the CLI entry point resolves
.venv/bin/coding-orchestrator --help
# or, equivalently, without relying on the installed script:
.venv/bin/python3 -m coding_orchestrator.app --help

# Confirm the package imports cleanly
.venv/bin/python3 -c "import coding_orchestrator.app"

# Confirm the test suite, linter, and type checker pass
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy .

# Confirm the CLI's report path works with no prior runs (prints empty state)
.venv/bin/python3 -m coding_orchestrator.app report
```

At the time this guide was written, `pytest -q` reported **132 passed**, `ruff check .`
reported **All checks passed!**, and `mypy .` reported **Success: no issues found in 63
source files**. These are the exact commands CI (`.github/workflows/ci.yml`) runs on
every push/PR to `main`/`master`, plus an import smoke test and a `report` smoke test.

---

## 4. Real OpenAI Setup

### Exact environment variable required

`OPENAI_API_KEY` (the name is itself configurable via
`providers.openai.api_key_env_var`, but `OPENAI_API_KEY` is the default and what
`config.example.yaml` ships).

### Safe examples for exporting it temporarily

Export it only in your current shell session — never write it into a file that could be
committed:

```bash
# Interactive shell, current session only (not persisted to any file)
export OPENAI_API_KEY="sk-...your-real-key..."

# Or, one-off for a single command, without polluting your shell's exported vars:
OPENAI_API_KEY="sk-...your-real-key..." .venv/bin/coding-orchestrator run --task tasks/example_task.md
```

### How to avoid storing or committing the key

- Never put it in `config.yaml`, `config.example.yaml`, any task file, any log, or any
  commit message. The config schema only ever holds the **name** of the environment
  variable (`api_key_env_var`), never a key value.
- If you use a `.env` file for convenience, `.gitignore` already excludes `.env`, and
  `validation.forbidden_paths` (`.env`, `secrets`, `credentials`, `tokens`, `~/.ssh`,
  `/etc/`) means the orchestrator itself will refuse to let a model-generated patch
  touch such a file even inside the repo it's operating on.
- Do not paste the key into a task's `title`/`description` — that text is sent verbatim
  to OpenAI as part of the prompt and is written into `logs/orchestrator.jsonl` and
  `logs/state.json`.

### Provider configuration required for live calls

In `config.yaml` (copy from `config.example.yaml`):

```yaml
providers:
  openai:
    enabled: true            # already true by default
    runtime_enabled: true    # MUST be flipped to true; false by default
    api_key_env_var: "OPENAI_API_KEY"
```

Both `enabled: true` **and** `runtime_enabled: true` are required —
`OpenAIProvider.generate` checks both independently and raises
`ProviderConfigurationError` (surfaced as `final_status="dry_run"`) if either is false,
if the API key env var is unset, or if the `openai` Python package isn't installed.

### How to confirm authentication safely

Do not paste your key anywhere for this. Instead, run a real, tiny, cheap task (see §10
for the full cautious first-run procedure) and inspect the result:

```bash
OPENAI_API_KEY="sk-...your-real-key..." .venv/bin/coding-orchestrator run --task tasks/example_task.md
```

- `final_status: "completed"` (or a validation/patch failure with a real, non-dry-run
  builder response) confirms authentication worked.
- `final_status: "dry_run"` with `tool_results.builder_warning` mentioning the API key
  environment variable means authentication was never attempted (config problem, not a
  credential problem) — see §15.
- A `ProviderConfigurationError` message containing `"rejected by the API"` (mapped from
  `openai.AuthenticationError`/`PermissionDeniedError`/`NotFoundError`) means the key was
  sent but rejected.

### The key must never be pasted into config files, logs, tasks, documentation, or commits

This is a hard rule, not a suggestion. If you ever suspect a key was pasted into any
tracked file, rotate that key with your provider immediately and remove it from git
history — do not just delete it in a new commit (the old commit still contains it).

---

## 5. Production Model Configuration

All figures below come directly from `coding_orchestrator/config.py`
(`ModelRoleRegistry`, `PricingSettings`) and are mirrored in `config.example.yaml`.

| Role | Model | Reasoning effort | Service tier | Max output tokens (role cap) | Pricing entry key | Auto-reachable? |
|---|---|---|---|---|---|---|
| `mechanical_worker` | `gpt-5-nano` | `low` | `flex` | 1,500 | `mechanical_worker:flex` | **Yes** |
| `classification_worker` | `gpt-5-nano` | `low` | `flex` | 1,000 | `classification_worker:flex` | No — never invoked by the engine at all (see below) |
| `simple_builder` | `gpt-5-mini` | `low` | `flex` | 3,000 | `simple_builder:flex` | **Yes** |
| `general_builder` | `gpt-5-mini` | `medium` | `flex` | 4,000 (role) / 6,000 (pricing cap) | `general_builder:flex` | **Yes** |
| `coding_optimized_builder` | `gpt-5` | `medium` | `flex` | 8,000 | `coding_optimized_builder:flex` | No — not returned by `_select_builder_role`; manual/direct role selection only |
| `frontier_balanced_reviewer` | `gpt-5` | `high` | `flex` | 6,000 | `frontier_balanced_reviewer:flex` | No — diagnosis-only path, and diagnosis is a non-functional stub |
| `frontier_reviewer` | `gpt-5` | `high` | `flex` | 8,000 | `frontier_reviewer:flex` | No — same as above; this is `diagnosis.model_role`'s default target |
| `emergency_pro_reviewer` | `gpt-5` | `high` | `flex` | 8,000 | `emergency_pro_reviewer:flex` | No — `manual_approval_required=true` |
| `legacy_reasoning_fallback` | `gpt-5` | `medium` | `flex` | 4,000 | `legacy_reasoning_fallback:flex` (+`:default`, unreachable) | No — manual role selection only |
| `mini_legacy_fallback` | `gpt-5-mini` | `low` | `flex` | 4,000 | `mini_legacy_fallback:flex` (+`:default`, unreachable) | No — manual role selection only |
| `frontier_coding_reviewer` | `gpt-5.3-codex` | `high` | `default` | 8,000 | `frontier_coding_reviewer:default`/`:priority` | **Never** — `live_calls_disabled=true` |
| `non_reasoning_instruction_follower` | `gpt-4.1` | `none` | `default` | 4,000 | `non_reasoning_instruction_follower:default` | **Never** — `live_calls_disabled=true` |

**Automatically reachable in practice**: only three roles —
`mechanical_worker`, `simple_builder`, `general_builder` — via
`WorkflowEngine._select_builder_role` (`orchestrator/engine.py`):

```
if retry_count > 0:                                          -> general_builder
elif risk == "high" or complexity in {hard, critical}:        -> general_builder
elif complexity in {trivial, simple}
     and len(allowed_files) <= 1
     and validation is configured
     and task_type in {write_tests, explain_code}:            -> mechanical_worker
elif complexity in {trivial, simple} and len(allowed_files) <= 2: -> simple_builder
else:                                                          -> general_builder
```

Every other role is manual-only (reachable only by code that explicitly resolves that
role name — there is no CLI flag or task field to select one), disabled
(`live_calls_disabled=true`, refused unconditionally by `OpenAIProvider.generate`
regardless of any other setting), or gated behind the non-functional diagnosis path or
`manual_approval_required`.

`classification_worker` deserves a specific callout: it is fully configured, priced,
and Flex-verified, but `TaskClassifier.classify_task_type`/`classify_complexity`/
`classify_risk` (`orchestrator/router.py`) are pure deterministic Python — keyword
matching and field lookups — with no model call anywhere in them. `classification_worker`
is not invoked by any code path in this repository today. It exists for a possible
future/manual summarization workload.

### The Flex-only policy

Every live-callable role must default to `service_tier="flex"`, declare
`fallback_service_tier: null`, and have a `<role>:flex` pricing entry — enforced twice:

1. **Config load** (`AppConfig._enforce_flex_only_policy`, a pydantic validator):
   rejects the whole configuration outright if any live-callable role violates this.
2. **The call boundary** (`OpenAIProvider.generate`): checked before enabled/API-key
   checks, unconditionally, for every request, with no override parameter anywhere.

### Retry behavior and Flex unavailability

On a transient error (SDK `RateLimitError`/`APITimeoutError`/`APIConnectionError`/
`InternalServerError`/`ConflictError`, or a message containing `429`/timeout/rate-limit
text), the engine retries — **still requesting Flex** — up to
`inference.builder_service_tier.flex.max_flex_retries` times (default 2). Exhausting
retries ends the task `flex_unavailable`; the repository is left exactly as it was
before the task started. There is no automatic escalation to a paid higher tier.

### Tier mismatch handling

If OpenAI's response reports a `service_tier` different from what was requested, that
response is never treated as a success: the discrepancy is recorded
(`tool_results.service_tier_mismatch`), and the task ends `blocked`.

---

## 6. Cost Control

### How estimates are calculated (`BudgetGuard.estimate_pre_call`)

- Input tokens: `max(1, len(prompt_text) // 4)` — a crude character-count heuristic, not
  a real tokenizer.
- Output tokens: the role's pricing-table `max_output_tokens`, capped further by the
  role's own `max_output_tokens` setting if lower.
- Cost: `(input_tokens / 1e6) * input_usd_per_1m_tokens + (output_tokens / 1e6) *
  output_usd_per_1m_tokens`, using the `<role>:flex` pricing entry.
- This estimate is **always a worst-case ceiling** for output (it assumes the maximum
  possible output every time), used purely to gate spend before the call is made.

### How actual usage/cost is reconciled

After a real call, `BudgetGuard.record_actual` takes the real `input_tokens`/
`output_tokens` from the OpenAI response's `usage` object and re-prices them against the
same `<role>:flex` table, then `BudgetLedger.record_actual_usage` performs an idempotent
`UPDATE` of the specific ledger row the pre-call estimate inserted (matched by
project/attempt/role/task, most recent un-reconciled row) — never a second `INSERT`, so
actual spend is never double-counted against its own estimate. Reported spend
(`spend_for_project`/`_role`/`_task`) always prefers `actual_cost_usd` and falls back to
`estimated_total_cost_usd` only for rows that never got reconciled (e.g. blocked before
calling, or the call itself errored).

### Budgets enforced (`BudgetGuard.check_pre_call`, before every call)

- **Task budget**: `min(task.max_cost_usd, budget.max_task_cost_usd)` — a single call's
  estimate can't exceed this, and cumulative task spend can't exceed `task.max_cost_usd`.
- **Project budget**: cumulative project spend + this estimate can't exceed
  `budget.project_total_budget_usd`.
- **Role budget**: cumulative spend for that specific role can't exceed
  `budget.role_budgets_usd[role]` (falls back to `project_total_budget_usd` if the role
  isn't listed).
- Any violation raises `BudgetExceeded`, records a `blocked` ledger row, and the task
  ends `final_status="blocked"` — no call is made.
- Attempt-level ceiling: indirectly bounded by `task.max_attempts` (default 2) and
  `timeouts.max_task_runtime_seconds`/`max_attempt_runtime_seconds`, not a separate cost
  field.

### Ledger location and schema

Default path: `logs/budget.sqlite`, resolved relative to `repo_path` (never the
process's current working directory), and always excluded from git checkpoint/
stash/rollback regardless of the target repo's `.gitignore`.

Table `budget_events` (SQLite): `id`, `project_id`, `task_id`, `attempt_id`,
`model_role`, `provider`, `model`, `inference_tier`, `estimated_context_chars`,
`estimated_input_tokens`, `estimated_output_tokens`, `estimated_input_cost_usd`,
`estimated_output_cost_usd`, `estimated_total_cost_usd`, `actual_input_tokens`
(nullable until reconciled), `actual_output_tokens` (nullable), `actual_cost_usd`
(nullable), `timestamp`, `status` (`estimated`/`completed`/`blocked`/
`*_limit_exceeded`), `requested_service_tier`, `actual_service_tier`,
`fallback_occurred` (always `0` under the strict Flex-only policy — its presence lets
you positively confirm no fallback ever happened).

Inspect it directly (read-only) with:

```bash
python3 -c "
import sqlite3
con = sqlite3.connect('logs/budget.sqlite')
for row in con.execute('SELECT id, task_id, model_role, model, status, estimated_total_cost_usd, actual_cost_usd FROM budget_events ORDER BY id DESC LIMIT 20'):
    print(row)
"
```

### How to read the budget report

```bash
.venv/bin/coding-orchestrator report
```

Returns JSON with `budget.project_total_spend_usd`, `project_total_remaining_usd`,
`role_spend_usd`/`role_remaining_usd` per role, `blocked_calls`, `limit_failures`,
`calls_by_service_tier`/`estimated_cost_by_service_tier_usd` (should show only
`"flex"`), and `service_tier_fallbacks` (always `0`, structurally, under this policy).

### Example low/typical/high costs for small tasks

There is no observed production usage to calibrate against (see §1) — the figures below
are derived purely from the configured Flex pricing and role token caps, treating all
input as uncached (a conservative upper bound; real repeated-context caching at
$0.0025–$0.0625 per 1M tokens would lower this).

| Scenario | Assumptions | Estimated cost |
|---|---|---|
| **Low** — one trivial one-file task | `mechanical_worker` (gpt-5-nano), ~4k input / ~0.6k output tokens | **~$0.0002** per task |
| **Typical** — one small-to-medium task, no retries | `simple_builder`/`general_builder` (gpt-5-mini), ~6k–20k input / ~0.8k–1.8k output tokens | **~$0.002–0.004** per task |
| **High** — a harder task with a validation retry, or a manually-selected `coding_optimized_builder` (gpt-5) escalation | gpt-5-mini with one retry (~2x the typical cost), or a single gpt-5 call at ~40k input / ~5k output tokens (~$0.05) | **~$0.01–0.05** per task |

For a full active-development *hour* (mixed classification-free routing, several tasks,
some retries), a rough estimate is **~$0.01–0.05/hour** under pure automatic routing
(nano/mini only), rising toward **~$0.15–0.25/hour** if the operator manually escalates
one or two hard tasks per hour to `coding_optimized_builder` (gpt-5) — gpt-5 costs
roughly 5–20x more per token than gpt-5-nano/mini and dominates total spend whenever
it's used, even though automatic routing never reaches it on its own.

### Why cost per successful task matters more than price per token

A cheap model that fails validation repeatedly (consuming multiple attempts, each
independently billed) or produces an unusable patch can cost more **per completed
task** than a pricier model that succeeds on the first attempt. The per-token price in
`pricing.roles` is not the number that matters operationally — `report`'s
`role_spend_usd` divided by the count of tasks that actually reached `completed` is.
This repository's own internal benchmark (documented in
`docs/OPERATIONAL_HARDENING_CHANGES.md`) used exactly this metric to choose the current
three-model routing.

### Recommendations for keeping usage inexpensive

- Keep automatic routing as-is (nano/mini only) — never manually invoke
  `coding_optimized_builder` or any `gpt-5`-tier role unless a task has already failed
  under `general_builder` and genuinely needs stronger reasoning.
- Keep `allowed_files` to 1–2 files per task; context size (and thus input cost) scales
  directly with how many files' full contents get embedded in the prompt.
- Keep `task.max_attempts` low (the default is 2) — each retry is a full independent
  billed call.
- Set a tight `task.max_cost_usd` per task (default `0.06`) rather than relying only on
  the global project budget.
- Never enable the diagnosis path (`diagnosis.enabled: true`) expecting it to save
  money by auto-resolving stuck tasks — it cannot make a real call today (§1); enabling
  it only adds a pre-call budget/limit check on a call that will never succeed.

---

## 7. Configuration Reference

Config is loaded from `config.yaml` in the current working directory by default
(`--config <path>` overrides), or `AppConfig()` defaults if no file exists. Unknown YAML
keys are silently ignored (pydantic v2 default `extra="ignore"`), so a typo in a field
name will not raise an error — verify with `report`/`validate` after editing.

| Section.field | Purpose | Valid values | Default | Safe production recommendation | Consequence of changing |
|---|---|---|---|---|---|
| `repo_path` | Target git repository root. | Any path | `"."` | Absolute path to the exact repo you intend to modify. | All relative data paths (logs/state/ledger/escalations) resolve against this, not the CLI's CWD. |
| `state_path` | Where finished task states are persisted. | Path | `logs/state.json` | Leave default; always excluded from git operations. | Losing this file loses `report`'s task history (ledger/logs are separate and unaffected). |
| `log_path` | JSONL event log. | Path | `logs/orchestrator.jsonl` | Leave default. | — |
| `escalations_path` | Directory for escalation JSON packages. | Path | `logs/escalations` | Leave default. | — |
| `providers.openai.enabled` | Master on/off for the OpenAI provider. | bool | `true` | `true` | If `false`, every call is a `dry_run`. |
| `providers.openai.runtime_enabled` | Whether real (billed) calls are allowed. | bool | `false` | `false` until you deliberately opt in per §4 | This is the actual "go live" switch. |
| `providers.openai.api_key_env_var` | Name of the env var holding the API key. | string | `OPENAI_API_KEY` | Leave default unless you have a reason to rename it. | Never put the key itself here. |
| `providers.openai.request_timeout_seconds` | Per-request SDK timeout. | int seconds | `300` | `300` | Too low risks spurious `ProviderTransientError`s on long generations. |
| `providers.openai.max_retries` | SDK-level retries on transient errors, still Flex. | int | `2` | `2` | `0` removes SDK-level resilience (the engine's own Flex-retry logic in §5 still applies independently). |
| `model_aliases.*` | Maps a short alias name to a real model id. | string | see §5 table | Do not change without re-verifying Flex support live. | Retargeting an alias changes every role that references it. |
| `model_roles.roles.<role>.model_alias` | Which alias (model) a role uses. | string, must exist in `model_aliases` | see §5 | Leave as shipped. | Changing this changes cost and capability for that role. |
| `model_roles.roles.<role>.reasoning_effort` | Requested reasoning depth. | `"none"`/`"low"`/`"medium"`/`"high"`/`"xhigh"` (type-level); **the live API only accepts `minimal`/`low`/`medium`/`high`** | see §5 | Never set `"none"` for a live-callable role — live-verified to be rejected by the API for every gpt-5-family model. | `"xhigh"` is additionally gated by `policies.allow_xhigh_reasoning` (default `false`). |
| `model_roles.roles.<role>.default_service_tier` | Requested tier. | `"default"`/`"flex"`/`"priority"`/`"batch"`/`"fast"` (type-level) | `flex` for every live role | Must stay `flex` for any role you want to actually call — enforced at config load. | Any non-`flex` value on a live role fails config validation. |
| `model_roles.roles.<role>.fallback_service_tier` | Automatic tier fallback. | must be `null` for any live role | `null` | Leave `null` — there is no fallback mechanism left to configure. | A non-null value fails config validation. |
| `model_roles.roles.<role>.max_output_tokens` | Per-call output cap for this role. | int | see §5 | Leave as shipped; lower only if you understand truncation risk for diffs. | Too low can truncate a patch mid-diff, causing a parse/apply failure. |
| `model_roles.roles.<role>.max_attempts` | Retries at the role level (informational; the real retry loop is `task.max_attempts`). | int | 1–2 | Leave as shipped. | — |
| `model_roles.roles.<role>.live_calls_disabled` | Hard-disables real calls for this role. | bool | `true` only for `frontier_coding_reviewer`, `non_reasoning_instruction_follower` | Never set `true` on a role you intend to use; never set `false` on the two disabled roles without first live-verifying Flex support for their models. | Provider refuses unconditionally when `true`. |
| `model_roles.roles.<role>.manual_approval_required` | Requires human sign-off before calling. | bool | `true` only for `emergency_pro_reviewer` | Leave as shipped. | — |
| `pricing.roles."<role>:<tier>"` | Per-1M-token rates used for estimate/reconciliation. | `ModelPricing` object | see §5 | Keep in sync with real OpenAI pricing; re-verify dates periodically. | Stale/wrong pricing silently mis-estimates and mis-reports cost — it does not affect what you're actually billed by OpenAI. |
| `policies.allow_frontier_direct_patch` | Allows `frontier_*` roles to bypass diagnosis-only mode and patch directly. | bool | `false` | `false` | Currently irrelevant in practice since frontier roles aren't auto-reachable. |
| `policies.allow_xhigh_reasoning` | Gate for `reasoning_effort="xhigh"`. | bool | `false` | `false` | No shipped role currently uses `xhigh`. |
| `policies.allow_emergency_pro_reviewer` | Additional gate referenced by policy, separate from the role's own `manual_approval_required`. | bool | `false` | `false` | — |
| `budget.max_task_cost_usd` | Global per-call estimate ceiling (also compared against `task.max_cost_usd`, whichever is lower wins). | float USD | `0.10` | Lower for production safety, e.g. `0.02`–`0.05`. | Too low can block legitimate `general_builder`/`coding_optimized_builder` calls before they're even attempted. |
| `budget.project_total_budget_usd` | Hard cap across the whole `project_id`. | float USD | `5.0` | Set deliberately per project/environment — this is your real ceiling. | Exceeding it blocks all further calls for that `project_id` until raised or the ledger/project_id changes. |
| `budget.stop_threshold_ratio` | Soft early-stop fraction of project budget (used by `can_spend`, the initial gate). | 0–1 | `0.9` | Leave default or lower for more headroom. | — |
| `budget.role_budgets_usd` | Per-role cumulative cap. | dict[str, float] | see §5/6 | Set `mechanical_worker`/`simple_builder`/`general_builder` deliberately; other roles are moot while unreachable. | — |
| `budget.ledger_path` | SQLite ledger file. | path | `logs/budget.sqlite` | Leave default. | — |
| `budget.project_id` | Logical project bucket for budget accounting. | string | `"default"` | Use a distinct id per repository/environment if you share one ledger file across projects. | Spend is scoped per `project_id`, not per repo path. |
| `limits.max_input_tokens_per_call` | Hard pre-call input token ceiling. | int | `32000` | Leave default or lower. | Estimated-input over this blocks the call (`context_limit_exceeded`). |
| `limits.max_output_tokens_per_call` | Hard pre-call output token ceiling. | int | `4000` | Leave default. | — |
| `limits.max_context_chars_per_call` | Hard character ceiling on the built prompt. | int | `128000` | Leave default. | `context_over_limit_policy` decides reject vs. trim. |
| `limits.context_over_limit_policy` | What to do when context is too large. | `"reject"`/`"trim"` | `reject` | `reject` (fail loud rather than silently truncate a prompt a model will act on). | `"trim"` keeps only the tail of the context. |
| `limits.max_patch_bytes` | Max total patch size. | int bytes | `256000` | Leave default. | — |
| `timeouts.max_task_runtime_seconds` | Wall-clock cap for one task run (all attempts). | int seconds | `600` | Lower for production tasks you expect to be small. | Exceeding it raises `TimeoutExceeded` → `final_status="timeout"`. |
| `timeouts.max_attempt_runtime_seconds` | Cap for a single subprocess call (validation commands, patch apply). | int seconds | `300` | Leave default unless your test suite is slow. | — |
| `retries.max_retries` | Present in config but not read anywhere in the active engine path — the real retry bound is `task.max_attempts`. | int | `1` | Ignore; use `task.max_attempts` instead. | No effect observed in current code. |
| `validation.max_files_changed` | Max files a patch may touch. | int | `5` | Lower to `1`–`2` for tightly scoped production tasks. | Patches touching more files are rejected. |
| `validation.forbidden_paths` | Substrings that block a path outright. | list[str] | `/etc/`, `~/.ssh`, `.env`, `secrets`, `credentials`, `tokens` | Leave default; extend if your repo has other sensitive paths. | Matching is substring-based on the normalized path (see §12). |
| `validation.default_commands` | Fallback validation commands when a task doesn't specify its own. | list[str] | `ruff check .`, `mypy .`, `pytest` | Leave default for Python repos; every command's executable must be in `tool_permissions.allowlisted_shell_commands`. | An empty task-level list plus a repo with no matching tooling will fail these commands. |
| `tool_permissions.allowlisted_shell_commands` | Executables the orchestrator is ever allowed to run. | list[str] | `git`, `pytest`, `ruff`, `mypy`, `python`, `python3` | Do not add arbitrary executables; every validation command's first token must be here. | Adding an unvetted executable widens the trusted execution surface. |
| `git.require_clean_worktree` | Refuse to start if the target repo has tracked dirty changes. | bool | `false` | `true` for production repositories you care about. | `false` allows starting on a dirty tree (it still gets stashed and restored). |
| `git.preserve_untracked_dirs` / `preserve_untracked_files` | Paths excluded from stash/clean regardless of `.gitignore`. | list[str] | `logs`, `.cache`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache` / `.gitignore` | Leave default; add any other build-cache dirs your repo generates. | — |
| `inference.builder_service_tier.default_tier` | Fixed at `flex`; not a real choice. | `"flex"` (Literal, only value) | `flex` | N/A — cannot be changed. | — |
| `inference.builder_service_tier.flex.max_flex_retries` | Bounded Flex-only retries on transient failure. | int | `2` | `2`–`3`. | Higher delays a `flex_unavailable` outcome; lower fails faster. |
| `diagnosis.enabled` | Turns on the (non-functional-for-real-calls) diagnosis path. | bool | `false` | Leave `false` — enabling it does not add working functionality (§1). | — |
| `diagnosis.dry_run` | Whether diagnosis returns a placeholder or attempts (and fails) a real call. | bool | `true` | Leave `true` if `enabled` is ever turned on. | `dry_run=false` makes `DiagnosisReviewer.diagnose` raise unconditionally. |
| `diagnosis.model_role` | Which role's pricing the (non-functional) diagnosis path's pre-call cost *estimate* is computed against. | string, must name an existing role | `general_builder` (as of 2026-08-10; previously `frontier_reviewer`) | Leave as a nano/mini-tier role — never point this at a gpt-5-tier role. | Only affects cost estimation for a call that never actually reaches the provider. |
| `handoff.enabled` | Whether a local handoff artifact is written when a task ends without completing. | bool | `true` | `true` — this is the recommended escalation-visibility mechanism (added 2026-08-10). | `false` returns to prior behavior on those paths (existing escalation/diagnosis-needed JSON packages are still written either way). |
| `handoff.output_dir` | Where handoff Markdown files are written. | path | `logs/handoffs` | Leave default; git-ignored and stash/clean-protected like the other data paths. | — |
| `handoff.max_diff_chars` / `max_validation_chars` / `max_context_chars` | Bound the size of the embedded diff/validation/context sections in each handoff file. | int | `20000` / `8000` / `4000` | Leave default; raise only if you find yourself needing more diff context in a specific handoff. | Oversized sections are truncated to their tail, not rejected. |
| `telegram.enabled` | Turns on Telegram alerting for blocked/timeout/error/escalated states. | bool | `false` | Enable only if you've set up a bot and both env vars below. | — |
| `telegram.bot_token_env_var` / `chat_id_env_var` | Env var names for Telegram credentials. | string | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Never put the actual token/chat id in config. | Missing vars: warns (default) or raises, per `missing_env_policy`. |

**Concurrency/locking**: not a config section — it's always-on (`RepoLock` in
`tools/lock.py`), an OS-level `flock` on `<repo>/.orchestrator.lock`, with no
configuration knob to disable it.

**Cache**: `coding_orchestrator/cache/cache.py` (`HashCache`) exists but is not wired
into the engine or any config section — there is no cache to configure or rely on.

---

## 8. Task File Reference

### Format

Either YAML frontmatter delimited by `---` with a Markdown body (the body becomes
`description` if `description` isn't set in the frontmatter), or a pure YAML file
(`load_task_file` in `coding_orchestrator/schemas.py`).

### Fields (`TaskSpec`)

| Field | Required | Type | Default | Notes |
|---|---|---|---|---|
| `id` | **yes** | string | — | Used in the commit message (`"<id>: <title>"`) and escalation filenames. |
| `title` | **yes** | string | — | Feeds task-type/workflow classification keyword matching. |
| `description` | no | string | `""` (or the Markdown body, for frontmatter files) | Also feeds classification keywords — avoid unrelated words like "test" if you don't want it force-classified as `write_tests`. |
| `complexity` | no | `trivial`/`simple`/`medium`/`hard`/`critical` | `simple` | Directly affects builder-role routing (§5) and, for `critical`, forces `requires_human_approval=true` (task blocked, no call made). |
| `risk` | no | `low`/`medium`/`high` | `low` | `high` forces `general_builder` regardless of complexity/file count. |
| `depends_on` | no | list[str] of other task `id`s | `[]` | Only meaningful with `run-all`; a task is `skipped` if any dependency didn't `complete`. |
| `allowed_files` | no | list[str], repo-relative paths | `[]` | The **only** files a patch may touch and the only files ever staged for commit. An empty list with a modifying workflow will make every patch attempt fail permission validation. |
| `max_attempts` | no | int ≥ 1 | `2` | The real retry bound (not `retries.max_retries`). |
| `max_runtime_seconds` | no | int ≥ 1 | `480` | Capped by `timeouts.max_task_runtime_seconds`. |
| `max_cost_usd` | no | float > 0 | `0.06` | Capped by `budget.max_task_cost_usd` (lower of the two wins). |
| `escalation_allowed` | no | bool | `true` | If `false`, a failing task ends `failed` rather than writing an escalation package. |
| `allow_deletes` | no | bool | `false` | Must be `true` for a patch that deletes a file to be accepted. |
| `validation_commands` | no | list[str] | `[]` | Falls back to `validation.default_commands` if empty. Every command's first token must be allowlisted. |

There is **no `workflow` or `task_type` field** — these are inferred automatically by
`TaskClassifier` from `title`/`description` keywords: `"test"` → `write_tests`;
`"bug"`/`"fix"`/`"error"`/`"failure"` → `fix_bug`; `"explain"`/`"document"` →
`explain_code`; `"security"` → `security_review` (disabled workflow); `"dependency"` →
`dependency_update` (disabled); `"refactor"` → `small_refactor`/`large_refactor`
(both disabled) depending on complexity; anything else → `fix_bug`. Keyword checks run
in that order — a description containing `"test"` anywhere will be classified
`write_tests` even if the task is really a bug fix, so word your title/description
carefully.

### Examples

**Explain code** (non-modifying; `allowed_files` may be empty):

```markdown
---
id: T-explain-001
title: Explain the retry logic in pkg/retry.py
complexity: trivial
risk: low
allowed_files: []
max_attempts: 1
max_runtime_seconds: 120
max_cost_usd: 0.01
escalation_allowed: true
validation_commands:
  - "python3 -c 'pass'"
---
Explain what pkg/retry.py's retry() function does and why it backs off exponentially.
```

**Fix a bug** (avoid the word "test" in title/description so it isn't misclassified):

```markdown
---
id: T-fix-001
title: Correct off-by-one error in pkg/calc.py
complexity: simple
risk: low
allowed_files:
  - pkg/calc.py
max_attempts: 2
max_runtime_seconds: 180
max_cost_usd: 0.02
escalation_allowed: true
validation_commands:
  - "python3 -m pytest tests/test_calc.py -q"
---
The subtract() function in pkg/calc.py returns a + b instead of a - b. Correct the
arithmetic operator so the function behaves as its name implies.
```

**Write tests**:

```markdown
---
id: T-tests-001
title: Add tests for is_palindrome
complexity: trivial
risk: low
allowed_files:
  - tests/test_stringutils.py
max_attempts: 2
max_runtime_seconds: 180
max_cost_usd: 0.02
escalation_allowed: true
validation_commands:
  - "python3 -m pytest tests/test_stringutils.py -q"
---
Add pytest test cases in tests/test_stringutils.py covering pkg/stringutils.py's
is_palindrome() for empty strings, single characters, and mixed case.
```

**Small refactor** — note this workflow is currently **disabled**
(`Workflow("small_refactor", ..., enabled=False)`); a task whose title/description
triggers this classification will be blocked with `requires_human_approval=true` before
any call is made. There is no supported way to run a refactor task today.

**Multi-file change** (two files, still routes to `simple_builder` since
`len(allowed_files) <= 2`, or to `general_builder` if complexity/risk force it):

```markdown
---
id: T-fix-002
title: Correct the running total bug across processor and validators
complexity: simple
risk: low
allowed_files:
  - pkg/processor.py
  - pkg/validators.py
max_attempts: 2
max_runtime_seconds: 240
max_cost_usd: 0.03
escalation_allowed: true
validation_commands:
  - "python3 -m pytest tests/test_processor.py -q"
---
sum_positive() in pkg/processor.py assigns instead of accumulating, so validators.py's
downstream check always sees only the last positive value. Correct the accumulation.
```

**Task with dependencies** (for `run-all`; `T-part-2` only runs if `T-part-1`
completed):

```yaml
id: T-part-1
title: Add a validate_email helper
complexity: simple
risk: low
allowed_files: ["pkg/validators.py"]
max_attempts: 2
max_cost_usd: 0.02
validation_commands: ["python3 -m compileall pkg/validators.py"]
description: Add a validate_email(addr) function to pkg/validators.py.
```

```yaml
id: T-part-2
title: Use validate_email in the signup handler
depends_on: ["T-part-1"]
complexity: simple
risk: low
allowed_files: ["pkg/signup.py"]
max_attempts: 2
max_cost_usd: 0.02
validation_commands: ["python3 -m compileall pkg/signup.py"]
description: Call the new validate_email helper from pkg/signup.py before accepting input.
```

---

## 9. CLI Reference

The only entry point is `coding_orchestrator/app.py` (installed as `coding-orchestrator`,
or invokable as `python -m coding_orchestrator.app`). It exposes exactly five
subcommands, plus a global `--config` option. **No other commands or flags exist** —
there is no `--dry-run`, `--fake-provider`, `--verbose`, or recovery subcommand.

```bash
coding-orchestrator [--config CONFIG_PATH] <run|run-all|validate|report|handoff> [...]
```

### `--help`

```bash
coding-orchestrator --help
coding-orchestrator run --help
```

### `run` — run exactly one task file

```bash
coding-orchestrator run --task tasks/example_task.md
coding-orchestrator --config config.yaml run --task tasks/my_task.md
```

Prints the full `OrchestratorState` as JSON. Exit code `0` if `final_status=="completed"`,
else `1`.

### `run-all` — run every task file in a directory, honoring `depends_on`

```bash
coding-orchestrator run-all --tasks-dir tasks/
```

Tasks are topologically sorted by `depends_on` (cycles raise `DependencyError`); a task
whose dependency didn't complete is reported `skipped` without being attempted. Prints a
JSON array of all states. Exit code `0` only if every state is `completed` or `skipped`.

### `report` — dump persisted state history plus budget/convergence summaries

```bash
coding-orchestrator report
```

Prints JSON: `states` (every persisted `OrchestratorState`, keyed by `request_id`),
`budget` (`BudgetUsage` — see §6), `convergence` (latest convergence decision summary).
Exit code always `0`. Safe to run repeatedly and does not make any model call.

### `validate` — run the configured validators against the current working tree

```bash
coding-orchestrator validate
```

This is a **health check**, not tied to any task file — it runs
`ruff check .`/`mypy .`/`pytest` (or your `validation.default_commands`) against the
current state of `repo_path` using a synthetic in-memory `TaskSpec(id="manual",
title="Manual validation")`, and prints a JSON array of `ValidationResult`s. Exit code
`0` only if every validator passed. Useful to confirm your repo's tooling is correctly
allowlisted and working before running any real task, and it never calls a model or
spends any budget.

### `handoff` — list pending local handoff artifacts (added 2026-08-10)

```bash
coding-orchestrator handoff
```

Prints a JSON array of pending handoff files under `handoff.output_dir` (default
`logs/handoffs/`), newest first, each with `path`/`task_id`/`reason`/`created_at`
read from the file's YAML frontmatter. A handoff artifact is written automatically
whenever a task ends without completing (non-convergence, a budget/limit block,
Flex unavailability, exhausted retries, or a timeout) and `handoff.enabled` is
true (the default) — see [ChatGPT Handoff Workflow](docs/CHATGPT_HANDOFF_WORKFLOW.md).
This command is read-only and local; it never makes a network call. Uploading a
handoff file (e.g. to Google Drive via `rclone copyto`) is a separate, explicit
step you run yourself.

### Dry/fake-provider testing

There is no CLI flag for this. The **only** dry-run path is automatic: if
`providers.openai.enabled=false`, `runtime_enabled=false` (the shipped default), the API
key env var is unset, or the `openai` package isn't installed,
`OpenAIProvider.generate` raises `ProviderConfigurationError`, which the engine catches
and converts into a `final_status="dry_run"` result — no exception propagates, nothing
is billed, and `tool_results.builder_warning` explains exactly why. This is the safe
default for a fresh checkout: **`run`/`run-all` are safe to execute against real task
files with no config changes**, because they will simply report `dry_run` until you
opt in per §4. `FakeModelProvider` (`models/fake_provider.py`) exists and is used
extensively by the test suite, but it is only reachable by passing
`provider_overrides={"openai": FakeModelProvider(...)}` to `WorkflowEngine(...)`
directly in Python — there is no CLI surface for it.

### Health checks / recovery commands

None exist beyond `validate` (a tooling health check), `report` (a state/budget
inspection), and `handoff` (a list of tasks that stopped without completing and
need either a config change or external, stronger-reasoning attention — see
above). There is no `resume`, `rollback`, `cancel`, or `status` subcommand. Recovery
from an interrupted run is manual: check `git stash list` for an
`orchestrator-<task_id>` entry (see §12/§15) and `.orchestrator.lock` for a stale lock
from a crashed process.

---

## 10. Recommended First Production Run

Follow this exactly, in order, before pointing the orchestrator at anything you care
about.

```bash
# 1. Create a fully disposable test repository — never your real project first.
mkdir -p /tmp/orchestrator-first-run && cd /tmp/orchestrator-first-run
git init
git config user.email "you@example.com"
git config user.name "Your Name"
mkdir pkg
cat > pkg/calc.py <<'EOF'
def add(a, b):
    return a + b
EOF
git add -A && git commit -m "initial"

# 2. Confirm the tree is clean.
git status --short   # must print nothing

# 3. Point a copy of config.yaml at this repo with a very small budget.
cp /path/to/cost-aware-ai-coding-orchestrator/config.example.yaml ./config.yaml
python3 - <<'EOF'
import re
text = open("config.yaml").read()
text = text.replace('repo_path: "."', f'repo_path: "{__import__("os").getcwd()}"')
text = text.replace("runtime_enabled: false", "runtime_enabled: true")
text = text.replace("project_total_budget_usd: 5.0", "project_total_budget_usd: 0.05")
text = text.replace("max_task_cost_usd: 0.10", "max_task_cost_usd: 0.01")
open("config.yaml", "w").write(text)
EOF

# 4. Write a tiny task touching exactly one allowed file.
mkdir -p tasks
cat > tasks/first_task.md <<'EOF'
---
id: T-first-001
title: Add a multiply function to pkg/calc.py
complexity: trivial
risk: low
allowed_files:
  - pkg/calc.py
max_attempts: 1
max_runtime_seconds: 120
max_cost_usd: 0.01
escalation_allowed: true
validation_commands:
  - "python3 -m compileall pkg/calc.py"
---
Add a multiply(a, b) function to pkg/calc.py that returns a * b.
EOF

# 5. Run it, from the orchestrator's own installed environment, with your key exported
#    only for this command.
OPENAI_API_KEY="sk-...your-real-key..." \
  /path/to/cost-aware-ai-coding-orchestrator/.venv/bin/coding-orchestrator \
  --config config.yaml run --task tasks/first_task.md
```

6. **Inspect the diff, logs, state, ledger, and commit**:

```bash
git log --oneline -3                 # your commit, if final_status was "completed"
git show --stat HEAD                 # confirm only pkg/calc.py changed
cat logs/orchestrator.jsonl | tail -5 # event trail for this run
cat logs/state.json | python3 -m json.tool | less   # full persisted OrchestratorState
python3 -c "
import sqlite3
con = sqlite3.connect('logs/budget.sqlite')
for row in con.execute('SELECT model_role, model, status, actual_cost_usd FROM budget_events'):
    print(row)
"
```

7. **Verify rollback with a controlled failure** — write a task guaranteed to fail
   validation, and confirm the repo is left exactly as it was:

```bash
git rev-parse HEAD > /tmp/before.sha
cat > tasks/forced_failure.md <<'EOF'
---
id: T-fail-001
title: Deliberately failing validation task
complexity: trivial
risk: low
allowed_files:
  - pkg/calc.py
max_attempts: 1
max_runtime_seconds: 60
max_cost_usd: 0.01
escalation_allowed: false
validation_commands:
  - "python3 -c \"import sys; sys.exit(1)\""
---
Add a divide(a, b) function to pkg/calc.py that returns a / b.
EOF
OPENAI_API_KEY="sk-...your-real-key..." \
  /path/to/.venv/bin/coding-orchestrator --config config.yaml run --task tasks/forced_failure.md
git rev-parse HEAD    # must match /tmp/before.sha — nothing was committed
git status --short    # must be clean
```

8. **Gradually expand usage** only after all of the above behaved as documented here:
   raise `budget.project_total_budget_usd`/`max_task_cost_usd` incrementally, increase
   `allowed_files` count and `max_attempts` for real tasks one step at a time, and only
   point it at a repository you care about once you've watched it roll back correctly on
   a real (not forced) failure at least once.

---

## 11. Daily Operating Workflow

- **Prepare the repository**: start from a clean `git status`. Not strictly required
  (`git.require_clean_worktree` defaults to `false` and pre-existing dirty state is
  stashed and restored either way), but a clean tree makes it trivial to verify what the
  task actually changed via `git show`/`git diff HEAD~1`.
- **Write a good task**: a single, narrowly-scoped change; a title/description that
  doesn't accidentally trigger the wrong keyword classification (§8); explicit,
  narrow `allowed_files`; a `validation_commands` list that will genuinely catch a bad
  patch (don't rely on the default `ruff`/`mypy`/`pytest` if your repo doesn't have
  matching tooling — a passing-by-default validator is worse than no validator).
- **Choose `allowed_files`**: the smallest set that could possibly need to change. Every
  listed file's full current contents are embedded in the prompt (cost) and become the
  only files a patch is permitted to touch or the commit is permitted to stage (safety).
- **Choose budgets/attempts**: start with `max_cost_usd` around the low/typical figures
  in §6 for the task's apparent size; `max_attempts=2` is a reasonable default —
  raising it multiplies worst-case spend for that task roughly linearly.
- **After completion, inspect**: the printed `OrchestratorState` JSON (especially
  `final_status`, `validation_results`, `tool_results.builder_model`/`builder_role`),
  `git show HEAD` for the actual diff, and `report`'s budget section for cumulative
  spend.
- **When to retry**: if a task ends `blocked` on budget/limits, raise the relevant
  ceiling deliberately (not blindly) and re-run the same task file. If it ends
  `flex_unavailable`, wait and retry later, or raise `max_flex_retries`.
- **When to escalate manually**: any `escalated`/`failed` status — read the JSON package
  in `logs/escalations/<task_id>-escalation.json` (diff, logs, validation errors, a
  heuristic `suggested_next_action`) and make the change yourself, or narrow the task and
  retry. Do not expect an automated reviewer to pick this up (§1).
- **Safe use on important repositories**: run `git.require_clean_worktree: true`, keep
  `allowed_files` minimal, keep a low per-task budget, and — since only one run can hold
  the repo lock at a time — never run two orchestrator instances against the same
  repository concurrently expecting them to interleave; the second will simply be
  `blocked`.

---

## 12. Safety Guarantees and Boundaries

Guarantees below are backed by specific code, cited by file. "Recommendation" items are
operator practices this guide advises, not something the code enforces for you.

| Area | Guarantee (implemented) | Source |
|---|---|---|
| Patch contract | Model output must be a `BuilderOutput`-shaped JSON object or a unified diff (bare or fenced); anything else is rejected before any file is touched. | `tools/patch.py: parse_builder_output` |
| Path restrictions | Absolute paths, path traversal outside the repo root, and paths under `/etc/`, `~/.ssh`, `.env`, `secrets`, `credentials`, `tokens` (substring match, case-insensitive) are rejected in both the patch validator and the pre-apply validator. | `tools/patch.py: SafePatchApplier.validate_patch`, `orchestrator/policies.py: is_forbidden_path` |
| Allowed files | A patch touching any file outside `task.allowed_files` is rejected; commit staging further intersects changed files with `allowed_files` — files outside that intersection are never staged even if changed on disk. | `tools/patch.py`, `tools/git.py: commit_task` |
| Forbidden paths | See above; enforced independently by both the patch applier and `PermissionValidator` (post-apply, belt-and-suspenders). | `validators/permission_validator.py` |
| Command allowlist | Every shell command actually executed (git, validation commands) must have its first token in `tool_permissions.allowlisted_shell_commands`; `run_limited_command` raises `CommandSafetyError` otherwise, and `CommandSafetyValidator` checks configured validation commands before they run. | `tools/shell.py`, `validators/safety_validator.py` |
| Git checkpoints | Every task run starts by recording `HEAD` and stashing pre-existing dirty/untracked state (excluding orchestrator data paths) via `git stash push --include-untracked`. | `tools/git.py: GitManager.checkpoint` |
| Isolated worktrees | Not implemented — the orchestrator operates directly on `repo_path`'s working tree, not a separate clone or worktree. Concurrency protection (below) is what prevents interference, not isolation. | — |
| Rollback | On any failure/timeout/budget-block/exception, `git reset --hard <checkpoint_sha>` + `git clean -fd` (excluding preserved dirs/files) restores the exact pre-task tree, then pops the pre-existing stash if one was made. | `tools/git.py: rollback_to_checkpoint` |
| Clean-worktree handling | Optional (`git.require_clean_worktree`): if `true`, a repo with tracked dirty changes refuses to start (`DirtyWorktreeError`) rather than stashing them. Default `false` stashes and restores instead. | `tools/git.py: checkpoint` |
| Concurrent-run protection | An OS-level advisory `flock` on `<repo>/.orchestrator.lock` — a second run against the same repo is rejected with `final_status="blocked"`, never silently interleaved. Released automatically if the holding process crashes. | `tools/lock.py: RepoLock` |
| HEAD-change detection | If `HEAD` differs from the checkpoint's recorded SHA right before commit, `HeadChangedError` aborts rather than committing on top of unexpected state. | `tools/git.py: verify_head` |
| Timeout handling | Wall-clock budget per task (`timeouts.max_task_runtime_seconds`, capped by `task.max_runtime_seconds`) and per subprocess call (`max_attempt_runtime_seconds`); exceeding either raises and rolls back. | `orchestrator/timeouts.py`, `tools/shell.py` (subprocess `timeout=`) |
| Output limits | stdout/stderr/patch/context byte-or-token ceilings are enforced pre- and post-call (`limits.*`), configurable to reject or (for stdout/stderr and validation output only) truncate. | `orchestrator/limits.py` |
| Structured output validation | JSON builder output is validated against the `BuilderOutput` pydantic schema; invalid JSON or a schema mismatch raises `StructuredOutputError` before anything is applied. | `models/openai_provider.py`, `models/provider.py` |
| Prevention of silent non-Flex calls | Checked unconditionally at the provider call boundary before any other setting, and independently at config-load time; no override parameter exists anywhere in the codebase. | `models/openai_provider.py: generate`, `config.py: _enforce_flex_only_policy` |
| Secret handling | The API key is only ever read from an environment variable named by `api_key_env_var`; the schema has no field that could hold a literal key. Forbidden-path rules block patches from touching `.env`/`secrets`/`credentials`/etc. | §4, `orchestrator/policies.py` |

**Limitations, stated plainly**: there is no sandboxing/containerization of the target
repository — the orchestrator runs real subprocesses (`git`, `pytest`, etc.) directly
against your filesystem with your user's permissions, constrained only by the allowlist
and path checks above, not by OS-level isolation. A validation command you configure
yourself (e.g. a custom `validation_commands` entry) is trusted to be safe — the
allowlist only checks the *executable name*, not what the command actually does.

---

## 13. Validation and Quality Gates

### What runs, and in what order (`WorkflowEngine._validate`)

1. **`CommandSafetyValidator`** — every configured validation command's first token must
   be in `tool_permissions.allowlisted_shell_commands`. Fails fast, before anything else
   runs, if a command isn't allowlisted.
2. **`PatchValidator`** — changed-file count vs. `validation.max_files_changed`, then
   delegates to `PermissionValidator` for forbidden-path/workspace/allowed-file checks
   against every file git reports as changed (not just what the patch declared).
3. **`SyntaxValidator`** — for every changed `.py` file, `python -m compileall -q
   <files>`. Non-Python changes are not compile-checked (passes trivially if no `.py`
   files changed).
4. **`TestValidator`** — runs `task.validation_commands`, or if empty,
   `validation.default_commands` (`ruff check .`, `mypy .`, `pytest`), each as a real
   subprocess with its own stdout/stderr captured (last 4,000 characters each).

All four always run (not short-circuited on the first failure) so a single attempt's
result reflects every gate.

### What happens when validation fails

The attempt's validator errors are collected; `ConvergenceEvaluator` scores the attempt
against the previous one and decides: retry the same builder role
(`continue_current_role_retry`, most common), request diagnosis
(`request_diagnosis` — only meaningful if `diagnosis.enabled=true`, otherwise falls
through to the escalation path described in §1), or pause/block
(`pause_block_task`, forced when a syntax regression or an unrelated-file touch is
detected). Retry context (the last 8,000 characters of failure output, configurable via
`limits.max_retry_context_chars`) is appended to the next attempt's prompt.

### Commit conditions

A commit only happens when, in the same attempt: validation produced **zero** errors,
and `git` reports at least one actually-changed file (for workflows that are supposed to
produce a change). The commit stages exactly the intersection of git-changed files and
`task.allowed_files` — never anything else, even if other files happen to be dirty for
unrelated reasons.

### No-change tasks

If validation passes but nothing changed, and the workflow is a modifying one (not
`explain_code`/`architecture_review`/`security_review`), the task ends `no_change` —
this is distinct from `completed` and is not treated as a failure requiring rollback of
anything (there was nothing to roll back), but it is not success either.

---

## 14. Logs, State, Ledger, Cache, and Escalation Artifacts

| Artifact | Default location | Format | Contents | Inspect with | Retention/cleanup | Sensitive? |
|---|---|---|---|---|---|---|
| Event log | `logs/orchestrator.jsonl` | JSON Lines, one event object per line | `task_started`, `validation_failed`, `attempt_metrics`, `task_completed`/`task_failed`/etc., `flex_transient_error`, `service_tier_mismatch`, `diagnosis_needed`, `telegram_warning` — includes error messages and tracebacks for unexpected exceptions. | `tail -f logs/orchestrator.jsonl`, `jq` | Append-only, grows unbounded; archive/rotate manually. | **Yes** — can contain task titles/descriptions, validator stdout/stderr excerpts, and exception tracebacks. Not prompts/patches in full. |
| State store | `logs/state.json` | Single JSON object, keyed by `request_id` | The full `OrchestratorState` for every finished run: task type/complexity/risk, `tool_results` (including `builder.text` — the model's raw output/patch), `validation_results`, cost estimates, timestamps. | `python3 -m json.tool logs/state.json \| less` | Rewritten in full on every run (`StateStore.append` reloads-all, merges, rewrites) — grows unbounded over time; archive/reset by moving the file aside between projects. | **Yes** — this is the most sensitive artifact: it contains full prompts sent (`tool_results.builder_request`), the model's raw patch text, and validator output verbatim. |
| Budget ledger | `logs/budget.sqlite` | SQLite | See §6 schema — token counts, costs, statuses, requested/actual service tier, per call. | `sqlite3 logs/budget.sqlite` or the Python one-liner in §6/§10 | Append-only table; safe to keep indefinitely for cost auditing, or delete to reset budget history for a `project_id` (this also resets cumulative spend checks). | No prompt/patch text — only metadata, token counts, and cost figures. |
| Escalation packages | `logs/escalations/<task_id>-escalation.json` | JSON | Full task spec, full `OrchestratorState`, git diff, recent logs, validation errors, a heuristic suggested next action. | Any JSON viewer/`jq` | One file per escalated task, overwritten if the same `task_id` escalates again; clean up manually once reviewed. | **Yes** — contains the diff and task description in full. |
| Handoff artifacts (added 2026-08-10) | `logs/handoffs/<task_id>-<request_id>-handoff.md` | Markdown with YAML frontmatter | Why automation stopped, task spec, attempts/convergence evidence, latest validation failures, current repo diff, budget snapshot, and the task-file schema — written whenever a task ends without completing. See §9 (`handoff` command) and [ChatGPT Handoff Workflow](docs/CHATGPT_HANDOFF_WORKFLOW.md). | `coding-orchestrator handoff` (lists them), or open the file directly | One file per non-completing run; not automatically deleted — clean up once processed. Never uploaded automatically. | **Yes** — contains the diff and full task description, same sensitivity as escalation packages. |
| Cache | N/A — not wired into the engine | — | — | — | `coding_orchestrator/cache/cache.py` (`HashCache`) is unused dead code; nothing to configure or inspect. | — |

All of `logs/*.json`, `logs/*.jsonl`, `logs/*.sqlite`, `logs/escalations/`, and
`logs/handoffs/` are git-ignored by default (`.gitignore`) and are always excluded
from the orchestrator's own stash/checkpoint/rollback logic regardless of the target
repo's own `.gitignore` — they will never be silently discarded or accidentally
committed as part of a task's patch.
Because `logs/state.json` and the escalation packages contain full prompts and model
output, treat that directory with the same care as source code that might reference
internal details — do not publish it externally without review.

---

## 15. Failure Statuses and Recovery

| Situation | Likely cause | `final_status` | Where to look | Safe recovery |
|---|---|---|---|---|
| Configuration error (provider disabled) | `providers.openai.enabled=false` | `dry_run` | `tool_results.builder_warning` | Set `enabled: true`. |
| Missing API key | `OPENAI_API_KEY` not exported, or `runtime_enabled=false` | `dry_run` | `tool_results.builder_warning` (states exactly which check failed) | Export the key (§4); set `runtime_enabled: true`. |
| Provider unavailable (SDK not installed) | `openai` package missing from the active venv | `dry_run` | `tool_results.builder_warning`: "OpenAI Python SDK is not installed" | `pip install -e ".[dev]"` or `pip install openai`. |
| Flex unavailable | Flex capacity exhausted after bounded retries | `flex_unavailable` | `tool_results.builder_flex_transient_error`, event log `flex_transient_error` entries | Retry later, or raise `inference.builder_service_tier.flex.max_flex_retries`. Never override to a non-Flex tier — no mechanism exists to do so. |
| Tier mismatch | OpenAI reported back a non-Flex tier for a Flex request | `blocked` | `tool_results.service_tier_mismatch` | Investigate with your OpenAI account/dashboard; re-run once resolved. Not something this codebase can force. |
| Invalid structured output | Model returned malformed/non-schema-matching JSON | Exception surfaces as `failed` (unhandled `StructuredOutputError` from the provider call) | `tool_results.error_type`/`error_traceback`, event log `unexpected_error` | Re-run (nondeterministic model output); if persistent, the role's prompt/context may need narrowing. |
| Invalid patch | Model output isn't a unified diff or valid `BuilderOutput` JSON | `failed` (unhandled `PatchContractError`) | Same as above, plus `tool_results.builder.text` for the raw model output | Re-run; consider a smaller/simpler task scope. |
| `git apply` failure | The diff's hunk headers don't match the file's actual current content (a real, observed model-output risk — `git apply --check` can pass while `git apply` only partially applies a miscounted hunk) | `failed` (unhandled `PatchApplyError`) | `tool_results.error_traceback`, `tool_results.builder.text` | Re-run; inspect the raw diff manually if it recurs. This is a known, documented risk of LLM-generated diffs, not a bug to "fix" via configuration. |
| Validation failure | `ruff`/`mypy`/`pytest`/custom command failed after a syntactically valid patch applied | stays `running` through retries, ends `escalated`/`failed`/`blocked` depending on convergence and attempts remaining | `validation_results`, `tool_results.convergence` | Retry (automatic, up to `max_attempts`) or read the escalation package and fix manually. |
| Timeout | Task exceeded `max_runtime_seconds`/`max_task_runtime_seconds` | `timeout` | Event log `task_timeout`, `validation_errors` list | Increase the timeout deliberately, or split the task into a smaller one. |
| Budget exceeded | Pre-call estimate or cumulative spend would exceed task/role/project budget | `blocked` | `validation_results.budget`, `report`'s budget section | Raise the specific budget that blocked it (task/role/project), or reduce task scope/attempts. |
| Non-converging task | Repeated/worsening validation failures past configured thresholds | `escalated` or `blocked` (`pause_block_task` if a syntax regression or unrelated-file touch was detected) | `tool_results.diagnosis_needed_package`, `logs/escalations/` | Read the escalation package; the task needs a human, not another automatic retry. |
| Rollback failure | `git reset --hard`/`git clean`/`git stash pop` itself fails (e.g. filesystem permission issue) | The rollback call's `CommandResult` is returned but not separately raised as a distinct status — check the surrounding `failed`/`timeout`/etc. status and inspect the repo directly | `git status`, `git stash list` | Manual `git` intervention; this is the one area with the least built-in recovery automation — verify repo state by hand. |
| Dirty worktree | `git.require_clean_worktree=true` and the repo had tracked dirty changes at start | Task never starts a checkpoint; raises `DirtyWorktreeError`, surfaces as `failed` | Exception message names the dirty files | Commit or stash your own changes first, or set `require_clean_worktree: false` to let the orchestrator stash them for you. |
| Concurrent execution | Another orchestrator run holds `.orchestrator.lock` on the same repo | `blocked` | Event log `concurrent_execution_blocked` | Wait for the other run to finish; if it crashed, the OS releases the `flock` automatically — no manual lock file cleanup should be needed. |
| Git commit failure | `git commit` itself returned non-zero (e.g. no configured `user.email`/`user.name`, or `allowed_files` didn't intersect changed files) | `failed` (`CommitFailed`) | `tool_results.git_commit.stderr` | Configure git identity in the target repo; verify `allowed_files` actually covers what the patch changed. |
| No changes produced | Validation passed but the builder's patch was empty or a no-op | `no_change` | `tool_results.builder.text` | Not an error — re-word the task if you expected a real change; some workflows (`explain_code`) are expected to end this way with prose output instead. |

---

## 16. Production Recommendations

| Setting | Recommended conservative value | Rationale |
|---|---|---|
| Model routing | Leave the shipped three-role automatic mapping (`mechanical_worker`→gpt-5-nano, `simple_builder`/`general_builder`→gpt-5-mini) unchanged. | This is already the outcome of this repository's own cost/reliability benchmark (§17, `docs/OPERATIONAL_HARDENING_CHANGES.md`). |
| Reasoning effort | Leave as shipped (`low` for nano/simple roles, `medium` for `general_builder`, `high` only for non-auto-routed reviewer roles). Never set `"none"` on a live role. | `"none"` is live-verified rejected by the API for gpt-5-family models. |
| Flex-only operation | Never attempt to disable it; there is no supported way to. | It is the entire cost-predictability guarantee of this system. |
| Task budget | `max_cost_usd` per task: `0.01`–`0.03` for trivial/simple tasks. | Matches the low/typical figures in §6 with headroom for one retry. |
| Project budget | Set `budget.project_total_budget_usd` explicitly per project/environment — do not rely on the `5.0` default for a shared or long-lived project. | The default is a generous ceiling meant for initial exploration, not a production limit you've reasoned about. |
| Max attempts | `2` (the default). | Each additional attempt is a fully independent billed call; 2 balances letting the model self-correct once against runaway cost. |
| Timeouts | Leave `timeouts.max_attempt_runtime_seconds=300`; lower `task.max_runtime_seconds` per task to roughly 2–4x your validation commands' expected wall-clock time. | Long timeouts on a stuck task delay rollback/escalation, not prevent it. |
| Allowed files | 1–2 files per task. | Matches what `mechanical_worker`/`simple_builder` are actually tuned and routed for; larger changes should be split into dependent tasks (§8) or reviewed manually. |
| Validation commands | Always specify task-appropriate `validation_commands` explicitly rather than relying on the generic default (`ruff`/`mypy`/`pytest`) if your repo's tooling doesn't match. | A validator that trivially passes (or errors for unrelated reasons) gives false confidence. |
| Use on clean repositories | `git.require_clean_worktree: true` for any repository you're not comfortable having auto-stashed. | Forces the operator to consciously commit/stash first rather than relying on the stash/restore safety net. |
| Backups and branches | Run against a dedicated branch, or ensure you have a remote/backup of `HEAD` before a real run, even though rollback is implemented and tested — defense in depth for a `git reset --hard` in a system that shells out to real git. | No sandboxing/isolation exists (§12) — this is real git, on your real working tree. |
| Supervision level | Full manual review of every commit before pushing/merging, for the foreseeable term. | No automated reviewer path works today (§1); `completed` means "validated and committed locally," not "reviewed." |

---

## 17. Known Limitations

Limitations verified as still true in the current code (not repeats of anything already
fixed in this repository's history):

- **Diagnosis/reviewer escalation cannot make a real model call.** `DiagnosisReviewer.diagnose`
  unconditionally raises when `dry_run=False`; combined with `diagnosis.enabled=false`
  by default, the `frontier_reviewer`/`frontier_balanced_reviewer` roles — despite being
  fully priced and Flex-verified — are unreachable in normal operation.
- **`classification_worker` is fully configured but never invoked.** Task
  type/complexity/risk classification is deterministic keyword/field logic with no
  model call anywhere in the path.
- **Only OpenAI has a real provider implementation.** `FakeModelProvider` is test-only.
- **Five of eight defined workflows are disabled**: `small_refactor`, `large_refactor`,
  `architecture_review`, `dependency_update`, `security_review`. A task classified into
  one of these is blocked (`requires_human_approval=true`) before any call.
- **No sandboxing or isolated worktree.** The orchestrator runs real `git`/validation
  subprocesses directly against `repo_path`'s working tree.
- **No CLI-level dry-run or fake-provider flag** — the dry-run path only triggers
  automatically via configuration/environment gaps (§9).
- **Several modules in the tree are dead code**, not wired into the active path:
  `coding_orchestrator/cache/`, `coding_orchestrator/memory/`,
  `observability/audit.py`, `observability/metrics.py`, `observability/traces.py`,
  `tools/formatter.py`, `tools/linter.py`, `tools/type_checker.py`, `tools/registry.py`,
  `tools/filesystem.py`, `validators/base.py`. Do not configure or rely on features
  implied by their names.
- **`retries.max_retries` in config is not read by the active engine path** — the real
  retry bound is `task.max_attempts`. Setting `retries.max_retries` has no observed
  effect.
- **`state.selected_model` (from the coarse `ModelRouter`) can be misleading** — it is
  set from a legacy pre-router used only to gate `complexity="critical"`, and does not
  necessarily match the model that actually ran. Always trust
  `tool_results.builder_model`/`tool_results.builder_role` for what really executed.
- **`git apply` can succeed on a miscounted hunk header and silently apply only part of
  a patch** — `git apply --check` validates the patch's shape but not that its declared
  line counts match its actual body; a model that miscounts a hunk header can produce a
  patch that partially applies without any reported error. This is a structural risk of
  LLM-generated unified diffs, not something this codebase currently detects or guards
  against beyond normal post-apply validation (which would generally catch the resulting
  broken code via `SyntaxValidator`/`TestValidator`, but not guaranteed to for every
  case).
- **No production usage data exists in this repository.** The local budget ledger has
  zero rows; every cost figure in this guide is a config-derived estimate, not a
  measured one.
- **Rollback failure has no dedicated status/handling** — if `git reset`/`git clean`/
  `git stash pop` themselves fail during rollback, there is no distinct `final_status`
  for that; the surrounding failure status is still reported, and the repository state
  must be verified manually (§15).

---

## 18. End-to-End Examples

### Installation

```bash
git clone <your-fork-or-copy-of-this-repo> cost-aware-ai-coding-orchestrator
cd cost-aware-ai-coding-orchestrator
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -r requirements-lock.txt
```

### Environment setup

```bash
export OPENAI_API_KEY="sk-REPLACE-WITH-YOUR-REAL-KEY"
```

### Minimal config

```yaml
# config.yaml
repo_path: "/path/to/your/target/repo"
providers:
  openai:
    enabled: true
    runtime_enabled: true
budget:
  project_total_budget_usd: 0.50
  max_task_cost_usd: 0.02
  project_id: "my-project"
```

(Every other field falls back to `AppConfig()` defaults — a minimal override file is
valid; unspecified sections use the same values shown throughout §7.)

### Explain-code task

```markdown
<!-- tasks/explain_calc.md -->
---
id: T-explain-calc
title: Explain the add function in pkg/calc.py
complexity: trivial
risk: low
allowed_files: []
max_attempts: 1
max_runtime_seconds: 90
max_cost_usd: 0.01
escalation_allowed: true
validation_commands:
  - "python3 -c 'pass'"
---
Explain what pkg/calc.py's add(a, b) function does.
```

### Patch-producing task

```markdown
<!-- tasks/add_multiply.md -->
---
id: T-add-multiply
title: Add a multiply function to pkg/calc.py
complexity: trivial
risk: low
allowed_files:
  - pkg/calc.py
max_attempts: 2
max_runtime_seconds: 180
max_cost_usd: 0.02
escalation_allowed: true
validation_commands:
  - "python3 -m compileall pkg/calc.py"
---
Add a multiply(a, b) function to pkg/calc.py that returns a * b.
```

### Running the tasks

```bash
.venv/bin/coding-orchestrator --config config.yaml run --task tasks/explain_calc.md
.venv/bin/coding-orchestrator --config config.yaml run --task tasks/add_multiply.md
```

### Viewing the report

```bash
.venv/bin/coding-orchestrator --config config.yaml report | python3 -m json.tool
```

### Inspecting git

```bash
cd /path/to/your/target/repo
git log --oneline -5
git show HEAD
```

### Locating ledger and logs

```bash
ls /path/to/your/target/repo/logs/
# budget.sqlite  orchestrator.jsonl  state.json  escalations/
```

---

## 19. Release and Maintenance Checklist

### Pre-run checklist

- [ ] `git status --short` on the target repo is clean (or you're deliberately relying
      on the stash/restore safety net and have reviewed §12).
- [ ] `config.yaml`'s `repo_path` points at the intended repository.
- [ ] `budget.project_total_budget_usd`/`max_task_cost_usd` are set deliberately, not
      left at generous defaults.
- [ ] `OPENAI_API_KEY` is exported in the current shell only, never written to a file.
- [ ] The task file's `allowed_files` is the minimal necessary set.

### Post-run checklist

- [ ] Read `final_status` — only `completed` means a real, validated, committed change.
- [ ] `git show HEAD` matches expectations (right files, sane diff).
- [ ] `report`'s budget section reflects expected spend.
- [ ] If `escalated`/`failed`/`blocked`, the corresponding artifact (`logs/escalations/`
      or the printed state JSON) has been read before retrying.

### Production-readiness checklist (for this repository as a whole)

- [ ] `.venv/bin/pytest -q` passes (132 tests at time of writing).
- [ ] `.venv/bin/ruff check .` passes.
- [ ] `.venv/bin/mypy .` passes.
- [ ] `.venv/bin/python3 -c "import coding_orchestrator.app"` succeeds.
- [ ] `.venv/bin/python3 -m coding_orchestrator.app report` succeeds with no prior state.
- [ ] You have personally run the first-production-run procedure in §10, including the
      forced-failure rollback verification, at least once.
- [ ] You understand that diagnosis/reviewer escalation does not work for real calls
      (§1/§17) and are not relying on it.

### Upgrade checklist

- [ ] Re-run the full test/lint/type-check suite after pulling changes.
- [ ] Diff `config.example.yaml` against your own `config.yaml` for new/changed/removed
      fields (unknown keys are silently ignored, not errored — a stale field name will
      not warn you).
- [ ] Re-verify model/reasoning-effort/tier compatibility live (small budget, one call
      per role you actually use) if any `model_roles`/`pricing` section changed upstream.

### Test commands

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy .
```

### Git cleanliness checks

```bash
git status --short
git stash list   # confirm no orphaned orchestrator-<task_id> stashes remain
```

### Secret scan

```bash
git grep -nE "sk-[A-Za-z0-9]{10,}" -- . ':!*.md' || echo "no obvious API key literals found"
git grep -n "OPENAI_API_KEY" -- '*.yaml' '*.yml'   # should only ever show the env-var NAME, never a value
```

### Configuration verification

```bash
.venv/bin/python3 -c "
from coding_orchestrator.config import load_config
c = load_config('config.yaml')
print('repo_path:', c.repo_path)
print('runtime_enabled:', c.providers.openai.runtime_enabled)
print('project_total_budget_usd:', c.budget.project_total_budget_usd)
"
```

(This also implicitly re-runs the Flex-only policy validator — a bad config raises
`FlexPolicyViolation` immediately.)

---

## 20. Quick Reference

```bash
# Install
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Verify install
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy .

# Health-check current repo tooling (no model call, no cost)
.venv/bin/coding-orchestrator --config config.yaml validate

# Run one task
OPENAI_API_KEY="sk-..." .venv/bin/coding-orchestrator --config config.yaml run --task tasks/my_task.md

# Run all tasks in a directory (dependency-ordered)
OPENAI_API_KEY="sk-..." .venv/bin/coding-orchestrator --config config.yaml run-all --tasks-dir tasks/

# Inspect history, budget, convergence
.venv/bin/coding-orchestrator --config config.yaml report

# Inspect the raw budget ledger
sqlite3 logs/budget.sqlite "SELECT model_role, model, status, actual_cost_usd FROM budget_events;"

# List pending ChatGPT-handoff artifacts (added 2026-08-10; local/read-only)
.venv/bin/coding-orchestrator --config config.yaml handoff
```

| Status | Meaning | Money spent? |
|---|---|---|
| `completed` | Real success: patched, validated, committed. | Yes (real call(s)) |
| `dry_run` | Provider not usable (config/key/SDK) — nothing ran. | No |
| `no_change` | Model called, produced no usable patch. | Yes |
| `blocked` | Budget/limit/approval/lock/tier-mismatch gate stopped it. | Sometimes (estimate only, never a completed call) |
| `flex_unavailable` | Flex retries exhausted; no other tier used. | Partial (failed attempts only) |
| `timeout` | Exceeded runtime budget. | Possibly (attempts made before timeout) |
| `failed` | Unhandled error (bad patch, commit failure, HEAD moved, etc.). | Possibly |
| `escalated` | Attempts exhausted; human review package written. | Yes (all attempts) |
| `skipped` | `run-all` only: a dependency never completed. | No |

**Golden rule**: only `final_status: "completed"` means the task actually succeeded.
Every other status means either nothing happened or something needs a human.

---

## 21. Cost-Minimization Workflow: ChatGPT Handoff (Added 2026-08-10)

For minimizing metered OpenAI API cost specifically (as opposed to just running
individual tasks), this project supports a workflow that keeps two categories of
work off the metered API entirely: detailed planning and initial multi-file code
generation (via a ChatGPT subscription, which naturally carries whole-conversation
context this orchestrator's per-task isolated context cannot provide), and
strong-reasoning escalation when nano/mini genuinely can't solve a task
economically (also via the ChatGPT subscription, a flat cost, instead of an
automatic call to a pricier OpenAI API model — there still isn't one; automatic
routing remains nano/mini-only end to end).

**What's new**: whenever a task ends without completing — non-convergence, a
budget/limit block, Flex unavailability, exhausted retries, or a timeout — and
`handoff.enabled` is `true` (the default), the engine writes a single, bounded,
self-contained Markdown file to `logs/handoffs/` summarizing why it stopped, the
task spec, the attempts/convergence evidence, the latest validation failures, the
current diff, a budget snapshot, and this repository's task-file schema. This is
pure local file I/O — no model call, no network access. List pending ones with
`coding-orchestrator handoff`; nothing is uploaded automatically. See §7 for the
`handoff.*` config fields and §9 for the CLI command.

**The intended loop**: ChatGPT plans and generates the initial repository → your
configured `rclone` remote → VPS (seed commit, then a free `coding-orchestrator
validate` pass) → ChatGPT turns any failures into bounded repair tasks → the
orchestrator closes as many gaps as it economically can on Flex-only nano/mini →
whenever that stops being economical, a handoff artifact is ready for you to
upload and ask ChatGPT to resolve → the result comes back and the orchestrator
continues, unchanged — `run`/`run-all` already accept whatever's currently in the
repository and tasks directory regardless of its origin. An optional final pass
with Claude Code (subscription, large-context repository review) can produce a
further correction task set through the same loop.

Full walkthrough, including the exact `rclone copyto`-based upload/verify
commands: [ChatGPT Handoff Workflow](docs/CHATGPT_HANDOFF_WORKFLOW.md).

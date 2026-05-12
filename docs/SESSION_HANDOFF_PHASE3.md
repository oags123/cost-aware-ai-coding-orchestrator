# SESSION HANDOFF - PHASE 3 (OpenAI Multimodel Refactor)

Last updated: 2026-05-11 (UTC)

## 1) Project Identity

- Project: `cost-aware-ai-coding-orchestrator`
- Branch: `refactor/openai-multimodel-no-opencode`
- Latest commit at handoff start: `ef60099 Add OpenAI role provider path and model catalog`
- Safety tags:
  - `after-phase-2-5-openai-model-catalog`
  - `before-openai-multimodel-refactor`
- Current repository status: **dirty** (Phase 3 in-progress working tree, not committed)
- Python version assumptions:
  - Runtime used in this session: `Python 3.12.3` (`.venv/bin/python --version`)
  - `pyproject.toml` requires `>=3.11`
  - Ruff target `py311`, mypy `python_version=3.11`
- Virtualenv assumptions:
  - Local venv path: `.venv`
  - Tooling commands expected from venv:
    - `.venv/bin/ruff`
    - `.venv/bin/mypy`
    - `.venv/bin/pytest`
    - `.venv/bin/python`

---

## 2) Current Architecture Summary

### Orchestrator flow

Primary flow in `coding_orchestrator/orchestrator/engine.py`:

1. Load task/state/config.
2. Classify task (`TaskClassifier`) and choose workflow/model role routing metadata.
3. Create git checkpoint.
4. Build bounded context from workflow + compact validator feedback + optional diagnosis guidance.
5. Run builder via provider path (role/provider/service-tier aware).
6. Validate output limits, parse patch contract, enforce patch/file safety, apply patch with `git apply --check`.
7. Run validators.
8. Record convergence metrics and decide retry/escalate/block.
9. Rollback on failure paths.
10. Record logs/state/budget and produce final status.

### Provider abstraction

- Contract in `coding_orchestrator/models/provider.py`:
  - `ProviderRequest`, `ProviderResponse`, `ModelUsage`, `BuilderOutput`.
  - Provider interface `ModelProvider.generate`.
- Structured output contract for builders:
  - Unified diff OR JSON matching `BuilderOutput`/patch contract.

### Fake provider

- `coding_orchestrator/models/fake_provider.py`
- Deterministic no-network path for tests.
- Captures requests and can emit:
  - `ProviderResponse`
  - `BuilderOutput`
  - raw text

### OpenAI provider

- `coding_orchestrator/models/openai_provider.py`
- Uses OpenAI Python SDK Responses API path.
- Reads API key from env only (`OPENAI_API_KEY` or configured env var).
- `providers.openai.runtime_enabled` gate prevents accidental live calls.
- Supports reasoning effort + service tier request fields.

### Capability-role routing

- Role schema + aliases in `coding_orchestrator/config.py`.
- Runtime role selection in `_select_builder_role`:
  - tiny deterministic/narrow tasks -> `mechanical_worker`
  - small tasks -> `simple_builder`
  - otherwise/retries/high-risk -> `general_builder`

### Builder/reviewer escalation flow

- Default builder path: role-provider.
- Convergence evaluator decides:
  - continue retry
  - request diagnosis
  - block/pause
- Diagnosis flow uses compact review packet + diagnosis-only contract.
- Guided retry can append diagnosis instruction to next builder attempt.

### Validation flow

- `CommandSafetyValidator`
- `PatchValidator`
- `SyntaxValidator`
- `TestValidator`
- Output truncation/rejection policies enforced by `LimitGuard`.

### Rollback flow

- Git checkpoint captured before attempts.
- On failure/timeout/budget/limit exceptions, rollback restores tracked/staged and removes new untracked except preserve lists.

### Git checkpoint flow

- `coding_orchestrator/tools/git.py`:
  - `checkpoint()`
  - `rollback_to_checkpoint()`
  - scoped `commit_task()` using `task.allowed_files`

### Patch safety flow

- `coding_orchestrator/tools/patch.py`
- Accepts only:
  - unified diff text
  - or structured JSON patch
- Enforces:
  - touched file consistency
  - forbidden path checks
  - workspace boundary checks
  - max file count
  - delete policy
  - `git apply --check` prior to apply

### Budget enforcement

- `coding_orchestrator/orchestrator/budget.py`
- Pre-call estimate -> budget gate -> ledger record.
- Enforces:
  - task cap
  - project cap
  - role budget cap
- Tracks spend and blocked calls in SQLite.

### Service-tier policy

- `coding_orchestrator/orchestrator/tier_policy.py`
- Builder service-tier state tracks:
  - calls by tier
  - timeout counts
  - fallback activations

### Flex/default fallback logic

- Prefer flex for non-urgent builder calls.
- On transient flex failures/timeouts, policy can activate fallback to default.
- Fallback bounded by count + fallback budget.

### Reasoning-effort policy

- Request-level setting in role config.
- Roles define default reasoning effort (`none/low/medium/high/xhigh`).
- Frontier direct patching still policy-gated (`allow_frontier_direct_patch=false` default).

### Pricing system

- Config-driven model pricing in `pricing.roles`.
- Includes source metadata + verified date.
- Supports service-tier entries + long-context fields + nullable cached input pricing.

### Structured output contracts

- Provider JSON output validated by `BuilderOutput` when applicable.
- Patch parser/contract enforces strict accepted shapes.

### Migration status categories

- Completed:
  - Role/provider path, OpenAI provider, fake provider, service-tier routing, pricing model catalog.
- Partially migrated:
  - Some naming still intentionally retains `ultra_cheap_classifier` alias terminology.
- Legacy:
  - none active for OpenCode runtime (removed).
- Pending removal:
  - no known active OpenCode runtime code; only finishing commit/cleanup choices remain.

---

## 3) Completed Phases

### Phase 1

- Goal:
  - Introduce role schema/config structure and pricing scaffolding without fully changing runtime backend.
- Changes:
  - Added model aliases, capability roles, pricing metadata fields, provider settings.
  - Added `resolve_model_role`.
- Key files:
  - `coding_orchestrator/config.py`
  - `tests/test_model_roles_config.py`
- Tests added/updated:
  - Role parsing/resolution.
  - Pricing metadata loading.
- Decisions:
  - Config-first model catalog.
  - Keep OpenCode path temporarily for stability during early migration.
- Unresolved at phase end:
  - Runtime still coupled to legacy builder path.

### Phase 2

- Goal:
  - Integrate provider path into engine while preserving safety behavior and test stability.
- Changes:
  - Added provider-backed builder execution path.
  - Maintained patch safety/validation/rollback constraints.
  - Preserved fake provider no-network testing path.
- Key files:
  - `coding_orchestrator/orchestrator/engine.py`
  - `coding_orchestrator/models/provider.py`
  - `coding_orchestrator/models/fake_provider.py`
  - `coding_orchestrator/models/openai_provider.py`
- Tests:
  - `tests/test_engine_provider_path.py`
- Decisions:
  - Provider contract must feed existing patch safety flow, not bypass it.
- Unresolved:
  - Legacy OpenCode backend still present.

### Phase 2.5

- Goal:
  - Update model catalog/aliases/pricing defaults/reasoning + service-tier policies to current OpenAI strategy.
- Changes:
  - OpenAI model alias matrix expanded.
  - Role defaults updated (`gpt-5.4-nano`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.5`, `gpt-5.5-pro`).
  - Pricing defaults updated with source metadata.
- Key files:
  - `coding_orchestrator/config.py`
  - `config.example.yaml`
  - docs set (role/cost/config/plan docs)
- Tests:
  - Model alias resolution.
  - pro-model manual approval policy.
  - cached input null handling.
- Decisions:
  - Treat reasoning as request-level, not separate model IDs.
- Unresolved:
  - Full OpenCode removal still pending at phase boundary.

---

## 4) Current Model Catalog and Routing Matrix

### Model aliases

- `openai_classifier_nano` -> `gpt-5-nano`
- `openai_nano` -> `gpt-5.4-nano`
- `openai_mini_legacy` -> `gpt-5-mini`
- `openai_mini` -> `gpt-5.4-mini`
- `openai_codex` -> `gpt-5.3-codex`
- `openai_frontier_balanced` -> `gpt-5.4`
- `openai_frontier` -> `gpt-5.5`
- `openai_frontier_pro` -> `gpt-5.5-pro`
- `openai_legacy_reasoning` -> `gpt-5`
- `openai_non_reasoning` -> `gpt-4.1`
- backward-compatible alias: `openai_ultra_cheap_legacy` -> `openai_classifier_nano`

### Role mappings / defaults

- `mechanical_worker`: `gpt-5.4-nano`, low, flex->default
- `classification_worker`: `gpt-5-nano`, none, flex/default, no patch, manual/reserved unless selected by config/policy
- `simple_builder`: `gpt-5.4-mini`, low, flex->default
- `general_builder`: `gpt-5.4-mini`, low/medium, flex/default
- `coding_optimized_builder`: `gpt-5.3-codex`, medium, default
- `frontier_coding_reviewer`: `gpt-5.3-codex`, high, default, no direct patch
- `frontier_balanced_reviewer`: `gpt-5.4`, medium/high, default, no direct patch
- `frontier_reviewer`: `gpt-5.5`, medium/high, default, no direct patch
- `emergency_pro_reviewer`: `gpt-5.5-pro`, high, default/batch, manual approval, no direct patch
- `legacy_reasoning_fallback`: `gpt-5`, low/medium fallback only
- `non_reasoning_instruction_follower`: `gpt-4.1`, no reasoning fallback only
- backward-compatible role alias: `ultra_cheap_classifier` -> `classification_worker`

### Escalation policy

- builder first with smallest likely-success role.
- escalate on non-convergence/high-risk/diagnosis-needed.
- frontier reviewer default mode is diagnosis-only.

### Flex policy

- flex preferred for lower-cost builder calls.
- fallback to default when transient flex failure thresholds are reached.
- fallback bounded by count and fallback budget.

### Pricing assumptions

- All pricing is config-driven.
- includes source URL/date + tier-specific values.
- no hardcoded pricing logic in orchestration decisions.

### Safety assumptions

- model outputs never directly execute shell.
- patch applies only through deterministic safety pipeline.
- validators remain source of truth.

---

## 5) Current Implementation Status

### Works now

- Provider-backed role execution path.
- OpenAI provider implementation and fake provider tests.
- Strict patch safety and validator flow.
- Rollback/checkpoint safety.
- Budget and limit pre-checking.
- Service-tier fallback behavior.
- Full test suite passing in this session.

### Scaffolded / placeholder

- Real diagnosis reviewer integration beyond dry-run placeholder logic.
- Some reviewer behavior remains diagnosis-contract focused, not full autonomous repair.

### Remaining legacy

- Terminology alias `ultra_cheap_classifier` intentionally retained for catalog clarity.
- Some wording “legacy” retained intentionally for fallback roles.

### OpenCode dependency status

- Runtime path removed (`coding_orchestrator/tools/opencode_runner.py` deleted).
- OpenCode setup docs removed.
- Legacy OpenCode tests replaced/migrated.

### Requires migration still

- No critical runtime dependency migration left for OpenCode.
- Remaining effort is consolidation/cleanup/commit discipline and any extra naming preferences.

---

## 6) Current Blockers and Risks

- Engine coupling risk:
  - `engine.py` remains central and dense; future refactors should isolate routing/diagnosis/budget orchestration methods further.
- Naming risk:
  - “ultra_cheap” terminology may still trigger policy discussion even though not legacy runtime behavior.
- Docs cleanup risk:
  - docs were heavily rewritten in one sweep; future maintainers should verify editorial consistency and operator clarity.
- Runtime migration risk:
  - provider configuration failures can alter behavior (dry-run fallback warning path exists).
- Testing risk:
  - strong unit coverage; still requires cautious integration testing for real OpenAI calls.
- OpenAI API assumptions:
  - Responses API field behavior can evolve; ensure periodic doc verification.
- Flex support assumptions:
  - fallback logic assumes flex may fail transiently; account-level behavior can vary.
- Reasoning assumptions:
  - role defaults assume capability/latency/cost balance; may need recalibration per real workloads.

---

## 7) Exact Remaining Phase 3 Tasks (Continuation Checklist)

1. Review working tree and split changes into coherent commit groups (runtime/tests/docs).
2. Decide if `ultra_cheap_classifier` wording stays or should be renamed (optional policy decision).
3. Re-run cleanup searches after any further edits:
   - `rg -i "opencode|open code|OpenCode"`
   - `rg -i "legacy_opencode|opencode_runner|OpenCodeRunner"`
   - `rg -i "gpt-5.1-codex-mini|gpt-5.2-codex"`
4. Re-verify service-tier fallback telemetry naming in reports and external docs.
5. Manual doc QA pass for operator usage clarity and command correctness.
6. Final validation:
   - `.venv/bin/ruff check .`
   - `.venv/bin/mypy .`
   - `.venv/bin/pytest`
7. Prepare final Phase 3 commit(s) (not done in this session).

---

## 8) File-Level Migration Map

| File | Current purpose | Migration status | Action |
|---|---|---|---|
| `coding_orchestrator/orchestrator/engine.py` | main workflow runtime | migrated to provider path | keep, consider future decomposition |
| `coding_orchestrator/models/provider.py` | provider contracts | complete | keep |
| `coding_orchestrator/models/fake_provider.py` | deterministic test provider | complete | keep |
| `coding_orchestrator/models/openai_provider.py` | OpenAI Responses integration | complete | keep |
| `coding_orchestrator/config.py` | schema + defaults + pricing/catalog | heavily migrated | keep, future cleanup optional |
| `coding_orchestrator/orchestrator/budget.py` | budget estimates/ledger/limits | migrated naming + fallback behavior | keep |
| `coding_orchestrator/orchestrator/tier_policy.py` | service-tier fallback state | migrated | keep |
| `coding_orchestrator/orchestrator/diagnosis.py` | diagnosis packet + contract | migrated naming | keep |
| `coding_orchestrator/orchestrator/convergence.py` | convergence decisions | migrated action naming | keep |
| `coding_orchestrator/tools/patch.py` | patch parse/apply safety | preserved safety, wording updated | keep |
| `coding_orchestrator/tools/opencode_runner.py` | legacy OpenCode runner | removed | delete (already deleted in WT) |
| `tests/test_engine_provider_path.py` | provider path integration tests | migrated | keep |
| `tests/test_patch_and_git_safety.py` | patch/git safety tests | new replacement | keep |
| `tests/test_opencode_and_patch.py` | legacy OpenCode tests | removed | delete (already deleted in WT) |
| `README.md` | project entry docs | rewritten | keep |
| `AGENTS.md` | local contributor/runtime rules | rewritten | keep |
| `docs/*` main set | architecture/config/safety/cost/roles | rewritten | keep |
| `docs/OPENCODE_SETUP.md` | legacy setup | removed | delete (already deleted in WT) |
| `docs/OPEN_CODE_SETUP.md` | legacy setup alias | removed | delete (already deleted in WT) |

---

## 9) Search / Reference Cleanup Status

- Remaining OpenCode refs:
  - none in current search (`rg -i "opencode|open code|OpenCode"` returned no matches).
- Remaining cheap/expensive refs:
  - none of legacy runtime identifiers; only intentional role/alias wording around `ultra_cheap_classifier`.
- Remaining Gemini refs:
  - none in current search (`rg -i "gemini"` returned no matches).
- Remaining deprecated model refs:
  - none (`gpt-5.1-codex-mini`, `gpt-5.2-codex` absent).
- Intentionally preserved historical/compatibility refs:
  - `openai_ultra_cheap_legacy` alias
  - `ultra_cheap_classifier` role name
  - fallback role names containing `legacy`

---

## 10) Validation State

Latest full run in this session:

- Ruff: `All checks passed!`
- Mypy: `Success: no issues found in 68 source files`
- Pytest: `73 passed` (full suite)
- Current passing test count: **73**

---

## 11) Recommended Next-Step Prompt

Suggested continuation prompt:

> Continue from `docs/SESSION_HANDOFF_PHASE3.md`. Do a final Phase 3 review-only pass: verify no unintended behavior regressions, confirm docs/config consistency, run cleanup searches and full validation, then prepare a clean staged commit plan (runtime/tests/docs split) without committing until asked.

Recommended model: `gpt-5.3-codex`  
Recommended reasoning effort: `high`  
Safety precautions:
- do not bypass patch safety/validators/rollback.
- no model-generated shell execution.
- keep OpenAI provider env-key-only behavior.

---

## 12) API Migration Notes

### Direct OpenAI usage continuation

- Runtime provider: `coding_orchestrator/models/openai_provider.py`
- Expected env var: `OPENAI_API_KEY` (or configured env var key in config).
- Enable live calls with:
  - `providers.openai.runtime_enabled: true`
- Keep fake provider for tests and non-network runs.

### Fake provider mode

- Use provider override in tests (`FakeModelProvider`).
- No network/API key required.

### Test execution without real API calls

- Default test suite uses fake provider and/or disabled live provider mode.
- Run:
  - `.venv/bin/pytest`

### Safety defaults

- `allow_frontier_direct_patch: false`
- `providers.openai.runtime_enabled: false` by default in config example
- strict patch and validator gates remain active.

---

## 13) Repository Reproducibility Commands

From repo root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

Validation:

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

Run orchestrator (fake-provider style / no live API):

```bash
cp config.example.yaml config.yaml
# keep providers.openai.runtime_enabled: false
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
```

Run orchestrator with OpenAI provider enabled:

```bash
export OPENAI_API_KEY="..."
# set providers.openai.runtime_enabled: true in config.yaml
.venv/bin/python -m coding_orchestrator.app run --task tasks/example_task.md
```

---

## 14) Session Continuity Notes

Important decisions made:

- OpenCode runtime path removed to satisfy pure Python + OpenAI architecture direction.
- Capability-role routing adopted to replace hard cheap/expensive model buckets.
- `gpt-5.3-codex` retained as coding-optimized role model.
- `gpt-5.4-mini` and `gpt-5.4-nano` used as default builder/mechanical role baselines.
- Flex/default tier policy preserved because cost control + resilience are core design constraints.
- Direct shell execution by models remains disabled; shell execution stays deterministic and policy-controlled.

Rejected approaches:

- Allowing frontier/pro models as default direct patchers (rejected by policy).
- Allowing model output to run arbitrary commands (rejected by safety constraints).
- Hardcoding pricing in logic (rejected; pricing remains config-driven).

---

## 15) Handoff End State

- This document is intended to allow immediate continuation from any new session/environment.
- No further refactor implementation was performed after creating this handoff package.

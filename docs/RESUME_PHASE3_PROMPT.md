# Resume Prompt For Fresh Codex Session (Phase 3)

Paste the full prompt below into a brand-new Codex session.

---

You are starting with zero prior context. Reconstruct the full project state from repository artifacts and continue Phase 3 safely.

## Session mode

- Do deterministic repository reconstruction first.
- Do not assume any prior conversation history.
- Work from repository files and git state only.

## 1) Reconstruct repository state

Read these files first:

- `docs/SESSION_HANDOFF_PHASE3.md`
- `docs/ARCHITECTURE_STATE_SNAPSHOT.md`
- `phase3_wip_status.txt`

Then run:

```bash
git branch --show-current
git log --oneline -3
git tag --list
git status --short
```

Confirm expected baseline:

- Branch: `refactor/openai-multimodel-no-opencode`
- Latest stable checkpoint commit: `70b18d4` (`Add Phase 3 session handoff documentation`)
- Safety tags:
  - `after-phase-2-5-openai-model-catalog`
  - `before-openai-multimodel-refactor`

If mismatched, stop and report exact differences before editing.

## 2) Restore WIP state safely

You may be on a machine/session where WIP is not loaded yet.

1. Inspect whether Phase 3 changes are already present:

```bash
git status --short
```

2. Only if needed, test patch applicability:

```bash
git apply --check phase3_wip.patch
```

3. Apply patch only if not already present:

```bash
git apply phase3_wip.patch
```

4. Re-verify:

```bash
git status --short
```

Important: avoid duplicate patch application. If `git apply --check` fails because changes already exist, do not force apply.

## 3) Reconstruct architecture understanding

Current target architecture is capability-role, OpenAI-provider-centric orchestrator:

- Orchestrator controls policy and flow.
- Provider abstraction:
  - `models/provider.py` contract
  - `models/openai_provider.py` real provider
  - `models/fake_provider.py` test/dry path
- Role-based routing (not cheap/expensive hard buckets).
- Pricing is config-driven (editable, metadata included).
- Reasoning effort is request-level config.
- Service-tier policy:
  - prefer `flex` for cheap non-urgent work
  - fallback to `default`
  - `priority` disabled by default
- Patch safety:
  - strict patch contract
  - file boundary checks
  - forbidden path checks
  - `git apply --check`
- Rollback/checkpoint safety preserved.
- Validators preserved and mandatory.
- Budget/limits pre-checks preserved.
- No model-generated shell execution allowed.

## 4) Reconstruct model routing matrix

Preferred defaults:

- `mechanical_worker` -> `gpt-5.4-nano`
- `classification_worker` -> `gpt-5-nano`
- `simple_builder` -> `gpt-5.4-mini`
- `general_builder` -> `gpt-5.4-mini`
- `coding_optimized_builder` -> `gpt-5.3-codex`
- `frontier_coding_reviewer` -> `gpt-5.3-codex`
- `frontier_reviewer` -> `gpt-5.5`
- `emergency_pro_reviewer` -> `gpt-5.5-pro`

Clarifications:

- `mechanical_worker` is the active routed nano role for tiny deterministic coding or bounded patch work.
- `classification_worker` is a canonical/manual classification-summarization role and is not currently auto-selected by the router.
- `ultra_cheap_classifier` and `openai_ultra_cheap_legacy` are backward-compatible aliases only.
- `reasoning_effort` is request-level policy.
- `medium/high` are not separate model IDs.
- `flex` preferred for cheap non-urgent work.
- `default` is fallback tier.
- `priority` remains disabled by default.

## 5) Reconstruct current Phase 3 state

Status:

- Phase 1: completed
- Phase 2: completed
- Phase 2.5: completed
- Phase 3: partially started, intentionally paused due session constraints

Assume incomplete areas still require verification:

- OpenCode removal may be incomplete in working tree reconciliation.
- Legacy naming cleanup may be incomplete.
- Docs cleanup may be incomplete.
- Runtime cleanup normalization may be incomplete.

Do not assume completion until re-validated from current tree and tests.

## 6) Remaining Phase 3 objectives checklist

- [ ] Remove remaining OpenCode runtime/config/code references (if any remain).
- [ ] Normalize legacy cheap/expensive naming to capability-role terms where required.
- [ ] Finish docs cleanup and consistency pass.
- [ ] Finalize config cleanup/defaults consistency.
- [ ] Complete/verify test migration to provider-path assumptions.
- [ ] Confirm runtime backend normalization (`role_provider` only behavior).
- [ ] Run full validation repeatedly during changes:
  - `ruff`
  - `mypy`
  - `pytest`
- [ ] Prepare final small, logical commits for Phase 3 completion.

## 7) Safety requirements (non-negotiable)

Do not weaken:

- validators
- rollback behavior
- git checkpointing
- patch safety boundary checks
- budget protections
- fake provider test path
- no-shell-execution-by-model policy

No hosted shell/apply-patch model tools.
No direct frontier/pro patching by default.

## 8) Recommended runtime/model for this continuation

Use:

- Model: `gpt-5.3-codex`
- Reasoning effort: `high`

Why:

- Phase 3 is cross-file cleanup/removal/normalization work.
- Requires careful coupling analysis and high-confidence refactor hygiene.
- `gpt-5.3-codex` is preferred for coding-centric multi-file changes.
- Mini models are not preferred for final cleanup/removal correctness passes.

## 9) Recommended session workflow

1. Inspect repository and patch state first.
2. Confirm git status before every edit batch.
3. Make small scoped edits.
4. Avoid giant deletion/refactor in one pass.
5. Validate frequently:

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

6. Report changed files and residual risks after each batch.
7. Do not auto-commit until asked.

## 10) Expected output discipline

- Keep actions deterministic and auditable.
- Include exact file lists changed.
- Include residual cleanup search results:
  - `rg -i "opencode|open code|OpenCode"`
  - `rg -i "cheap|expensive|gemini|legacy_opencode|opencode_runner|OpenCodeRunner"`
  - `rg -i "gpt-5.1-codex-mini|gpt-5.2-codex"`
- End each milestone with current validation results and next safe step.

---

Start now by executing Section 1 and report findings before any code edits.

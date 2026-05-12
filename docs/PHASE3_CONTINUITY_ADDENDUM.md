# Phase 3 Continuity Addendum

This addendum complements:
- `docs/SESSION_HANDOFF_PHASE3.md`
- `docs/ARCHITECTURE_STATE_SNAPSHOT.md`
- `docs/RESUME_PHASE3_PROMPT.md`

It is a continuity/navigation layer for future Codex sessions.

## 1) Required Reading Order

Read in this exact order before implementation:

1. `docs/SESSION_HANDOFF_PHASE3.md`  
   Why: complete state narrative, decisions, risks, and phase status.
2. `docs/ARCHITECTURE_STATE_SNAPSHOT.md`  
   Why: fast architecture/status checksum.
3. `docs/RESUME_PHASE3_PROMPT.md`  
   Why: ready-to-run bootstrap and guardrails for a new session.
4. `docs/OPENAI_MULTIMODEL_REFACTOR_PLAN.md`  
   Why: canonical phase intent, target architecture, and migration criteria.
5. `phase3_wip_status.txt`  
   Why: expected uncommitted working-tree footprint.
6. `phase3_wip.patch`  
   Why: recoverable WIP delta for session/machine transfer.

## 2) Repository Reconstruction Procedure

Run this startup sequence in a fresh session:

```bash
git branch --show-current
git log --oneline -3
git tag --list
git status --short
```

Expected anchors:
- branch: `refactor/openai-multimodel-no-opencode`
- stable commit: `70b18d4` (`Add Phase 3 session handoff documentation`)
- safety tags:
  - `after-phase-2-5-openai-model-catalog`
  - `before-openai-multimodel-refactor`

Patch restoration procedure:

```bash
git status --short
git apply --check phase3_wip.patch
git apply phase3_wip.patch
git status --short
```

Duplicate patch avoidance:
- If `git apply --check` fails because changes already exist, do **not** force apply.
- Compare against `phase3_wip_status.txt` and reconcile manually.

Validation cadence during restore/implementation:

```bash
.venv/bin/ruff check .
.venv/bin/mypy .
.venv/bin/pytest
```

## 3) Current Phase Dependency Map

- Phase 1: complete (schema/roles/pricing foundations).
- Phase 2: complete (provider path integrated).
- Phase 2.5: complete (model catalog/routing/pricing refresh).
- Phase 3: intentionally paused mid-cleanup.

Dependencies:
- Final cleanup depends on confirming exact WIP state first.
- Naming/docs cleanup depends on backend normalization being correct.
- Final commit prep depends on full validation pass.

Must happen before final cleanup:
- verify branch/commit/tags/status
- verify patch state (already applied vs needs apply)
- verify safety behavior remains intact

Must not be removed accidentally:
- validator flow
- rollback/checkpoint flow
- patch boundary checks and `git apply --check`
- budget and limits enforcement
- fake provider test path
- no model shell-execution policy

## 4) Remaining Phase 3 Task Ordering

1. OpenCode runtime removal completion check  
   Dependencies: patch state confirmed.  
   Risks: partial removal leaves broken imports/paths.  
   Validation: targeted tests + full suite.

2. Backend normalization  
   Dependencies: runtime paths audited.  
   Risks: fallback regressions, provider runtime drift.  
   Validation: engine/provider-path tests.

3. Naming normalization  
   Dependencies: runtime stable first.  
   Risks: broad rename breaks reports/tests/contracts.  
   Validation: grep audit + unit tests.

4. Config cleanup  
   Dependencies: naming baseline settled.  
   Risks: invalid defaults or schema mismatch.  
   Validation: config parse tests + mypy.

5. Docs cleanup  
   Dependencies: final runtime/config semantics known.  
   Risks: stale instructions causing operator errors.  
   Validation: doc command spot-check.

6. Test migration completion  
   Dependencies: code/docs naming stable.  
   Risks: hidden legacy assumptions.  
   Validation: full pytest.

7. Validation stabilization  
   Dependencies: all above complete.  
   Risks: intermittent failures ignored too early.  
   Validation: repeated ruff/mypy/pytest clean runs.

8. Final cleanup search  
   Dependencies: migration complete.  
   Risks: missed legacy references.  
   Validation:
   - `rg -i "opencode|open code|OpenCode"`
   - `rg -i "cheap|expensive|gemini|legacy_opencode|opencode_runner|OpenCodeRunner"`
   - `rg -i "gpt-5.1-codex-mini|gpt-5.2-codex"`

9. Final validation  
   Dependencies: cleanup search clear/intentional-only.  
   Risks: last-minute drift.  
   Validation: full lint/type/test.

10. Final commit preparation  
   Dependencies: all checks green.  
   Risks: giant mixed commit.  
   Validation: commit splitting review by scope.

## 5) Architecture Continuity Notes

Preserve these decisions:
- capability-role routing (not hard cheap/expensive buckets)
- provider abstraction contract
- fake provider for deterministic tests
- config-driven pricing defaults with metadata
- request-level reasoning effort policy
- service-tier policy (`flex` preferred, `default` fallback, `priority` off by default)
- flex/default fallback behavior
- strict no-shell-execution-by-model rule
- validator gating after patch apply
- rollback + git checkpoint safety
- strict patch safety model
- budget pre-check and ledger enforcement

Non-negotiable safety constraints:
- no weakening validators
- no bypassing rollback/checkpointing
- no bypassing patch checks
- no direct model shell execution
- no disabling budget/limit guards

Forbidden regressions:
- reintroducing OpenCode runtime dependence
- frontier/pro direct patch defaults
- removing fake provider coverage
- hardcoding pricing in runtime logic

## 6) Dangerous Failure Modes

Watch for:
- quota exhaustion during large one-shot deletions
- context fragmentation across long sessions
- partial OpenCode removal leaving inconsistent state
- accidental validator weakening
- accidental shell execution enablement
- accidental patch-safety bypass/removal
- duplicate `phase3_wip.patch` application
- giant unreviewed commits
- provider-coupling regressions in engine

## 7) Recommended Workflow Discipline

- Keep edits and commits small and logical.
- Create checkpoint tags before risky cleanup batches.
- Validate frequently (ruff/mypy/pytest).
- Use staged cleanup rather than one-pass deletion.
- Review search/replace results manually.
- Preserve recovery artifacts (`phase3_wip.patch`, handoff docs) until final merge.

## 8) Recommended Continuation Runtime

- Model: `gpt-5.3-codex`
- Reasoning effort: `high`

Why:
- Phase 3 is coupled multi-file cleanup/deletion with architectural risk.
- Requires precise dependency/safety reasoning and contract awareness.
- Mini-class models are cost-efficient but less reliable for final migration cleanup.

## 9) Recovery Artifact Inventory

Current artifacts:
- Commit `70b18d4`: documentation checkpoint for handoff package.
- Commit `ef60099`: phase 2/2.5 baseline checkpoint.
- Safety tags:
  - `after-phase-2-5-openai-model-catalog`
  - `before-openai-multimodel-refactor`
- `phase3_wip.patch`: full uncommitted Phase 3 diff recovery artifact.
- `phase3_wip_status.txt`: short status snapshot for patch-state comparison.
- `docs/SESSION_HANDOFF_PHASE3.md`: comprehensive continuity handoff.
- `docs/ARCHITECTURE_STATE_SNAPSHOT.md`: compact architecture/status snapshot.
- `docs/RESUME_PHASE3_PROMPT.md`: ready-to-paste fresh-session bootstrap prompt.

Artifact purpose summary:
- tags/commits anchor reproducible starting points
- patch/status restore uncommitted work
- docs reconstruct architecture intent and safe execution flow

## 10) Resume Checklist (Pre-Coding)

Repository verification:
- [ ] branch/commit/tag checks completed
- [ ] current `git status --short` captured

Patch verification:
- [ ] determined whether WIP already present
- [ ] `git apply --check phase3_wip.patch` evaluated
- [ ] patch applied only if necessary

Reading completion:
- [ ] required reading order completed

Validation baseline:
- [ ] initial `ruff` baseline run
- [ ] initial `mypy` baseline run
- [ ] initial `pytest` baseline run

Architecture understanding confirmation:
- [ ] role/provider/fallback/safety model confirmed

Safety confirmation:
- [ ] validators/rollback/checkpoint/patch-safety/budget protections confirmed intact

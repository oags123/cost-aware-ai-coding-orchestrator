# Architecture

## Runtime flow

`task -> classify -> choose role -> build context -> provider call -> parse patch -> patch safety checks -> validators -> retry/escalate`

## Primary components

- `orchestrator/engine.py`: bounded workflow controller.
- `orchestrator/budget.py`: pre-call estimates + SQLite ledger + budget gates.
- `orchestrator/limits.py`: hard context/output/patch/stdout/stderr limits.
- `orchestrator/tier_policy.py`: flex/default fallback policy.
- `models/provider.py`: provider request/response contracts.
- `models/openai_provider.py`: OpenAI Responses API integration.
- `models/fake_provider.py`: deterministic test provider.
- `tools/patch.py`: strict patch contract parsing + safe apply.
- `tools/git.py`: checkpoint, rollback, scoped commit.

## Safety invariants

- Model output cannot execute shell commands.
- Only deterministic wrappers execute shell commands.
- Patch apply always runs boundary checks and `git apply --check`.
- Validation always runs after patch application.
- Rollback is required on failure paths.

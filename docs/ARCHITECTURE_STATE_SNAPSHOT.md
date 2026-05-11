# Architecture State Snapshot (Phase 3 Handoff)

Date: 2026-05-11 UTC

## Runtime backend state

- Active backend: `role_provider`
- Legacy OpenCode runner: removed from runtime path and deleted from tree
- Provider implementations:
  - `OpenAIProvider` (env-key gated runtime)
  - `FakeModelProvider` (tests/no-network)

## Safety-critical invariants (current)

- No model-generated shell execution.
- Deterministic subprocess wrappers with allowlist/timeouts.
- Strict patch contract + boundary validation + `git apply --check`.
- Validators run after patch apply.
- Rollback/checkpoint behavior preserved.

## Cost/routing state

- Role-driven model selection with config aliases.
- Service-tier policy: flex primary, default fallback.
- Pricing is config-driven with source metadata.
- Budget and limits checked before provider calls.

## Test/validation snapshot

- Latest suite in this session: `73 passed`.
- Ruff clean.
- Mypy clean.

## Working tree snapshot

- Phase 3 migration edits are present and uncommitted.
- See `git status --short` and `docs/SESSION_HANDOFF_PHASE3.md` for full file-level detail.

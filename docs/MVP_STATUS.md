# MVP Status

Current MVP is operational with:

- role-provider runtime backend
- OpenAI provider implementation (opt-in), with typed error handling so real SDK failures
  drive the flex->default fallback and retries rather than being silently unguarded
- fake provider test mode
- patch safety/validators/rollback/checkpointing, including symlink/absolute-path/traversal
  rejection and stash-based preservation of pre-existing uncommitted work
- accurate, distinct task outcomes (`completed` vs `dry_run` vs `no_change` vs `blocked` vs
  `escalated` vs `failed` vs `timeout`) — a disabled provider or a no-op response is never
  reported as a successful completion
- reconciled budget ledger (pre-call estimate + actual token usage/cost, idempotent)
- bounded budget/runtime/context/output policies
- convergence + diagnosis-only escalation path (diagnosis reviewer itself is
  dry-run/placeholder only — no live model integration; see `AGENTS.md` known limitations)
- advisory concurrency lock and HEAD-change detection
- CI running tests/lint/type-check on every push and PR

Not implemented / known limitations are tracked in `AGENTS.md` and `README.md`.

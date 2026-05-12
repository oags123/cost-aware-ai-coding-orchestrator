# Cost Control

## Core controls

- Pre-call budget estimate for each model call.
- Task/project/role budget gates before provider execution.
- SQLite budget ledger for all estimated/blocked calls.
- Service-tier aware routing (`flex` preferred, `default` fallback).
- Bounded retries with convergence checks.

## Pricing defaults

Pricing is config-driven in `pricing.roles` with metadata:

- `source_url`
- `retrieved_or_verified_date`
- `input_usd_per_1m_tokens`
- `cached_input_usd_per_1m_tokens` (nullable)
- `output_usd_per_1m_tokens`
- optional long-context fields

No pricing is hardcoded in runtime business logic.

## Reasoning headroom

Reasoning tokens are billed as output and consume context. Reserve output and context headroom for diagnosis/refactor tasks.

## Service tier policy

- Use `flex` by default for non-urgent builder work.
- If flex times out or returns resource-unavailable conditions repeatedly, fallback to `default`.
- Keep `priority` disabled by default.
- Record selected service tier in request metadata and budget ledger.

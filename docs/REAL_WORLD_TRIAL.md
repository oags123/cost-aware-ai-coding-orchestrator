# Real-World Trial

## Goal

Run one narrow bounded task with real OpenAI provider calls and verify:

- role selection is expected
- patch contract and safety checks pass
- validators pass
- budget ledger records provider/model/service tier metadata

## Preconditions

- `OPENAI_API_KEY` exported
- `providers.openai.runtime_enabled: true`
- clean git branch

## Trial checklist

1. Create a tiny task with strict `allowed_files`.
2. Run one task.
3. Inspect report and git diff/commit.
4. Confirm no policy/safety regression.

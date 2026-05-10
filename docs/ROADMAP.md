# Roadmap

## Immediate Next Technical Milestone

Run one controlled real OpenCode task in a clean clone or branch:

1. Install/authenticate OpenCode.
2. Configure `opencode.enabled=true` and `opencode.dry_run=false`.
3. Create a task with one or two `allowed_files`.
4. Run the task.
5. Inspect patch, validations, state, logs, rollback behavior, and commit behavior.

## Near-Term Follow-Ups

- Add an integration test harness with a fake `opencode` executable that emits deterministic patches.
- Add optional OpenCode `--format json` handling if raw stdout is brittle.
- Improve escalation package ergonomics for manual review.
- Add better reporting for queue runs.
- Add documented examples for `fix_bug` and `write_tests` tasks.

## Later

- Reviewer model integrations.
- More precise provider cost accounting.
- Provider routing, including Gemini, only after the local OpenCode path is proven.
- Docker hardening for server execution.

## Not Planned For Phase 1

- LangChain, LangGraph, CrewAI, AutoGen
- web UI
- cloud deployment
- Kubernetes
- semantic memory, embeddings, RAG, vector DB


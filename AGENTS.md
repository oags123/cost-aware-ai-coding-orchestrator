# AGENTS.md

## Project goal

Build Phase 1 of a Cost-Aware AI Coding Orchestrator.

This is a controlled workflow engine, not a free-roaming AI agent.

The orchestrator must control:
request → classify → route → build context → execute bounded step → validate → retry/escalate → log result.

## Hard rules

- Do not build a web UI.
- Do not build LangChain, LangGraph, CrewAI, or AutoGen integration in Phase 1.
- Use plain Python.
- Use typed state with Pydantic.
- Use YAML config.
- Use SQLite or JSON for persistent state.
- Use subprocess with timeouts for shell commands.
- Never allow unlimited retries.
- Never allow unlimited runtime.
- Never allow unlimited cost.
- Do not let LLMs execute arbitrary shell commands directly.
- The orchestrator runs deterministic tools itself: git, pytest, ruff, mypy.
- LLMs are only called inside bounded steps.

## Phase 1 scope

Implement:
- task state
- task classifier
- model router
- workflow engine
- OpenCode runner interface
- Codex/Claude escalation interface as placeholders
- git manager
- validator runner
- patch/file boundary validator
- timeout guard
- budget guard
- logging
- CLI entrypoint

## Validation commands

Use:
- ruff check .
- mypy .
- pytest

## Output requirement

Create a working Python package with tests and a README.

# MVP Status

## Complete Enough For Local Dry-Run Use

- CLI entrypoint
- task loading
- dependency ordering
- classification and routing
- dry-run builder execution
- validation pipeline
- retry loop
- logging and state files
- escalation package generation
- Docker scaffold
- unit tests

## Complete But Needs Real-World Trial

- real OpenCode subprocess invocation
- strict patch parsing
- safe patch application
- git checkpoint/rollback
- scoped task commits

These are implemented and tested with mocks/temp repositories, but should be exercised with one carefully scoped real OpenCode task before broader use.

## Placeholder

- reviewer/escalation model API integrations
- accurate provider billing/cost accounting
- specialized implementations for scaffolded workflows
- long-term memory beyond simple project facts storage

## Deferred

- web UI
- cloud deployment
- Kubernetes
- Gemini/provider integrations
- embeddings/RAG/vector database
- multi-agent conversation systems


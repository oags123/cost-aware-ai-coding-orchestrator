# Future Provider Integration

Status: planning only.

Provider integration is deferred until the local OpenCode builder path is proven.

## Scope

Future provider work may include:

- OpenCode provider/model discovery
- provider pricing tables
- usage/cost ingestion
- Gemini routing
- OpenAI/Codex reviewer diagnosis
- Claude reviewer diagnosis

## Non-Goals For Phase 1.5

- provider marketplace
- automatic model shopping
- uncontrolled fallback chains
- expensive model as default coder
- direct provider SDK sprawl in the workflow engine

## Design Direction

Add provider abstractions around model roles, not around arbitrary agents:

```yaml
providers:
  opencode:
    executable: opencode
  openai:
    enabled: false
  gemini:
    enabled: false
```

Each provider must expose:

- model identifier
- role compatibility
- token limits
- pricing estimate
- call timeout
- output contract

## Gemini Notes

Do not hardcode Gemini model IDs or prices without a freshness/audit process. Gemini model availability and pricing change over time. Treat Gemini integration as a separate provider milestone.


# OpenCode Setup

OpenCode is not installed by this Python package. Install and authenticate it
separately before enabling real mode.

Official docs:

- OpenCode intro/install: <https://opencode.ai/docs/>
- OpenCode CLI: <https://opencode.ai/docs/cli/>
- Gemini models: <https://ai.google.dev/gemini-api/docs/models>
- Gemini pricing: <https://ai.google.dev/gemini-api/docs/pricing>
- Gemini Flex inference: <https://ai.google.dev/gemini-api/docs/flex-inference>

## Install OpenCode

The OpenCode docs list several install options. Common Linux options include:

```bash
curl -fsSL https://opencode.ai/install | bash
```

or:

```bash
npm install -g opencode-ai
```

Verify:

```bash
command -v opencode
opencode --version
```

## Authenticate Providers

OpenCode manages provider credentials outside this repository.

```bash
opencode auth login
opencode auth list
```

For Gemini, either authenticate through OpenCode or expose the Gemini key in
the environment:

```bash
export GEMINI_API_KEY="..."
```

Do not put API keys in `config.yaml`, task files, committed docs, or logs.

## Find The Model String

OpenCode expects models in `provider/model` format.

```bash
opencode models --refresh
opencode models
opencode models google
```

Use the exact string printed by OpenCode in `config.yaml`.

The orchestrator config currently defaults its cheap-builder pricing/model
entries to Gemini Flash-Lite planning values. Google documentation currently
lists Gemini 3.1 Flash-Lite as a stable Flash-Lite model, and Flex as a
lower-cost, best-effort, variable-latency inference tier. Before paid usage,
audit the exact model id, OpenCode provider prefix, and prices against current
Google and OpenCode output.

## Configure The Orchestrator

Real mode requires:

```yaml
opencode:
  enabled: true
  dry_run: false
  executable: "opencode"
  default_model: "google/gemini-3.1-flash-lite"
  max_runtime_seconds: 300
  output_mode: "unified_diff"
  allowed_env_vars:
    - "GEMINI_API_KEY"
  extra_args: []
```

Replace `google/gemini-3.1-flash-lite` with the exact `provider/model` string
from `opencode models`.

The runner calls:

```bash
opencode run --model <provider/model> <prompt>
```

It does not pass `--dangerously-skip-permissions`. Do not add that flag to
`extra_args` for normal operation.

## Environment Forwarding

The orchestrator forwards only:

- `PATH`
- `HOME`
- `XDG_CONFIG_HOME`
- `XDG_DATA_HOME`
- `TMPDIR`
- names listed in `opencode.allowed_env_vars`

For Gemini through OpenCode, include:

```yaml
opencode:
  allowed_env_vars:
    - "GEMINI_API_KEY"
```

If OpenCode uses credentials stored under your home directory, `HOME` and
`XDG_*` must point to the same location where OpenCode is authenticated.

## Flex And Standard

The current tier policy:

- selects Flex by default for cheap builder work
- retries Flex according to timeout policy
- falls back to Standard only when timeout policy triggers
- blocks Standard fallback when count or budget caps are exceeded
- never falls back to GPT/frontier models for builder work

Current example config:

```yaml
inference:
  cheap_builder:
    default_tier: "flex"
    fallback_tier: "standard"
    flex:
      max_attempt_runtime_seconds: 600
      max_consecutive_timeouts: 2
      timeout_rate_threshold: 0.5
    max_standard_fallbacks_per_run: 1
    max_standard_fallback_cost_usd_per_run: 0.25
```

Google documents Flex as best-effort with variable latency and no server-side
automatic fallback to Standard. This repository implements its own bounded
client-side fallback policy.

## Smoke Test OpenCode Before Real Mode

Run a harmless OpenCode command outside the orchestrator:

```bash
opencode run --model <provider/model> "Reply with exactly: ok"
```

Then run the orchestrator dry-run smoke tests before switching to real mode.

## Missing OpenCode

If real mode is enabled and `opencode` is not on `PATH`, the task fails with a
clear installation note. It does not silently fall back to dry-run.

## Related Guides

- [User Guide](USER_GUIDE.md)
- [Real-World Trial Runbook](REAL_WORLD_TRIAL.md)
- [Configuration](CONFIGURATION.md)
- [Troubleshooting](TROUBLESHOOTING.md)

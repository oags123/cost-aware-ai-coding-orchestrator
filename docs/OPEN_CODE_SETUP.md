# OpenCode Setup

OpenCode is not installed by this package. Install and authenticate it separately.

Official docs: <https://opencode.ai/docs/cli/>

## Recommended Setup Flow

```bash
opencode auth login
opencode models --refresh
opencode models
```

Use the exact `provider/model` string in `config.yaml`:

```yaml
opencode:
  enabled: true
  dry_run: false
  executable: "opencode"
  default_model: "provider/model"
  output_mode: "unified_diff"
```

## Runner Behavior

The runner calls:

```bash
opencode run <prompt>
```

with `--model <provider/model>` when configured.

The prompt instructs OpenCode to return only a unified diff, or structured JSON when `output_mode` is configured for JSON patch output.

## Missing OpenCode

If real mode is enabled and `opencode` is not on PATH, the run fails clearly. It does not silently fall back to dry-run.

## Secrets

Do not put API keys in config files. Use environment variables and list only the variable names that may be forwarded:

```yaml
opencode:
  allowed_env_vars:
    - "OPENAI_API_KEY"
```


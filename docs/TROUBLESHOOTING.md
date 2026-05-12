# Troubleshooting

## OpenAI provider blocked

- Check `providers.openai.runtime_enabled`.
- Confirm `OPENAI_API_KEY` is set.
- Confirm `openai` Python package is installed.

## Budget blocked

- Inspect `report` budget fields.
- Reduce task scope or increase configured role budget.

## Limits blocked

- Inspect `report.limit_failures`.
- Reduce context/patch size or adjust limits deliberately.

## Patch rejected

- Ensure output is unified diff or structured JSON patch.
- Ensure touched files stay within task `allowed_files`.

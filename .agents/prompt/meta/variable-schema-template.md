# Variable Schema Template

## Use When

Use when a prompt should declare its runtime inputs clearly for Agent-driven
composition.

## Constraints

- Prefer explicit variables over hidden assumptions.
- Mark optional variables and safe defaults.
- Avoid leaking raw paths when artifact refs are available.
- Keep schema readable in Markdown.

## Prompt Template

Define variables for `{prompt_template}`.

Return:
- Required variables.
- Optional variables.
- Artifact refs consumed.
- Validation notes.
- Example invocation with placeholder values.

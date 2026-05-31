# Evidence Table Extraction

## Use When

Use when research notes are messy and need to become structured evidence for
Grouping, Content, or Review Agents.

## Constraints

- Preserve source refs and quote only short snippets when necessary.
- Convert vague claims into observable facts or mark them as interpretation.
- Remove login dialogs, tool errors, unrelated UI text, and diagnostic noise.
- Keep rows concise enough for downstream prompt context.

## Prompt Template

Extract an evidence table from `{research_notes}`.

Columns:
- `source_ref`
- `observed_fact`
- `audience_relevance`
- `content_use`
- `risk_or_uncertainty`
- `suggested_group`

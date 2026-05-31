# Prompt Regression Checklist

## Use When

Use when changing prompts that affect production content quality.

## Constraints

- Check route choice, Skill choice, template choice, schema validity, and output
  relevance.
- Include image artifact contamination checks.
- Include Feishu-only delivery checks.
- Keep checklist executable by tests or a reviewer.

## Prompt Template

Create a regression checklist for `{change_summary}`.

Return:
- Behaviors that must remain stable.
- New behavior to verify.
- Test commands or probes.
- Manual review items.
- Rollback warning signs.

# Prompt Template Spec

## Use When

Use when adding or refactoring prompt templates in this library.

## Constraints

- Every template must be reusable by an Agent, not tied to one hardcoded case.
- Include Use When, Constraints, and Prompt Template sections.
- Use variables for runtime context.
- Keep external source inspiration paraphrased and project-specific.

## Prompt Template

Design a prompt template for `{agent_or_phase}`.

Return:
- Intended Agent.
- Inputs and variables.
- Output shape.
- Required constraints.
- Anti-patterns the template prevents.

# Prompt Test Cases

## Use When

Use when a prompt template needs regression cases before becoming a formal
library asset.

## Constraints

- Include at least one happy path and one failure-prone path.
- Test semantic selection, not keyword matching.
- Include negative examples that should not select the template.
- Keep expected assertions concrete.

## Prompt Template

Create test cases for prompt template `{template_path}`.

Return:
- Positive request examples.
- Negative request examples.
- Expected selected categories.
- Expected generated constraints.
- Regression assertions.
